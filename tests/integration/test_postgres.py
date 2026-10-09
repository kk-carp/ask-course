"""Database semantics that SQLite and mocked retrieval cannot verify."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from uuid import uuid4

import pytest
from alembic import command
from fastapi import HTTPException
from sqlalchemy import func, select, text

from backend.infra.chunk_tsv import update_chunk_content_tsv
from backend.infra.retrieve import search_dense, search_lexical
from backend.models import Chunk, Document, Space, VisitorConsultation, VisitorTurn
from backend.schemas import AskResponse
from backend.services import widget_history as history


def test_migration_preserves_legacy_data_and_is_repeatable(postgres_store):
    factory, engine, config = postgres_store
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, "0001")
        connection.execute(text(
            "INSERT INTO visitor_consultations (id, visitor_id, profile_json, history_json, status) "
            "VALUES ('legacy-session', 'legacy-visitor', '{}', '[]', 'collecting')"
        ))
        command.upgrade(config, "head")
        command.upgrade(config, "head")
    with factory() as session:
        row = session.get(VisitorConsultation, "legacy-session")
        assert row.visitor_id == "legacy-visitor"
        assert row.last_activity_at is not None
        assert not row.widget_session
        assert session.scalar(text("SELECT version_num FROM alembic_version")) == "0002"


def test_dense_and_lexical_filter_before_returning_results(postgres_store):
    factory, _, _ = postgres_store
    expected = None
    vector = [1.0] + [0.0] * 1023
    with factory() as session:
        session.add(Space(id="private-test", name="Private"))
        session.flush()
        for space, course, status in [
            ("courses", "43", "ready"),
            ("courses", "42", "ready"),
            ("courses", "43", "offline"),
            ("courses", "43", "processing"),
            ("courses", "43", "failed"),
            ("private-test", "43", "ready"),
        ]:
            doc = Document(space_id=space, course_id=course, status=status,
                           title="Robot course", file_path="test-only.md")
            session.add(doc)
            session.flush()
            chunk = Chunk(document_id=doc.id, space_id=space, chunk_index=0,
                          content="robot hardware syllabus", embedding=vector)
            session.add(chunk)
            session.flush()
            update_chunk_content_tsv(session, chunk.id, chunk.content)
            if space == "courses" and course == "43" and status == "ready":
                expected = doc.id
        session.commit()
    for hits in [search_dense(vector, ["courses"], 20, course_id="43"),
                 search_lexical("robot", ["courses"], 20, course_id="43")]:
        assert [str(hit.document_id) for hit in hits] == [expected]
    assert search_dense(vector, [], 20, course_id="43") == []


def test_concurrent_creation_and_turn_claim_are_idempotent(postgres_store):
    factory, _, _ = postgres_store
    creation_key, request_id = str(uuid4()), str(uuid4())
    barrier = Barrier(2)

    def create():
        with factory() as session:
            barrier.wait(timeout=5)
            return history.create(session, "visitor-a", creation_key)["id"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(create) for _ in range(2)]
        ids = [future.result(timeout=10) for future in futures]
    assert ids[0] == ids[1]
    barrier = Barrier(2)

    def claim():
        with factory() as session:
            barrier.wait(timeout=5)
            try:
                history.begin_turn(session, ids[0], "visitor-a", request_id, "robot")
                return 200
            except HTTPException as exc:
                return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(claim) for _ in range(2)]
        assert sorted(future.result(timeout=10) for future in futures) == [200, 409]
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(VisitorTurn)) == 1
        with pytest.raises(HTTPException) as exc:
            history.owned(session, ids[0], "visitor-b")
        assert exc.value.status_code == 404


def test_delete_lock_prevents_late_answer_from_reviving_history(postgres_store):
    factory, engine, _ = postgres_store
    request_id = str(uuid4())
    with factory() as session:
        key = history.create(session, "visitor-a", str(uuid4()))["id"]
        _, _, claim_id = history.begin_turn(session, key, "visitor-a", request_id, "robot")
    started = Event()
    worker_pid = []

    def finish():
        with factory() as session:
            worker_pid.append(session.scalar(text("SELECT pg_backend_pid()")))
            started.set()
            try:
                history.finish_turn(session, key, "visitor-a", request_id, "robot",
                                    AskResponse(answer="answer", hit=True), claim_id)
            except HTTPException as exc:
                return exc.status_code
            return 200

    with factory() as session, ThreadPoolExecutor(max_workers=1) as pool:
        row = history.owned(session, key, "visitor-a", lock=True)
        row.deleted_at = history.now()
        future = pool.submit(finish)
        try:
            assert started.wait(timeout=5)
            # Confirm PostgreSQL sees the worker waiting on the deletion lock.
            import time

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
            assert blocked, "Late answer did not contend on the row lock"
        finally:
            session.commit()
        assert future.result(timeout=10) == 404
    with factory() as session:
        turn = session.scalar(select(VisitorTurn).where(VisitorTurn.request_id == request_id))
        assert turn.response_json is None
        assert session.get(VisitorConsultation, key).deleted_at is not None
