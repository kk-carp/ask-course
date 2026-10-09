from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend import db
from backend.db import get_session
from backend.main import app
from backend.models import FunnelEvent, PilotControl, VisitorConsultation, VisitorTurn, WebsiteCustomer
from backend.schemas import AskRequest, AskResponse
from backend.services import widget_history as history
from backend.services.course_scope import course_scope
from backend.domain.website_owner import VerifiedCustomerIdentity
from backend.services.website_identity import verified_website_identity


@pytest.fixture
def store(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    for table in (
        WebsiteCustomer.__table__,
        VisitorConsultation.__table__,
        VisitorTurn.__table__,
        PilotControl.__table__,
        FunnelEvent.__table__,
    ):
        table.create(engine)
    factory = sessionmaker(engine)
    monkeypatch.setattr(db, "SessionLocal", factory)
    monkeypatch.setattr(db, "init_engine", lambda: engine)

    def dependency():
        with factory() as session:
            yield session

    app.dependency_overrides[get_session] = dependency
    monkeypatch.setattr("backend.routes.widget_history.site_eligible", lambda *_: True)
    monkeypatch.setattr("backend.routes.consultations.site_eligible", lambda *_: True)
    monkeypatch.setattr(
        "backend.routes.consultations.site_course_ids", lambda *_: frozenset({"43"})
    )
    monkeypatch.setattr("backend.routes.ask.site_eligible", lambda *_: True)
    monkeypatch.setattr(
        "backend.routes.ask.site_course_ids", lambda *_: frozenset({"43"})
    )
    monkeypatch.setattr("backend.routes.widget_history._limit", lambda *_: None)
    monkeypatch.setattr("backend.routes.ask._allow_guest_ask", lambda *_: True)
    yield factory
    app.dependency_overrides.pop(get_session, None)
    engine.dispose()


def start(client, request_id=None):
    response = client.post(
        "/widget/conversations", json={"request_id": request_id or str(uuid4())}
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def test_config_identity_partition_is_server_owned_stable_and_not_authorization(store):
    guest, other = TestClient(app), TestClient(app)
    path = "/widget/config?mode=site"
    first = guest.get(path)
    assert first.headers["cache-control"] == "no-store"
    guest_key = first.json()["identity_key"]
    assert first.json()["identity_kind"] == "guest"
    assert guest.get(path).json()["identity_key"] == guest_key
    assert other.get(path).json()["identity_key"] != guest_key
    identity = VerifiedCustomerIdentity("website-prod", "101", history.now() + timedelta(hours=1))
    app.dependency_overrides[verified_website_identity] = lambda: identity
    try:
        customer = guest.get(path).json()
        assert customer["identity_kind"] == "customer"
        assert len(customer["identity_key"]) == 64
        assert customer["identity_key"] != guest_key
        assert other.get(path).json()["identity_key"] == customer["identity_key"]
        assert not {"external_user_id", "customer_id", "token", "valid_until"} & customer.keys()
        app.dependency_overrides[verified_website_identity] = lambda: None
        assert guest.get(path).json()["identity_key"] == guest_key
        # Even the genuine partition reference supplied by a browser grants no access.
        assert other.get(path + "&identity_key=" + customer["identity_key"]).json()["identity_kind"] == "guest"
    finally:
        app.dependency_overrides.pop(verified_website_identity, None)


def test_history_ownership_rename_ttl_delete_and_late_result(store):
    client, other = TestClient(app), TestClient(app)
    creation_key = str(uuid4())
    key = start(client, creation_key)
    assert start(client, creation_key) == key
    other.get("/widget/config?mode=site")
    assert other.get(f"/widget/conversations/{key}/messages").status_code == 404
    assert (
        other.patch(f"/widget/conversations/{key}", json={"title": "冒用"}).status_code
        == 404
    )
    request_id = str(uuid4())
    with store() as session:
        row = session.get(VisitorConsultation, key)
        visitor = row.visitor_id
        assert history.begin_turn(
            session, key, visitor, request_id, "四足机器人需要什么硬件？"
        )[:2] == (None, True)
        answer = AskResponse(answer="需要确认设备", hit=False, conversation_id=key)
        history.finish_turn(
            session, key, visitor, request_id, "四足机器人需要什么硬件？", answer
        )
        activity = session.get(VisitorConsultation, key).last_activity_at
    assert (
        client.patch(
            f"/widget/conversations/{key}", json={"title": "我的学习计划"}
        ).status_code
        == 200
    )
    with store() as session:
        assert session.get(VisitorConsultation, key).last_activity_at == activity
    data = client.get(f"/widget/conversations/{key}/messages?limit=1").json()
    assert data["items"][0]["result"]["answer"] == "需要确认设备"
    assert data["conversation"]["title"] == "我的学习计划"
    assert client.delete(f"/widget/conversations/{key}").status_code == 204
    assert client.delete(f"/widget/conversations/{key}").status_code == 204
    assert client.get("/widget/conversations").json()["items"] == []
    assert client.get(f"/widget/conversations/{key}/messages").status_code == 404
    with store() as session, pytest.raises(HTTPException) as exc:
        history.finish_turn(session, key, visitor, request_id, "迟到的提问", answer)
    assert exc.value.status_code == 404


def test_customer_http_access_and_association_require_verified_identity(store, monkeypatch):
    from backend.config import settings
    from backend.services.ask_orchestrator import _bind_selected_course

    guest, device = TestClient(app), TestClient(app)
    key, untouched = start(guest), start(guest)
    path = f"/widget/conversations/{key}"
    assert guest.post(path + "/associate", json={"customer_id": "forged"}).status_code == 401
    assert guest.get("/widget/conversations", headers={"Authorization": "Bearer unverified"}).status_code == 503
    identity = VerifiedCustomerIdentity("website-prod", "101", history.now() + timedelta(hours=1))
    app.dependency_overrides[verified_website_identity] = lambda: identity
    try:
        # A valid customer identity alone cannot claim an arbitrary guest conversation.
        assert device.post(path + "/associate").status_code == 404
        bad_cookie = TestClient(app)
        bad_cookie.cookies.set(settings.visitor_cookie_name, "forged")
        assert bad_cookie.post(path + "/associate").status_code == 404
        linked = guest.post(path + "/associate")
        assert linked.status_code == 200, linked.text
        assert guest.post(path + "/associate").json() == linked.json()
        assert [r["id"] for r in device.get("/widget/conversations").json()["items"]] == [key]
        assert device.get(path + "/messages").status_code == 200
        assert device.patch(path, json={"title": "customer title"}).status_code == 200
        payload = {"question": "推荐一门适合我的课程", "channel": "site_widget",
                   "conversation_id": key, "request_id": str(uuid4())}
        response = device.post("/ask", json=payload)
        assert response.status_code == 200, response.text
        assert device.post("/ask", json={**payload, "channel": None}).status_code == 400
        assert response.json()["conversation_id"] == key
        assert len(device.get(path + "/messages").json()["items"]) == 1
        # Real customer orchestration, not a mock, persisted the turn and profile.
        with store() as session:
            row = session.get(VisitorConsultation, key)
            assert row.customer_id and row.visitor_id is None
            assert row.profile_json != "{}"
        monkeypatch.setattr("backend.routes.widget_history.site_eligible", lambda *_: False)
        assert device.get("/widget/conversations").status_code == 404
        monkeypatch.setattr("backend.routes.widget_history.site_eligible", lambda *_: True)
        monkeypatch.setattr("backend.routes.ask.site_eligible", lambda *_: False)
        assert device.post("/ask", json=payload).status_code == 404
        monkeypatch.setattr("backend.routes.ask.site_eligible", lambda *_: True)
        # Logging out removes verified identity; the still-valid original guest cookie cannot read back.
        app.dependency_overrides[verified_website_identity] = lambda: None
        assert guest.get(path + "/messages").status_code == 404
        assert guest.patch(path, json={"title": "guest"}).status_code == 404
        assert guest.delete(path).status_code == 204
        assert guest.post("/ask", json=payload).status_code == 404
        assert [r["id"] for r in guest.get("/widget/conversations").json()["items"]] == [untouched]
        with store() as session:
            source = session.get(VisitorConsultation, key).source_visitor_id
        with pytest.raises(HTTPException):
            _bind_selected_course(source, key, "43")
        # A different validated account also cannot take or modify the conversation.
        other_identity = VerifiedCustomerIdentity("website-prod", "102", identity.valid_until)
        app.dependency_overrides[verified_website_identity] = lambda: other_identity
        assert guest.post(path + "/associate").status_code == 404
        assert device.get(path + "/messages").status_code == 404
        assert device.patch(path, json={"title": "other"}).status_code == 404
        assert device.post("/ask", json=payload).status_code == 404
        assert device.get("/widget/conversations").json()["items"] == []
        assert device.delete(path).status_code == 204
        app.dependency_overrides[verified_website_identity] = lambda: identity
        assert device.get(path + "/messages").status_code == 200
        # Verification expiry denies instead of falling back to the cookie.
        invalid = VerifiedCustomerIdentity("website-prod", "101", history.now() - timedelta(seconds=1))
        app.dependency_overrides[verified_website_identity] = lambda: invalid
        assert guest.get("/widget/conversations").status_code == 401
        assert guest.post("/ask", json=payload).status_code == 401
        assert guest.cookies.get(settings.visitor_cookie_name)
    finally:
        app.dependency_overrides.pop(verified_website_identity, None)


def test_legacy_consultations_share_customer_authorization(store, monkeypatch):
    monkeypatch.setattr("backend.routes.consultations.eligible", lambda *_: True)
    monkeypatch.setattr("backend.routes.ask.eligible", lambda *_: True)
    identity = VerifiedCustomerIdentity("website-prod", "101", history.now() + timedelta(hours=1))
    app.dependency_overrides[verified_website_identity] = lambda: identity
    customer, device = TestClient(app), TestClient(app)
    try:
        result = customer.post("/consultations", json={"course_id": "43"})
        assert result.status_code == 200, result.text
        key = result.json()["id"]
        assert device.get(f"/consultations/{key}").status_code == 200
        assert device.post(f"/consultations/{key}/answers", json={"field": "basis", "value": "basic"}).status_code == 200
        assert customer.get("/widget/config?mode=site").json()["history_hours"] == 90 * 24
        payload = {"question": "推荐一门适合我的课程", "course_id": "43",
                   "channel": "course_page", "conversation_id": key}
        result = device.post("/ask", json=payload)
        assert result.status_code == 200, result.text
        assert result.json()["conversation_id"] == key
        app.dependency_overrides[verified_website_identity] = lambda: None
        assert customer.get(f"/consultations/{key}").status_code == 404
        assert customer.post(f"/consultations/{key}/answers", json={"field": "basis", "value": "none"}).status_code == 404
        assert customer.post("/ask", json=payload).status_code == 404
    finally:
        app.dependency_overrides.pop(verified_website_identity, None)


def test_customer_verification_expiring_during_stream_cannot_save_final(store, monkeypatch):
    clock = [history.now()]
    monkeypatch.setattr("backend.domain.website_owner.utcnow", lambda: clock[0])
    identity = VerifiedCustomerIdentity("website-prod", "101", clock[0] + timedelta(minutes=1))
    app.dependency_overrides[verified_website_identity] = lambda: identity

    def answer(payload, _identity):
        clock[0] += timedelta(minutes=2)
        yield "final", AskResponse(answer="expired answer", hit=True, conversation_id=payload.conversation_id)

    monkeypatch.setattr("backend.routes.ask.iter_ask_turn", answer)
    try:
        client = TestClient(app)
        key = start(client)
        response = client.post("/ask/stream", json={
            "question": "hello", "channel": "site_widget", "conversation_id": key,
            "request_id": str(uuid4()),
        })
        assert '"status": 401' in response.text
        assert "event: final" not in response.text
        with store() as session:
            assert session.scalar(select(VisitorTurn)).response_json is None
            assert session.get(VisitorConsultation, key).history_json == "[]"
    finally:
        app.dependency_overrides.pop(verified_website_identity, None)


def mock_me(monkeypatch):
    import httpx
    from backend.config import settings
    from backend.infra import website_identity_client

    state = {"status": 200, "calls": 0}

    def upstream(request):
        assert request.headers["token"] == request.headers["authorization"].split(" ", 1)[1]
        assert not request.content and "cookie" not in request.headers
        state["calls"] += 1
        key = 101 if request.headers["token"] == "synthetic-A" else 102
        return httpx.Response(state["status"], json={"success": True, "data": {"id": key, "role": "admin"}})

    monkeypatch.setattr(website_identity_client, "Client", lambda **options: httpx.Client(
        transport=httpx.MockTransport(upstream), **options,
    ))
    monkeypatch.setattr(settings, "website_identity_enabled", True)
    return state


def test_me_adapter_http_identity_association_and_upstream_failure_do_not_fall_back(store, monkeypatch):
    state = mock_me(monkeypatch)
    guest, device = TestClient(app), TestClient(app)
    key = start(guest)
    path = f"/widget/conversations/{key}"
    auth_a, auth_b = {"Authorization": "Bearer synthetic-A"}, {"Authorization": "Bearer synthetic-B"}
    assert guest.post(path + "/associate", headers=auth_a).status_code == 200
    assert device.get(path + "/messages", headers=auth_a).status_code == 200
    assert device.get(path + "/messages", headers=auth_b).status_code == 404
    assert guest.get(path + "/messages").status_code == 404
    with store() as session:
        row = session.get(VisitorConsultation, key)
        customer = session.get(WebsiteCustomer, row.customer_id)
        assert customer.external_user_id == "101" and row.visitor_id is None
    state["status"] = 401
    for method, url, payload in [
        ("GET", "/widget/config?mode=site", None), ("GET", "/widget/conversations", None),
        ("GET", path + "/messages", None), ("PATCH", path, {"title": "revoked"}),
        ("DELETE", path, None), ("POST", path + "/associate", None),
        ("POST", "/ask", {"question": "你好", "channel": "site_widget", "conversation_id": key, "request_id": str(uuid4())}),
    ]:
        assert guest.request(method, url, headers=auth_a, json=payload).status_code == 401
    state["status"] = 503
    assert guest.get("/widget/conversations", headers=auth_a).status_code == 503
    assert guest.get(path + "/messages").status_code == 404


@pytest.mark.parametrize("upstream_status", [401, 503])
def test_me_recheck_blocks_inflight_final_and_cleans_only_its_pending_claim(store, monkeypatch, upstream_status):
    state = mock_me(monkeypatch)
    client = TestClient(app)
    headers = {"Authorization": "Bearer synthetic-A"}
    key = client.post("/widget/conversations", headers=headers, json={"request_id": str(uuid4())}).json()["id"]

    def answer(payload, _identity):
        state["status"] = upstream_status
        yield "final", AskResponse(answer="must not persist", hit=True, conversation_id=payload.conversation_id)

    monkeypatch.setattr("backend.routes.ask.iter_ask_turn", answer)
    response = client.post("/ask/stream", headers=headers, json={
        "question": "你好", "channel": "site_widget", "conversation_id": key, "request_id": str(uuid4()),
    })
    assert f'"status": {upstream_status}' in response.text
    assert "event: final" not in response.text and "must not persist" not in response.text
    with store() as session:
        assert session.scalar(select(VisitorTurn)) is None
        assert session.get(VisitorConsultation, key).history_json == "[]"
    state["status"] = 200
    assert client.get(f"/widget/conversations/{key}/messages", headers=headers).status_code == 200


def test_me_recheck_blocks_late_partial_answer(store, monkeypatch):
    state = mock_me(monkeypatch)
    client = TestClient(app)
    headers = {"Authorization": "Bearer synthetic-A"}
    key = client.post("/widget/conversations", headers=headers, json={"request_id": str(uuid4())}).json()["id"]

    def questions(*_args):
        state["status"] = 401
        yield "part", {"index": 1, "question": "private", "answer": "must not output"}

    monkeypatch.setattr("backend.services.ask_orchestrator._run_questions", questions)
    response = client.post("/ask/stream", headers=headers, json={
        "question": "你好", "channel": "site_widget", "conversation_id": key, "request_id": str(uuid4()),
    })
    assert '"status": 401' in response.text
    assert "event: part" not in response.text and "must not output" not in response.text
    with store() as session:
        assert session.scalar(select(VisitorTurn)) is None


def test_turn_idempotency_conflict_retry_and_expiration(store):
    with store() as session:
        key = history.create(session, "visitor-a", str(uuid4()))["id"]
        request_id = str(uuid4())
        history.begin_turn(session, key, "visitor-a", request_id, "课程目录")
        with pytest.raises(HTTPException) as exc:
            history.begin_turn(session, key, "visitor-a", request_id, "课程目录")
        assert exc.value.status_code == 409
        history.abandon_turn(session, key, "visitor-a", request_id)
        assert history.begin_turn(session, key, "visitor-a", request_id, "课程目录")[
            :2
        ] == (None, True)
        response = AskResponse(answer="目录回答", hit=True, conversation_id=key)
        history.finish_turn(session, key, "visitor-a", request_id, "课程目录", response)
        cached, first, _ = history.begin_turn(
            session, key, "visitor-a", request_id, "课程目录"
        )
        assert cached.answer == "目录回答" and not first
        assert len(list(session.scalars(select(VisitorTurn)))) == 1
        with pytest.raises(HTTPException):
            history.begin_turn(session, key, "visitor-a", request_id, "换一个问题")
        row = session.get(VisitorConsultation, key)
        row.last_activity_at = history.cutoff() - timedelta(seconds=1)
        session.commit()
        with pytest.raises(HTTPException) as exc:
            history.owned(session, key, "visitor-a")
        assert exc.value.status_code == 404


def test_site_stream_is_guest_even_when_internal_auth_is_present(store, monkeypatch):
    identities = []

    def forbidden(_):
        pytest.fail("官网不应读取内部登录身份")

    monkeypatch.setattr("backend.routes.ask.load_auth_context", forbidden)

    def answer(payload, identity):
        identities.append(identity)
        yield (
            "final",
            AskResponse(
                answer="安全回答", hit=False, conversation_id=payload.conversation_id
            ),
        )

    monkeypatch.setattr("backend.routes.ask.iter_ask_turn", answer)
    client = TestClient(app)
    key = start(client)
    payload = {
        "question": "你好",
        "course_id": "999",
        "channel": "site_widget",
        "conversation_id": key,
        "request_id": str(uuid4()),
    }
    for _ in range(2):
        response = client.post("/ask/stream", json=payload)
        assert response.status_code == 200 and "安全回答" in response.text
    assert (
        len(identities) == 1
    )  # Replay cached final without a second model invocation.
    assert identities[0].user_id is None and identities[0].course_ids == frozenset(
        {"43"}
    )
    assert identities[0].first_turn is True
    assert (
        client.get(f"/widget/conversations/{key}/messages").json()["items"][0][
            "question"
        ]
        == "你好"
    )


def test_scope_blocks_fact_and_unbound_retrieval_before_io(monkeypatch):
    from backend.services.course_facts import answer_course_fact
    from backend.services.qa_service import _retrieve

    monkeypatch.setattr(
        "backend.services.course_facts.live_course",
        lambda *_: pytest.fail("越界查询官网"),
    )
    monkeypatch.setattr(
        "backend.services.qa_service.encode_query",
        lambda *_: pytest.fail("越界进入检索"),
    )
    token = course_scope.set(frozenset({"43"}))
    try:
        assert answer_course_fact("多少钱", "999") is None
        assert _retrieve(["courses"], "资料", course_id=None) == []
        assert _retrieve(["courses"], "资料", course_id="999") == []
    finally:
        course_scope.reset(token)


def test_scoped_generator_can_resume_in_different_thread_contexts(monkeypatch):
    from contextvars import Context

    from backend.services.ask_orchestrator import AskIdentity, iter_ask_turn

    def inner(*_):
        assert course_scope.get() == frozenset({"43"})
        yield "part", {}
        assert course_scope.get() == frozenset({"43"})
        yield "final", AskResponse(answer="完成", hit=False)

    monkeypatch.setattr("backend.services.ask_orchestrator._iter_ask_turn", inner)
    generator = iter_ask_turn(
        AskRequest(question="你好"),
        AskIdentity(["courses"], None, "guest", "visitor", frozenset({"43"})),
    )
    assert Context().run(next, generator)[0] == "part"
    assert Context().run(next, generator)[0] == "final"
    with pytest.raises(StopIteration):
        Context().run(next, generator)
    assert course_scope.get() is None


def test_alembic_adopts_legacy_data_and_can_revert_widget_schema(tmp_path):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import inspect

    engine = create_engine("sqlite:///" + str(tmp_path / "migration.db"))
    config = Config("alembic.ini")
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "0001")
        connection.exec_driver_sql(
            "INSERT INTO visitor_consultations (id, visitor_id, profile_json, history_json, status) VALUES ('old', 'visitor', '{}', '[]', 'collecting')"
        )
        command.upgrade(config, "head")
        assert (
            connection.exec_driver_sql(
                "SELECT title FROM visitor_consultations WHERE id='old'"
            ).scalar()
            == "新咨询"
        )
        assert "visitor_turns" in inspect(connection).get_table_names()
        command.downgrade(config, "0001")
        assert (
            connection.exec_driver_sql(
                "SELECT visitor_id FROM visitor_consultations WHERE id='old'"
            ).scalar()
            == "visitor"
        )
        command.upgrade(config, "head")
    engine.dispose()


def test_expired_claim_cannot_replace_the_retried_answer(store):
    with store() as session:
        key = history.create(session, "visitor", str(uuid4()))["id"]
        request = str(uuid4())
        _, _, old_claim = history.begin_turn(
            session, key, "visitor", request, "课程内容"
        )
        record = session.get(VisitorTurn, old_claim)
        record.created_at = history.now() - timedelta(minutes=16)
        session.commit()
        _, _, new_claim = history.begin_turn(
            session, key, "visitor", request, "课程内容"
        )
        assert old_claim != new_claim
        with pytest.raises(HTTPException) as exc:
            history.finish_turn(
                session,
                key,
                "visitor",
                request,
                "课程内容",
                AskResponse(answer="旧回答", hit=True),
                old_claim,
            )
        assert exc.value.status_code == 409
        history.abandon_turn(session, key, "visitor", request, old_claim)
        history.finish_turn(
            session,
            key,
            "visitor",
            request,
            "课程内容",
            AskResponse(answer="新回答", hit=True),
            new_claim,
        )
        cached, _, _ = history.begin_turn(session, key, "visitor", request, "课程内容")
        assert cached.answer == "新回答"


def test_cleanup_physically_removes_deleted_and_expired_messages(store):
    from backend.services.retention_service import purge_expired

    with store() as session:
        for visitor in ("deleted", "expired", "retained"):
            key = history.create(session, visitor, str(uuid4()))["id"]
            request = str(uuid4())
            history.begin_turn(session, key, visitor, request, "课程内容")
            history.finish_turn(
                session,
                key,
                visitor,
                request,
                "课程内容",
                AskResponse(answer="内容", hit=True),
            )
            row = session.get(VisitorConsultation, key)
            if visitor == "deleted":
                row.deleted_at = history.now()
            if visitor == "expired":
                row.last_activity_at = history.cutoff() - timedelta(seconds=1)
            session.commit()
        result = purge_expired(session, retention_days=0)
        session.commit()
        assert result.consultations == 2
        assert len(list(session.scalars(select(VisitorTurn)))) == 1


def test_explicit_new_session_is_not_replaced_by_default_recommendation(store):
    from backend.services.ask_orchestrator import _prepare_guest_dialogue
    from backend.services.intent_router import Intent

    with store() as session:
        key = history.create(session, "visitor", str(uuid4()))["id"]
    result = _prepare_guest_dialogue(
        "visitor",
        AskRequest(question="推荐适合我的课程", conversation_id=key),
        intent=Intent.recommend,
    )
    assert result[0] == key
    with store() as session:
        assert len(list(session.scalars(select(VisitorConsultation)))) == 1


def test_site_gate_requires_qualified_course_and_can_be_closed(monkeypatch):
    from backend.services.pilot_service import site_eligible

    monkeypatch.setattr(
        "backend.services.pilot_service.settings.pilot_course_ids", "43,999"
    )
    monkeypatch.setattr("backend.services.pilot_service.pilot_percent", lambda _: 100)
    monkeypatch.setattr(
        "backend.services.pilot_service.get_approved_course",
        lambda key: object() if key == "43" else None,
    )
    monkeypatch.setattr("backend.services.pilot_service.course_ready", lambda *_: True)
    assert site_eligible("visitor", None)
    assert not site_eligible("", None)
    monkeypatch.setattr("backend.services.pilot_service.pilot_percent", lambda _: 0)
    assert not site_eligible("visitor", None)
    monkeypatch.setattr("backend.services.pilot_service.pilot_percent", lambda _: 100)
    monkeypatch.setattr("backend.services.pilot_service.course_ready", lambda *_: False)
    assert not site_eligible("visitor", None)
