"""Real PostgreSQL publication, withdrawal and in-flight output regressions."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from threading import Barrier, Event
from uuid import UUID, uuid4

import pytest
from alembic import command
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from starlette.requests import ClientDisconnect

from backend.config import settings
from backend.infra.generate import ChatResult
from backend.infra.retrieve import RetrievedChunk, search_dense, search_lexical
from backend.models import Document, DocumentReview, Message, User
from backend.routes import ask as ask_routes
from backend.schemas import AskRequest, AskResponse
from backend.services import ingest_service as ingest
from backend.services import qa_service, widget_history
from backend.services.ask_orchestrator import AskIdentity
from backend.services.document_admin_service import (
    DocumentDeleteError,
    publish_document,
    set_document_offline,
)
from backend.services.document_file_service import DocumentFileError, open_document_file
from backend.services.knowledge_guard import ensure_published, published_evidence
from backend.services.material_safety import REVIEW_CHECKS
from backend.services.website_identity import verified_website_identity


@pytest.fixture
def store(postgres_store, monkeypatch, tmp_path):
    factory, engine, config = postgres_store
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))
    monkeypatch.setattr(settings, "course_content_validation_mode", "off")
    monkeypatch.setattr(ingest, "is_loaded", lambda: True)
    monkeypatch.setattr(ingest, "encode_documents", lambda chunks: [[1.0] + [0.0] * 1023 for _ in chunks])
    return factory, engine, config


def candidate(text="robot original syllabus", supersedes_id=None):
    with BytesIO(text.encode()) as content:
        return ingest.ingest_document(UploadFile(filename="course.txt", file=content), "courses",
                                      course_id="43", supersedes_id=supersedes_id)


def publish(result):
    return publish_document(str(result.id), actor_id="course-reviewer", note="Course owner confirmed syllabus",
                            safety_checks=dict.fromkeys(REVIEW_CHECKS, True))


def test_upload_waits_for_review_and_replacement_is_atomic(store):
    factory, _, _ = store
    first = candidate()
    assert first.status == "pending"
    vector = [1.0] + [0.0] * 1023
    assert search_dense(vector, ["courses"], 10, course_id="43") == []
    assert search_lexical("robot", ["courses"], 10, course_id="43") == []
    publish(first)
    newer = candidate("robot revised syllabus", str(first.id))
    assert [hit.document_id for hit in search_dense(vector, ["courses"], 10, course_id="43")] == [first.id]
    publish(newer)
    assert [hit.document_id for hit in search_lexical("robot", ["courses"], 10, course_id="43")] == [newer.id]
    with factory() as session:
        assert session.get(Document, str(first.id)).status == "offline"
        audit = list(session.scalars(select(DocumentReview).where(DocumentReview.document_id == str(newer.id))))
        assert [(row.actor_id, row.action, row.note) for row in audit] == [
            ("course-reviewer", "publish", "Course owner confirmed syllabus\n安全规则2026-10-10通过；人工四项检查全部确认")]


def test_sensitive_replacement_cannot_displace_published_document(store):
    factory, _, _ = store
    old = candidate()
    publish(old)
    unsafe = candidate("robot 内部专用：未公开报价", str(old.id))
    with pytest.raises(DocumentDeleteError, match="安全检查未通过"):
        publish(unsafe)
    with factory() as session:
        assert session.get(Document, str(old.id)).status == "ready"
        assert session.get(Document, str(unsafe.id)).status == "pending"


def test_publication_requires_all_human_checks(store):
    item = candidate()
    with pytest.raises(DocumentDeleteError, match="四项检查"):
        publish_document(str(item.id), actor_id="reviewer", note="reviewed")


def test_existing_ready_material_can_be_reviewed_without_republishing_replaced_version(store):
    factory, _, _ = store
    first = candidate()
    publish(first)
    newer = candidate("robot new course syllabus", str(first.id))
    publish(newer)
    publish_document(str(newer.id), actor_id="second-reviewer", note="Rechecked public source",
                     safety_checks=dict.fromkeys(REVIEW_CHECKS, True), review_existing=True)
    with factory() as session:
        assert session.get(Document, str(first.id)).status == "offline"
        assert session.get(Document, str(newer.id)).status == "ready"
        assert session.scalar(select(func.count()).select_from(DocumentReview)
                              .where(DocumentReview.document_id == str(newer.id))) == 2


def test_legacy_material_without_hash_can_be_safety_reviewed(store):
    factory, _, _ = store
    first, second = candidate("robot one"), candidate("robot two")
    publish(first)
    publish(second)
    with factory() as session:
        session.get(Document, str(first.id)).content_hash = None
        session.get(Document, str(second.id)).content_hash = None
        session.commit()
    item = publish_document(str(first.id), actor_id="reviewer", note="Legacy material confirmed",
                            safety_checks=dict.fromkeys(REVIEW_CHECKS, True), review_existing=True)
    assert item.status == "ready"


def test_concurrent_replacement_publications_cannot_both_win(store):
    factory, _, _ = store
    first = candidate()
    publish(first)
    candidates = [candidate(f"robot revision {index}", str(first.id)) for index in (1, 2)]
    barrier = Barrier(2)

    def attempt(result):
        barrier.wait(timeout=5)
        try:
            publish(result)
            return 200
        except DocumentDeleteError as exc:
            return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(attempt, result) for result in candidates]
        assert sorted(future.result(timeout=10) for future in futures) == [200, 409]
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Document).where(Document.status == "ready")) == 1


@pytest.mark.parametrize("logged_in", [False, True])
def test_withdrawal_during_generation_discards_answer_and_does_not_save_it(store, monkeypatch, logged_in):
    factory, _, _ = store
    first = candidate()
    publish(first)
    if logged_in:
        with factory() as session:
            session.add(User(id="review-test-user", username="review-test-user", role="admin", password_hash="unused"))
            session.commit()
    hits = [RetrievedChunk(document_id=first.id, content="robot original syllabus", score=.9,
                           title="course", space_id="courses")]
    monkeypatch.setattr(qa_service, "is_loaded", lambda: True)
    monkeypatch.setattr(qa_service, "_retrieve", lambda *_a, **_kw: hits)
    started, release = Event(), Event()

    def generate(*_a, **_kw):
        started.set()
        assert release.wait(timeout=5)
        return ChatResult("This stale answer must never be delivered")

    monkeypatch.setattr(qa_service, "generate_answer", generate)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(qa_service.answer_question, ["courses"], "robot syllabus?",
                             user_id="review-test-user" if logged_in else None)
        try:
            assert started.wait(timeout=5)
            set_document_offline(str(first.id), actor_id="reviewer")
        finally:
            release.set()
        with pytest.raises(HTTPException) as exc:
            future.result(timeout=10)
        assert exc.value.status_code == 409
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Message)) == 0


def test_all_used_documents_are_checked_even_when_only_three_sources_are_shown(store, monkeypatch):
    docs = [candidate(f"robot document {index}") for index in range(4)]
    for doc in docs:
        publish(doc)
    hits = [RetrievedChunk(document_id=doc.id, content="robot", score=.9, title="course", space_id="courses") for doc in docs]
    monkeypatch.setattr(qa_service, "is_loaded", lambda: True)
    monkeypatch.setattr(qa_service, "_retrieve", lambda *_a, **_kw: hits)
    monkeypatch.setattr(qa_service, "generate_answer", lambda *_a, **_kw: ChatResult("reviewed answer"))
    result = qa_service.answer_question(["courses"], "robot syllabus?")
    assert len(result.sources) == 3
    assert len(result.knowledge_document_ids) == 4
    set_document_offline(str(docs[3].id))
    with pytest.raises(HTTPException):
        ensure_published(result.knowledge_document_ids)


def test_output_guard_serializes_with_withdrawal_commit(store):
    factory, engine, _ = store
    doc = candidate()
    publish(doc)
    started = Event()
    pid = []

    def withdraw():
        with factory() as session:
            pid.append(session.scalar(text("SELECT pg_backend_pid()")))
            started.set()
            row = session.scalar(select(Document).where(Document.id == str(doc.id)).with_for_update())
            row.status = "offline"
            session.commit()

    with ThreadPoolExecutor(max_workers=1) as pool:
        with published_evidence([doc.id]):
            future = pool.submit(withdraw)
            assert started.wait(timeout=5)
            import time

            deadline = time.monotonic() + 5
            blocked = False
            while time.monotonic() < deadline:
                with engine.connect() as connection:
                    blocked = bool(connection.scalar(text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"), {"pid": pid[0]}))
                if blocked:
                    break
                time.sleep(.01)
            assert blocked, "Withdrawal did not contend with the output guard"
        future.result(timeout=10)
    with pytest.raises(HTTPException):
        ensure_published([doc.id])


def test_reviewed_data_refuses_destructive_migration_rollback(store):
    _, engine, config = store
    publish(candidate())
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        with pytest.raises(RuntimeError, match="Cannot discard"):
            command.downgrade(config, "0003")


def test_missing_document_fails_closed(store):
    with pytest.raises(HTTPException) as exc:
        ensure_published([UUID(str(uuid4()))])
    assert exc.value.status_code == 409


def test_pending_original_is_only_available_to_a_document_manager(store):
    doc = candidate()
    with pytest.raises(DocumentFileError) as exc:
        open_document_file(str(doc.id), ["courses"])
    assert exc.value.status_code == 404
    path, _ = open_document_file(str(doc.id), ["courses"], allow_unpublished=True)
    assert path.read_text() == "robot original syllabus"
    with pytest.raises(DocumentFileError) as exc:
        open_document_file(str(doc.id), [], allow_unpublished=True)
    assert exc.value.status_code == 403
    with pytest.raises(DocumentDeleteError):
        publish_document(str(doc.id), actor_id="reviewer", note="   ")


@pytest.mark.parametrize("stream", [False, True])
def test_http_boundary_rejects_withdrawn_answer_and_sse_discards_previous_parts(store, monkeypatch, stream):
    doc = candidate()
    publish(doc)
    result = AskResponse(answer="stale answer", hit=True, knowledge_document_ids=[doc.id])
    app = FastAPI()
    app.include_router(ask_routes.router)
    app.dependency_overrides[verified_website_identity] = lambda: None
    monkeypatch.setattr(ask_routes, "_prepare_request", lambda *_args: AskIdentity(["courses"], None, None, None))

    def turns(*_args):
        yield "part", {"index":1, "question":"robot", **result.model_dump(mode="json")}
        set_document_offline(str(doc.id))
        yield "final", result

    def run(*_args):
        set_document_offline(str(doc.id))
        return result

    monkeypatch.setattr(ask_routes, "_website_turns", turns)
    monkeypatch.setattr(ask_routes, "run_ask_turn", run)
    response = TestClient(app).post("/ask/stream" if stream else "/ask", json={"question":"robot"})
    if stream:
        assert "event: part" in response.text
        assert "event: final" not in response.text
        assert '"discard_answer": true' in response.text
        assert '"status": 409' in response.text
    else:
        assert response.status_code == 409
        assert "stale answer" not in response.text


def test_idempotent_cached_response_cannot_replay_withdrawn_knowledge(store):
    factory, _, _ = store
    doc = candidate()
    publish(doc)
    request_id = str(uuid4())
    with factory() as session:
        conversation_id = widget_history.create(session, "review-visitor", str(uuid4()))["id"]
        _, _, claim = widget_history.begin_turn(session, conversation_id, "review-visitor", request_id, "robot")
        widget_history.finish_turn(session, conversation_id, "review-visitor", request_id, "robot",
                                   AskResponse(answer="historical answer", knowledge_document_ids=[doc.id]), claim)
    set_document_offline(str(doc.id))
    payload = AskRequest(question="robot", channel="site_widget", conversation_id=UUID(conversation_id), request_id=UUID(request_id))
    with pytest.raises(HTTPException) as exc:
        next(ask_routes._website_turns(payload, AskIdentity(["courses"], None, None, "review-visitor")))
    assert exc.value.status_code == 409


def test_browser_disconnect_releases_stream_publication_lock(store):
    doc = candidate()
    publish(doc)
    closed = Event()

    def events():
        try:
            with published_evidence([doc.id]):
                yield "event: meta\ndata: {}\n\n"
        finally:
            closed.set()

    response = ask_routes.ReviewedStreamResponse(events(), media_type="text/event-stream")

    async def scenario():
        async def receive():
            await asyncio.sleep(10)
            return {"type":"http.disconnect"}

        async def send(message):
            if message["type"] == "http.response.body":
                raise ConnectionError("browser disconnected")

        with pytest.raises(ClientDisconnect):
            await response({"type":"http", "asgi":{"spec_version":"2.4"}}, receive, send)

    asyncio.run(scenario())
    assert closed.is_set()
    # A leaked shared lock would time out this real PostgreSQL write.
    set_document_offline(str(doc.id))
