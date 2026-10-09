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
