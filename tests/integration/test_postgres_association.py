"""Real row locks decide association, turn claims and stale guest writes."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from dataclasses import replace
from threading import Barrier, Event
from uuid import uuid4
import time

from fastapi import HTTPException
import pytest
from sqlalchemy import select, text

from backend.domain.website_owner import VerifiedCustomerIdentity
from backend.models import VisitorConsultation, VisitorTurn, WebsiteCustomer
from backend.schemas import AskResponse
from backend.services import widget_history as history
from backend.services.consultation_service import complete_dialogue


def identity(key="101"):
    return VerifiedCustomerIdentity("website-prod", key, history.now() + timedelta(hours=1))


def test_upstream_rejection_while_waiting_for_row_lock_denies_write(postgres_store):
    factory, engine, _ = postgres_store
    with factory() as session:
        key = history.create(session, "visitor-a", str(uuid4()))["id"]
        owner, _ = history.associate_current(session, identity(), "visitor-a", key)
    revoked, started = Event(), Event()
    worker_pid = []

    def check_upstream():
        if revoked.is_set():
            raise HTTPException(401, "synthetic upstream rejection")

    checked_owner = replace(owner, revalidate=check_upstream)

    def write():
        with factory() as session:
            worker_pid.append(session.scalar(text("SELECT pg_backend_pid()")))
            started.set()
            try:
                history.rename(session, key, checked_owner, "must not persist")
            except HTTPException as exc:
                return exc.status_code
            return 200

    with factory() as session, ThreadPoolExecutor(max_workers=1) as pool:
        history.owned(session, key, owner, lock=True)
        future = pool.submit(write)
        try:
            assert started.wait(timeout=5)
            deadline = time.monotonic() + 5
            blocked = False
            while time.monotonic() < deadline:
                with engine.connect() as observer:
                    blocked = bool(observer.scalar(text(
                        "SELECT cardinality(pg_blocking_pids(:pid)) > 0"
                    ), {"pid": worker_pid[0]}))
                if blocked:
                    break
                time.sleep(0.01)
            assert blocked, "Write did not wait for the authorization row lock"
            revoked.set()
        finally:
            session.rollback()
        assert future.result(timeout=10) == 401
    with factory() as session:
        row = history.owned(session, key, owner)
        assert row.title != "must not persist" and row.deleted_at is None


@pytest.mark.parametrize("same_account", [True, False])
def test_concurrent_association_is_idempotent_or_exclusive(postgres_store, same_account):
    factory, _, _ = postgres_store
    with factory() as session:
        key = history.create(session, "visitor-a", str(uuid4()))["id"]
        activity = session.get(VisitorConsultation, key).last_activity_at
    barrier = Barrier(2)

    def associate(account):
        with factory() as session:
            barrier.wait(timeout=5)
            try:
                owner, result = history.associate_current(session, identity(account), "visitor-a", key)
                return 200, owner.customer_id, result["id"]
            except HTTPException as exc:
                return exc.status_code, None, None

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(associate, account) for account in ("101", "101" if same_account else "102")]
        results = [f.result(timeout=10) for f in futures]
    assert sorted(r[0] for r in results) == ([200, 200] if same_account else [200, 404])
    if same_account:
        assert results[0] == results[1]
    with factory() as session:
        row = session.get(VisitorConsultation, key)
        assert row.customer_id and row.visitor_id is None
        assert row.last_activity_at == activity
        assert len(list(session.scalars(select(WebsiteCustomer)))) == 1
        assert history.listing(session, "visitor-a", 0, 10) == []


def test_association_and_turn_claim_cannot_both_succeed(postgres_store):
    factory, _, _ = postgres_store
    with factory() as session:
        key = history.create(session, "visitor-a", str(uuid4()))["id"]
    barrier = Barrier(2)

    def execute(associate):
        with factory() as session:
            barrier.wait(timeout=5)
            try:
                if associate:
                    history.associate_current(session, identity(), "visitor-a", key)
                else:
                    history.begin_turn(session, key, "visitor-a", str(uuid4()), "robot")
                return 200
            except HTTPException as exc:
                return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        association, claim = (pool.submit(execute, True), pool.submit(execute, False))
        result = association.result(timeout=10), claim.result(timeout=10)
    assert result in {(200, 404), (409, 200)}
    with factory() as session:
        row = session.get(VisitorConsultation, key)
        turns = list(session.scalars(select(VisitorTurn)))
        assert (row.customer_id is not None) == (result[0] == 200)
        assert len(turns) == (0 if result[0] == 200 else 1)


@pytest.mark.parametrize("operation", ["rename", "delete", "finish", "legacy-finish"])
def test_association_revokes_writes_even_with_a_stale_identity_map(postgres_store, operation):
    factory, engine, _ = postgres_store
    request_id = str(uuid4())
    with factory() as session:
        key = history.create(session, "visitor-a", str(uuid4()))["id"]
        _, _, claim = history.begin_turn(session, key, "visitor-a", request_id, "robot")
        session.get(VisitorTurn, claim).created_at = history.now() - timedelta(minutes=16)
        session.commit()
    started = Event()
    worker_pid = []

    def stale_write():
        with factory() as session:
            stale_row = session.get(VisitorConsultation, key)
            worker_pid.append(session.scalar(text("SELECT pg_backend_pid()")))
            started.set()
            try:
                if operation == "rename":
                    history.rename(session, key, "visitor-a", "stolen")
                elif operation == "delete":
                    history.remove(session, key, "visitor-a")
                elif operation == "finish":
                    history.finish_turn(session, key, "visitor-a", request_id, "robot",
                                        AskResponse(answer="late", hit=True), claim)
                else:
                    complete_dialogue(session, stale_row, "robot", "late", owner="visitor-a")
            except HTTPException as exc:
                return exc.status_code
            except ValueError:
                return 404
            return 204

    with factory() as session, ThreadPoolExecutor(max_workers=1) as pool:
        history.owned(session, key, "visitor-a", lock=True)
        future = pool.submit(stale_write)
        try:
            assert started.wait(timeout=5)
            deadline = time.monotonic() + 5
            blocked = False
            while time.monotonic() < deadline:
                with engine.connect() as observer:
                    blocked = bool(observer.scalar(text(
                        "SELECT cardinality(pg_blocking_pids(:pid)) > 0"
                    ), {"pid": worker_pid[0]}))
                if blocked:
                    break
                time.sleep(0.01)
            assert blocked, "Guest write did not contend on the association lock"
            owner, _ = history.associate_current(session, identity(), "visitor-a", key)
        finally:
            session.rollback()  # Release the lock even if a test assertion fails.
        assert future.result(timeout=10) == (204 if operation == "delete" else 404)
    with factory() as session:
        row = history.owned(session, key, owner)
        assert row.deleted_at is None and row.title != "stolen"
        assert row.history_json == "[]"
        assert session.get(VisitorTurn, claim) is None


def test_delete_and_association_never_resurrect_a_conversation(postgres_store):
    factory, _, _ = postgres_store
    with factory() as session:
        key = history.create(session, "visitor-a", str(uuid4()))["id"]
    barrier = Barrier(2)

    def execute(associate):
        with factory() as session:
            barrier.wait(timeout=5)
            if not associate:
                history.remove(session, key, "visitor-a")
                return 204
            try:
                history.associate_current(session, identity(), "visitor-a", key)
                return 200
            except HTTPException as exc:
                return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(execute, flag) for flag in (True, False)]
        results = [f.result(timeout=10) for f in futures]
    assert results in [[200, 204], [404, 204]]
    with factory() as session:
        row = session.get(VisitorConsultation, key)
        if results[0] == 200:
            assert row.customer_id and row.deleted_at is None
        else:
            assert row.customer_id is None and row.deleted_at is not None
