"""Enforce customer ownership in real PostgreSQL."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from alembic import command
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError

from backend.models import VisitorConsultation, WebsiteCustomer


def test_postgres_customer_constraints_and_protected_deletion(postgres_store):
    factory, engine, _ = postgres_store
    with factory() as session:
        session.add(WebsiteCustomer(id="customer", provider="site", external_user_id="101"))
        session.commit()
        for kwargs in [
            {"visitor_id": None},
            {"visitor_id": "visitor", "customer_id": "customer"},
            {"visitor_id": None, "customer_id": "missing"},
        ]:
            with pytest.raises(IntegrityError), session.begin_nested():
                session.add(VisitorConsultation(**kwargs))
                session.flush()
        session.add(VisitorConsultation(visitor_id=None, customer_id="customer"))
        session.commit()
        with pytest.raises(IntegrityError), session.begin_nested():
            session.delete(session.get(WebsiteCustomer, "customer"))
            session.flush()
        assert len(list(session.scalars(select(VisitorConsultation)))) == 1
    assert "ix_consultations_customer_activity" in {
        index["name"] for index in inspect(engine).get_indexes("visitor_consultations")
    }


def test_postgres_concurrent_identity_insert_cannot_duplicate_customer(postgres_store):
    factory, _, _ = postgres_store
    barrier = Barrier(2)

    def insert():
        with factory() as session:
            barrier.wait(timeout=5)
            session.add(WebsiteCustomer(provider="site", external_user_id="101"))
            try:
                session.commit()
                return "created"
            except IntegrityError:
                session.rollback()
                return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(insert) for _ in range(2)]
        assert sorted(future.result(timeout=10) for future in futures) == ["conflict", "created"]
    with factory() as session:
        assert len(list(session.scalars(select(WebsiteCustomer)))) == 1


def test_postgres_0003_upgrades_guest_history_and_refuses_customer_data_loss(postgres_store):
    _, engine, config = postgres_store
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, "0002")
        connection.execute(text(
            "INSERT INTO visitor_consultations "
            "(id, visitor_id, profile_json, history_json, status, widget_session, last_activity_at) "
            "VALUES ('legacy', 'visitor-a', '{}', '[]', 'collecting', true, '2026-10-01 12:00:00+00')"
        ))
        connection.execute(text(
            "INSERT INTO visitor_turns (id, conversation_id, request_id, question, response_json) "
            "VALUES ('turn', 'legacy', 'request', 'robot', '{\"answer\":\"saved\"}')"
        ))
        command.upgrade(config, "head")
        row = connection.execute(text(
            "SELECT visitor_id, customer_id, source_visitor_id, last_activity_at "
            "FROM visitor_consultations WHERE id='legacy'"
        )).one()
        assert tuple(row[:3]) == ("visitor-a", None, "visitor-a")
        assert row.last_activity_at.isoformat().startswith("2026-10-01T12:00:00")
        assert connection.scalar(text("SELECT response_json FROM visitor_turns WHERE id='turn'")) == '{"answer":"saved"}'
        connection.execute(text(
            "INSERT INTO website_customers (id, provider, external_user_id) VALUES ('customer', 'site', '101')"
        ))
        connection.execute(text(
            "UPDATE visitor_consultations SET visitor_id=NULL, customer_id='customer' WHERE id='legacy'"
        ))
        with pytest.raises(RuntimeError, match="Cannot downgrade"):
            command.downgrade(config, "0002")
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0003"
        assert connection.scalar(text("SELECT customer_id FROM visitor_consultations WHERE id='legacy'")) == "customer"
