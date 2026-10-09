"""Customer identity, exclusive ownership and legacy-data compatibility."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi import HTTPException
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from backend.models import (
    Base, Conversation, FunnelEvent, Message, User, VisitorConsultation,
    VisitorTurn, WebsiteCustomer,
)
from backend.schemas import AskResponse
from backend.services import widget_history as history
from backend.services.consultation_service import load_owned
from backend.services.retention_service import purge_expired
from backend.domain.website_owner import VerifiedCustomerIdentity
from backend.services.website_identity import customer_owner


@pytest.fixture
def ownership_store():
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine, tables=[
        WebsiteCustomer.__table__, User.__table__, Conversation.__table__,
        Message.__table__, VisitorConsultation.__table__, VisitorTurn.__table__,
        FunnelEvent.__table__,
    ])
    yield sessionmaker(engine, autoflush=False)
    engine.dispose()


def test_customer_identity_is_provider_scoped_and_unique(ownership_store):
    with ownership_store() as session:
        session.add_all([
            WebsiteCustomer(provider="website-prod", external_user_id="101"),
            WebsiteCustomer(provider="website-test", external_user_id="101"),
        ])
        session.commit()
        with pytest.raises(IntegrityError):
            with session.begin_nested():
                session.add(WebsiteCustomer(provider="website-prod", external_user_id="101"))
                session.flush()
        assert len(list(session.scalars(select(WebsiteCustomer)))) == 2


def verified(external_id="101"):
    return VerifiedCustomerIdentity("website-prod", external_id,
                                    datetime.now(timezone.utc) + timedelta(hours=1))


def test_association_is_exclusive_idempotent_and_preserves_activity(ownership_store):
    with ownership_store() as session:
        key = history.create(session, "visitor-a", str(uuid4()))["id"]
        other = history.create(session, "visitor-a", str(uuid4()))["id"]
        request_id = str(uuid4())
        _, _, claim = history.begin_turn(session, key, "visitor-a", request_id, "robot")
        history.finish_turn(session, key, "visitor-a", request_id, "robot",
                            AskResponse(answer="saved", hit=True), claim)
        row = session.get(VisitorConsultation, key)
        activity, updated = row.last_activity_at, row.updated_at
        owner, result = history.associate_current(session, verified(), "visitor-a", key)
        assert result["id"] == key
        assert history.associate_current(session, verified(), "visitor-a", key)[1] == result
        assert len(list(session.scalars(select(WebsiteCustomer)))) == 1
        assert history.owned(session, key, owner).last_activity_at == activity
        assert row.updated_at == updated
        assert row.visitor_id is None and row.source_visitor_id == "visitor-a"
        assert history.owned(session, other, "visitor-a")
        assert session.scalar(select(VisitorTurn)).response_json is not None
        for intruder in ("visitor-a", "visitor-b", customer_owner(session, verified("102"))):
            for operation in (
                lambda: history.owned(session, key, intruder),
                lambda: history.rename(session, key, intruder, "stolen"),
                lambda: history.begin_turn(session, key, intruder, str(uuid4()), "robot"),
                lambda: history.finish_turn(session, key, intruder, request_id, "robot",
                                          AskResponse(answer="stolen", hit=True), claim),
            ):
                with pytest.raises(HTTPException) as exc:
                    operation()
                assert exc.value.status_code == 404
            history.remove(session, key, intruder)
        assert history.owned(session, key, owner).deleted_at is None
        assert [x.id for x in history.listing(session, owner, 0, 10)] == [key]
        request_id = str(uuid4())
        _, _, claim = history.begin_turn(session, key, owner, request_id, "next")
        history.finish_turn(session, key, owner, request_id, "next", AskResponse(answer="new", hit=True), claim)
        history.rename(session, key, owner, "mine")
        history.remove(session, key, owner)
        assert history.listing(session, owner, 0, 10) == []


@pytest.mark.parametrize("state", ["foreign", "expired", "deleted", "processing", "missing-cookie", "missing-id"])
def test_association_denials_do_not_create_customers_or_change_guest(ownership_store, state):
    with ownership_store() as session:
        key = history.create(session, "visitor-a", str(uuid4()))["id"]
        row = session.get(VisitorConsultation, key)
        if state == "expired":
            row.last_activity_at = history.cutoff() - timedelta(seconds=1)
        if state == "deleted":
            row.deleted_at = history.now()
        session.commit()
        if state == "processing":
            history.begin_turn(session, key, "visitor-a", str(uuid4()), "robot")
        guest = "visitor-b" if state == "foreign" else None if state == "missing-cookie" else "visitor-a"
        with pytest.raises(HTTPException) as exc:
            history.associate_current(session, verified(), guest, "missing" if state == "missing-id" else key)
        assert exc.value.status_code == (409 if state == "processing" else 404)
        assert list(session.scalars(select(WebsiteCustomer))) == []
        assert session.get(VisitorConsultation, key).visitor_id == "visitor-a"


def test_identity_only_and_stale_claim_transfer(ownership_store):
    with ownership_store() as session:
        owner, result = history.associate_current(session, verified(), None)
        assert result is None
        assert list(session.scalars(select(VisitorConsultation))) == []
        key = history.create(session, "visitor-a", str(uuid4()))["id"]
        request_id = str(uuid4())
        _, _, claim = history.begin_turn(session, key, "visitor-a", request_id, "robot")
        session.get(VisitorTurn, claim).created_at = history.now() - timedelta(minutes=16)
        session.commit()
        owner, _ = history.associate_current(session, verified(), "visitor-a", key)
        assert session.get(VisitorTurn, claim) is None
        with pytest.raises(HTTPException):
            history.finish_turn(session, key, "visitor-a", request_id, "robot",
                                AskResponse(answer="late", hit=True), claim)
        assert history.owned(session, key, owner).history_json == "[]"


def test_owner_ttl_and_expired_verification_fail_closed(ownership_store):
    from dataclasses import replace

    with ownership_store() as session:
        owner = customer_owner(session, verified())
        session.commit()
        key = history.create(session, owner, str(uuid4()))["id"]
        row = session.get(VisitorConsultation, key)
        row.last_activity_at = history.now() - timedelta(days=2)
        session.commit()
        activity = row.last_activity_at
        assert history.owned(session, key, owner)
        history.rename(session, key, owner, "old but active")
        assert row.last_activity_at == activity
        expired = replace(owner, valid_until=history.now() - timedelta(seconds=1))
        with pytest.raises(HTTPException) as exc:
            history.remove(session, key, expired)
        assert exc.value.status_code == 401
        assert row.deleted_at is None
        row.last_activity_at = history.now() - timedelta(days=91)
        session.commit()
        assert history.listing(session, owner, 0, 10) == []
        with pytest.raises(HTTPException) as exc:
            history.owned(session, key, owner)
        assert exc.value.status_code == 404


def test_stale_legacy_row_cannot_write_after_association(ownership_store):
    from backend.services.consultation_service import answer, complete_dialogue

    with ownership_store() as session:
        row = VisitorConsultation(visitor_id="visitor-a", course_id="43")
        session.add(row)
        session.commit()
        history.associate_current(session, verified(), "visitor-a", row.id)
        for operation in (
            lambda: answer(session, row, "goal", "robot", owner="visitor-a"),
            lambda: complete_dialogue(session, row, "robot", "late", owner="visitor-a"),
        ):
            with pytest.raises(ValueError):
                operation()
        session.refresh(row)
        assert row.profile_json == "{}" and row.history_json == "[]"


def test_association_rollback_restores_guest_even_after_flush(ownership_store, monkeypatch):
    with ownership_store() as session:
        key = history.create(session, "visitor-a", str(uuid4()))["id"]

        def failed_commit():
            session.flush()
            raise RuntimeError("commit failed")

        monkeypatch.setattr(session, "commit", failed_commit)
        with pytest.raises(RuntimeError, match="commit failed"):
            history.associate_current(session, verified(), "visitor-a", key)
        assert history.owned(session, key, "visitor-a").customer_id is None
        assert list(session.scalars(select(WebsiteCustomer))) == []


@pytest.mark.parametrize("provider,external_id", [("", "101"), ("   ", "101"), ("site", ""), ("site", "   ")])
def test_empty_customer_identity_is_rejected(ownership_store, provider, external_id):
    with ownership_store() as session, pytest.raises(IntegrityError):
        session.add(WebsiteCustomer(provider=provider, external_user_id=external_id))
        session.commit()


@pytest.mark.parametrize("visitor,customer", [(None, None), ("visitor-a", "customer"), (None, "missing")])
def test_invalid_consultation_owners_are_rejected(ownership_store, visitor, customer):
    with ownership_store() as session:
        session.add(WebsiteCustomer(id="customer", provider="site", external_user_id="101"))
        session.commit()
        with pytest.raises(IntegrityError):
            session.add(VisitorConsultation(visitor_id=visitor, customer_id=customer))
            session.commit()


def test_customer_consultation_never_uses_source_visitor_for_access(ownership_store):
    with ownership_store() as session:
        customer = WebsiteCustomer(provider="site", external_user_id="101")
        session.add(customer)
        session.commit()
        key = history.create(session, "visitor-a", str(uuid4()))["id"]
        request_id = str(uuid4())
        _, _, claim = history.begin_turn(session, key, "visitor-a", request_id, "robot")
        history.finish_turn(session, key, "visitor-a", request_id, "robot",
                            AskResponse(answer="answer", hit=True), claim)
        row = session.get(VisitorConsultation, key)
        activity = row.last_activity_at
        row.source_visitor_id, row.visitor_id, row.customer_id = "visitor-a", None, customer.id
        session.commit()
        assert row.last_activity_at == activity
        assert load_owned(session, key, "visitor-a") is None
        assert load_owned(session, key, None) is None
        with pytest.raises(HTTPException) as exc:
            history.owned(session, key, "visitor-a")
        assert exc.value.status_code == 404
        assert session.scalar(select(VisitorTurn)).response_json is not None
        with pytest.raises(IntegrityError):
            session.delete(customer)
            session.commit()


def test_cleanup_applies_owner_retention_and_preserves_customer_identity(ownership_store, monkeypatch):
    from backend.config import settings

    monkeypatch.setattr(settings, "visitor_consultation_hours", 24)
    monkeypatch.setattr(settings, "customer_consultation_days", 90)
    now = datetime.now(timezone.utc)
    with ownership_store() as session:
        customer = WebsiteCustomer(provider="site", external_user_id="101")
        session.add(customer)
        session.flush()
        for key, guest, days, deleted in [
            ("guest-expired", True, 2, False),
            ("guest-current", True, 0, False),
            ("customer-current", False, 2, False),
            ("customer-expired", False, 91, False),
            ("customer-deleted", False, 0, True),
        ]:
            row = VisitorConsultation(
                id=key, visitor_id="visitor" if guest else None,
                customer_id=None if guest else customer.id,
                last_activity_at=now - timedelta(days=days),
                deleted_at=now if deleted else None,
            )
            session.add(row)
            session.flush()
            session.add(VisitorTurn(conversation_id=key, request_id=str(uuid4()), question="robot"))
        session.commit()
        result = purge_expired(session, retention_days=0, now=now)
        session.commit()
        assert result.consultations == 3
        assert set(session.scalars(select(VisitorConsultation.id))) == {"guest-current", "customer-current"}
        assert len(list(session.scalars(select(VisitorTurn)))) == 2
        assert session.get(WebsiteCustomer, customer.id) is not None


def test_0003_migration_preserves_guest_messages_and_safe_downgrade(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "customer-migration.db"))
    config = Config("alembic.ini")
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "0002")
        connection.execute(text(
            "INSERT INTO visitor_consultations "
            "(id, visitor_id, profile_json, history_json, status, widget_session, last_activity_at) "
            "VALUES ('legacy', 'visitor-a', '{}', '[]', 'collecting', true, '2026-10-01 12:00:00')"
        ))
        connection.execute(text(
            "INSERT INTO visitor_turns (id, conversation_id, request_id, question, response_json) "
            "VALUES ('turn', 'legacy', 'request', 'robot', '{\"answer\":\"saved\"}')"
        ))
        command.upgrade(config, "head")
        row = connection.execute(text(
            "SELECT visitor_id, customer_id, source_visitor_id, last_activity_at "
            "FROM visitor_consultations WHERE id = 'legacy'"
        )).one()
        assert tuple(row[:3]) == ("visitor-a", None, "visitor-a")
        assert str(row.last_activity_at).startswith("2026-10-01 12:00:00")
        assert connection.scalar(text("SELECT response_json FROM visitor_turns WHERE id='turn'")) == '{"answer":"saved"}'
        command.downgrade(config, "0002")
        assert connection.scalar(text("SELECT visitor_id FROM visitor_consultations WHERE id='legacy'")) == "visitor-a"
        command.upgrade(config, "head")
        connection.execute(text(
            "INSERT INTO website_customers (id, provider, external_user_id) VALUES ('customer', 'site', '101')"
        ))
        with pytest.raises(RuntimeError, match="Cannot downgrade"):
            command.downgrade(config, "0002")
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0003"
        assert connection.scalar(text("SELECT external_user_id FROM website_customers")) == "101"
    engine.dispose()
