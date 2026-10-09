"""Only synthetic credentials and responses; no live website login calls."""

from datetime import timedelta

import httpx
import pytest
from fastapi import HTTPException
from starlette.requests import Request

from backend.config import Settings, settings
from backend.domain.website_owner import WebsiteOwner, utcnow
from backend.infra import website_identity_client as upstream
from backend.services.website_identity import verified_website_identity


def request(*headers):
    return Request({"type": "http", "headers": [(key.encode(), value.encode()) for key, value in headers]})


@pytest.fixture
def me(monkeypatch):
    state = {"status": 200, "body": {"success": True, "data": {"id": 12345}}, "calls": [], "error": None}

    def handler(req):
        state["calls"].append(req)
        if state["error"]:
            raise state["error"]("synthetic transport failure", request=req)
        return httpx.Response(state["status"], json=state["body"])

    def client(**options):
        assert options["follow_redirects"] is False
        assert 0 < options["timeout"] <= 10
        return httpx.Client(transport=httpx.MockTransport(handler), **options)

    monkeypatch.setattr(upstream, "Client", client)
    monkeypatch.setattr(settings, "website_identity_enabled", True)
    return state


def test_no_credentials_stays_guest_and_disabled_adapter_never_calls_upstream(me, monkeypatch):
    assert verified_website_identity(request()) is None
    monkeypatch.setattr(settings, "website_identity_enabled", False)
    with pytest.raises(HTTPException) as error:
        verified_website_identity(request(("authorization", "Bearer synthetic-disabled")))
    assert error.value.status_code == 503
    assert me["calls"] == []


@pytest.mark.parametrize("credential", ["synthetic.jwt.signature", "ts_synthetic_only"])
def test_me_maps_only_verified_id_and_rechecks_without_caching(me, credential, caplog):
    me["body"]["data"].update(role="admin", nickname="PRIVATE PROFILE", phone="PRIVATE PHONE")
    before = utcnow()
    identity = verified_website_identity(request(("authorization", "Bearer " + credential)))
    assert identity.external_user_id == "12345"
    assert before < identity.valid_until <= utcnow() + timedelta(seconds=settings.website_identity_max_request_seconds)
    owner = WebsiteOwner(customer_id="local-id", valid_until=identity.valid_until, revalidate=identity.revalidate)
    owner.check_current()
    assert len(me["calls"]) == 2
    for call in me["calls"]:
        assert str(call.url) == upstream.IDENTITY_URL
        assert call.method == "POST" and call.content == b""
        assert call.headers["authorization"] == "Bearer " + credential
        assert call.headers["token"] == credential
        assert "cookie" not in call.headers
    assert credential not in repr(identity) + repr(owner) + caplog.text
    assert "PRIVATE" not in repr(identity) + repr(owner) + caplog.text
    me["status"] = 401
    with pytest.raises(HTTPException) as error:
        owner.check_current()
    assert error.value.status_code == 401


@pytest.mark.parametrize("headers", [
    (("authorization", ""),), (("authorization", "Basic synthetic"),),
    (("authorization", "Bearer "),), (("authorization", "Bearer synthetic space"),),
    (("authorization", "Bearer synthetic\n"),), (("authorization", "Bearer " + "x" * 8192),),
    (("authorization", "Bearer one"), ("authorization", "Bearer two")),
    (("token", "synthetic-only"),),
    (("authorization", "Bearer one"), ("token", "two")),
    (("authorization", "Bearer one"), ("token", "one"), ("token", "one")),
])
def test_ambiguous_or_invalid_credentials_never_reach_upstream(me, headers):
    with pytest.raises(HTTPException) as error:
        verified_website_identity(request(*headers))
    assert error.value.status_code == 401 and me["calls"] == []


@pytest.mark.parametrize("body", [
    None, [], {"success": False, "data": {"id": 12345}}, {"success": 1, "data": {"id": 12345}},
    {"success": True}, {"success": True, "data": []}, {"success": True, "data": {"id": True}},
    {"success": True, "data": {"id": 0}}, {"success": True, "data": {"id": -1}},
    {"success": True, "data": {"id": "12345"}}, {"success": True, "data": {"id": 1.2}},
    {"success": True, "data": {"id": 10 ** 128}},
])
def test_unconfirmed_business_failures_or_malformed_profiles_deny_instead_of_guessing(me, body):
    me["body"] = body
    with pytest.raises(HTTPException) as error:
        verified_website_identity(request(("authorization", "Bearer synthetic")))
    assert error.value.status_code == 503


@pytest.mark.parametrize("status, expected", [(401, 401), (403, 503), (429, 503), (500, 503), (302, 503)])
def test_upstream_statuses_fail_closed(me, status, expected):
    me["status"] = status
    with pytest.raises(HTTPException) as error:
        verified_website_identity(request(("authorization", "Bearer synthetic")))
    assert error.value.status_code == expected


@pytest.mark.parametrize("error_type", [httpx.ConnectError, httpx.ReadTimeout])
def test_network_errors_do_not_expose_credentials_or_return_a_guest(me, error_type):
    me["error"] = error_type
    with pytest.raises(HTTPException) as error:
        verified_website_identity(request(("authorization", "Bearer synthetic-secret")))
    assert error.value.status_code == 503
    assert "synthetic-secret" not in str(error.value)


def test_credential_cannot_change_member_during_a_request(me):
    identity = verified_website_identity(request(("authorization", "Bearer synthetic"), ("token", "synthetic")))
    me["body"]["data"]["id"] = 54321
    with pytest.raises(HTTPException) as error:
        identity.revalidate()
    assert error.value.status_code == 401


@pytest.mark.parametrize("content", [b"not json", b"x" * 65537], ids=["invalid-json", "oversized"])
def test_invalid_or_oversized_responses_do_not_establish_identity(me, monkeypatch, content):
    monkeypatch.setattr(upstream, "Client", lambda **options: httpx.Client(
        transport=httpx.MockTransport(lambda _req: httpx.Response(200, content=content)), **options,
    ))
    with pytest.raises(HTTPException) as error:
        verified_website_identity(request(("authorization", "Bearer synthetic")))
    assert error.value.status_code == 503


@pytest.mark.parametrize("values", [
    {"website_identity_provider": " "}, {"website_identity_provider": " padded"},
    {"website_identity_provider": "x" * 65}, {"website_identity_timeout_seconds": 0},
    {"website_identity_timeout_seconds": 11}, {"website_identity_max_request_seconds": 0},
    {"website_identity_max_request_seconds": 901},
])
def test_identity_configuration_is_bounded(values):
    with pytest.raises(ValueError):
        Settings(_env_file=None, **values)
