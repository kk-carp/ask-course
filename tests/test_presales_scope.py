"""售前精简回归：主链路、管理员迁移、课程空间隔离与无依据拒答。"""

import json
from io import BytesIO
from uuid import uuid4

import pytest
from fastapi import UploadFile
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend import db
from backend.config import settings
from backend.domain.membership import get_allowed_spaces_for_user
from backend.errors import UpstreamServiceError
from backend.infra import generate
from backend.infra.generate import ChatResult, ChatUsage
from backend.infra.retrieve import RetrievedChunk
from backend.infra.storage import save_upload
from backend.main import app
from backend.models import (
    Conversation,
    Message,
    Space,
    SpaceMember,
    User,
    VisitorConsultation,
)
from backend.schemas import OwnerInfo
from backend.seed.course_owners import P0_ADMIN_USERNAME, _seed_admin_user
from backend.services import qa_service
from backend.services.auth_service import AuthContext, AuthUser, can_manage_documents
from backend.services.handoff_service import HandoffResult


@pytest.fixture
def sessions(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    for table in (Space, User, SpaceMember, Conversation, Message, VisitorConsultation):
        table.__table__.create(engine)
    factory = sessionmaker(engine)
    monkeypatch.setattr(db, "init_engine", lambda: engine)
    monkeypatch.setattr(db, "SessionLocal", factory)
    yield factory
    engine.dispose()


def fail_model(*_args, **_kwargs):
    raise AssertionError("无课程依据时不得调用模型")


def sse_events(response):
    return [
        (block.splitlines()[0].removeprefix("event: "),
         json.loads(block.splitlines()[1].removeprefix("data: ")))
        for block in response.text.strip().split("\n\n")
    ]


def ask_http(monkeypatch, stream, logged_in):
    context = AuthContext(AuthUser("admin", "admin", "admin"), [settings.course_space_id]) if logged_in else None
    monkeypatch.setattr("backend.routes.ask.load_auth_context", lambda _r: context)
    monkeypatch.setattr("backend.routes.ask.allow_ask", lambda _id: True)
    monkeypatch.setattr("backend.routes.ask._allow_guest_ask", lambda _id: True)
    monkeypatch.setattr("backend.services.course_catalog_service.load_official_courses", lambda **_k: ())
    monkeypatch.setattr(settings, "handoff_enabled", False)
    return TestClient(app).post(
        "/ask/stream" if stream else "/ask",
        json={"question": "课时多久？", "course_id": "43", "channel": "internal_tool"},
    )


def ask_response(monkeypatch, stream, logged_in):
    response = ask_http(monkeypatch, stream, logged_in)
    assert response.status_code == 200
    if not stream:
        return response.json()
    events = sse_events(response)
    assert [name for name, _ in events] == ["progress", "meta", "final", "done"]
    return next(data for name, data in events if name == "final")


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("logged_in", [False, True])
def test_knowledge_miss_never_generates(monkeypatch, sessions, stream, logged_in):
    monkeypatch.setattr(qa_service, "is_loaded", lambda: True)
    monkeypatch.setattr(qa_service, "_retrieve", lambda *_a, **_k: [])
    monkeypatch.setattr(qa_service, "generate_answer", fail_model)
    with sessions() as session:
        session.add(
            User(id="admin", username="admin", role="admin", password_hash="unused")
        )
        session.commit()
    result = ask_response(monkeypatch, stream, logged_in)
    assert result["hit"] is False
    assert result["llm_called"] is False
    assert result["sources"] == []
    if logged_in:
        with sessions() as session:
            assert len(session.scalars(select(Message)).all()) == 2


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("logged_in", [False, True])
def test_course_answer_preserves_sources_and_history(
    monkeypatch, sessions, stream, logged_in
):
    chunk = RetrievedChunk(
        content="课程周期为十二周。",
        score=0.9,
        document_id=uuid4(),
        title="四足机器人课程",
        space_id=settings.course_space_id,
    )
    monkeypatch.setattr(qa_service, "is_loaded", lambda: True)
    monkeypatch.setattr(qa_service, "_retrieve", lambda *_a, **_k: [chunk])
    generated = ChatResult("课程周期为十二周。", ChatUsage(12, 8))
    monkeypatch.setattr(qa_service, "generate_answer", lambda *_a, **_k: generated)
    with sessions() as session:
        session.add(
            User(id="admin", username="admin", role="admin", password_hash="unused")
        )
        session.commit()
    result = ask_response(monkeypatch, stream, logged_in)
    assert result["hit"] is True
    assert result["sources"][0]["document_id"] == str(chunk.document_id)
    assert result["answer"] == generated.text
    assert result["llm_called"] is True
    assert result["prompt_tokens"] == 12
    if logged_in:
        with sessions() as session:
            assert len(session.scalars(select(Message)).all()) == 2


def test_generation_requires_knowledge_even_with_history():
    with pytest.raises(ValueError, match="没有知识库依据"):
        generate.generate_answer("有没有证书？", [], history=[("assistant", "保证拿证")])


def test_guest_history_only_guides_local_retrieval(monkeypatch):
    chunk = RetrievedChunk(
        content="课程资料说明了基础要求。", score=0.9,
        document_id=uuid4(), title="课程资料", space_id=settings.course_space_id,
    )
    seen = {}
    monkeypatch.setattr(qa_service, "is_loaded", lambda: True)

    def retrieve(*_args, **kwargs):
        seen["previous"] = kwargs.get("previous_user_question")
        return [chunk]

    def generate_answer(*_args, **kwargs):
        seen["generation_kwargs"] = kwargs
        return ChatResult("根据本轮资料回答。")

    monkeypatch.setattr(qa_service, "_retrieve", retrieve)
    monkeypatch.setattr(qa_service, "generate_answer", generate_answer)
    result = qa_service.answer_question(
        [settings.course_space_id], "那基础呢？",
        visitor_history=[("user", "巡检课程学什么？"), ("assistant", "先看课程资料。")],
    )
    assert result.hit is True
    assert seen["previous"] == "巡检课程学什么？"
    assert "history" not in seen["generation_kwargs"]


def test_admin_seed_migrates_only_project_account_and_keeps_credentials(sessions):
    with sessions() as session:
        session.add(Space(id=settings.course_space_id, name="课程"))
        session.add_all(
            [
                User(
                    id="old-admin",
                    username=P0_ADMIN_USERNAME,
                    role="teaching",
                    is_teaching=True,
                    password_hash="keep-this",
                ),
                User(
                    id="teacher",
                    username="teaching_demo",
                    role="teaching",
                    is_teaching=True,
                    password_hash="other",
                ),
            ]
        )
        session.commit()
        _seed_admin_user(session)
        _seed_admin_user(session)
        session.commit()
        assert session.get(User, "old-admin").role == "admin"
        assert session.get(User, "old-admin").password_hash == "keep-this"
        assert session.get(User, "teacher").role == "teaching"
        assert len(session.scalars(select(SpaceMember)).all()) == 1


def test_fresh_admin_seed(sessions):
    with sessions() as session:
        session.add(Space(id=settings.course_space_id, name="课程"))
        session.commit()
        _seed_admin_user(session)
        session.commit()
        user = session.scalar(select(User))
        assert user.role == "admin"
        assert session.get(SpaceMember, (user.id, settings.course_space_id)) is not None


def test_legacy_memberships_cannot_expand_course_access(sessions):
    with sessions() as session:
        session.add(
            User(id="admin", username="admin", role="admin", password_hash="unused")
        )
        for space_id in (settings.course_space_id, "student", "company"):
            session.add(Space(id=space_id, name=space_id))
            session.add(SpaceMember(user_id="admin", space_id=space_id))
        session.commit()
    assert get_allowed_spaces_for_user("admin") == [settings.course_space_id]
    assert get_allowed_spaces_for_user("unknown") == []


@pytest.mark.parametrize("role", ["guest", "student", "employee", "teaching", "admin"])
def test_only_admin_manages_documents(role):
    user = AuthUser(id="u", username="u", role=role)
    assert can_manage_documents(user) is (role == "admin")


@pytest.mark.parametrize("role, status", [("admin", 200), ("teaching", 403)])
def test_metrics_uses_presales_admin_permission(monkeypatch, role, status):
    context = AuthContext(AuthUser(id="u", username="u", role=role), [settings.course_space_id])
    monkeypatch.setattr("backend.routes.metrics.load_auth_context", lambda _r: context)
    response = TestClient(app).get("/metrics")
    assert response.status_code == status
    if status == 200:
        assert "ask_total" in response.json()


def test_upload_retains_course_documents_but_rejects_code_archives(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path))
    saved = save_upload(
        UploadFile(filename="课程.md", file=BytesIO("课程介绍".encode())),
        settings.course_space_id,
    )
    assert saved.path.read_text(encoding="utf-8") == "课程介绍"
    with pytest.raises(ValueError, match="extension"):
        save_upload(
            UploadFile(filename="code.zip", file=BytesIO(b"zip")),
            settings.course_space_id,
        )
    with pytest.raises(ValueError, match="space_id"):
        save_upload(UploadFile(filename="course.md", file=BytesIO(b"text")), "student")


@pytest.mark.parametrize("stream", [False, True])
def test_guest_api_miss_hands_off_to_selected_course(monkeypatch, sessions, stream):
    monkeypatch.setattr("backend.routes.ask.load_auth_context", lambda _r: None)
    monkeypatch.setattr("backend.routes.ask._allow_guest_ask", lambda _id: True)
    monkeypatch.setattr(qa_service, "is_loaded", lambda: True)
    monkeypatch.setattr(qa_service, "_retrieve", lambda *_a, **_k: [])
    monkeypatch.setattr(qa_service, "generate_answer", fail_model)

    def handoff(*, question, course_id):
        assert course_id == "43"
        return HandoffResult(
            OwnerInfo(
                configured=True,
                topic_key="43",
                name="课程顾问",
                contact="https://work.weixin.qq.com/ca/course43",
            ),
            "course_id",
        )

    monkeypatch.setattr("backend.services.ask_orchestrator.resolve_handoff", handoff)
    # No context manager: skip model/database startup; exercise actual HTTP routes.
    with_request = TestClient(app)
    response = with_request.post(
        "/ask/stream" if stream else "/ask",
        json={"question": "课时多久？", "course_id": "43"},
    )
    assert response.status_code == 200
    if stream:
        assert '"topic_key": "43"' in response.text
        assert "event: done" in response.text
    else:
        assert response.json()["owner"]["topic_key"] == "43"
        assert response.json()["llm_called"] is False


@pytest.mark.parametrize("stream", [False, True])
def test_model_failure_does_not_save_answer(monkeypatch, sessions, stream):
    chunk = RetrievedChunk(
        content="正文",
        score=0.9,
        document_id=uuid4(),
        title="课程",
        space_id=settings.course_space_id,
    )
    monkeypatch.setattr(qa_service, "is_loaded", lambda: True)
    monkeypatch.setattr(qa_service, "_retrieve", lambda *_a, **_k: [chunk])

    def fail(*_a, **_k):
        raise UpstreamServiceError("模型不可用")

    monkeypatch.setattr(qa_service, "generate_answer", fail)
    with sessions() as session:
        session.add(
            User(id="admin", username="admin", role="admin", password_hash="unused")
        )
        session.commit()
    response = ask_http(monkeypatch, stream, logged_in=True)
    if stream:
        assert response.status_code == 200
        errors = [data for name, data in sse_events(response) if name == "error"]
        assert errors[0]["status"] == 502
        assert not any(name == "final" for name, _ in sse_events(response))
    else:
        assert response.status_code == 502
    with sessions() as session:
        assert session.scalars(select(Message)).all() == []
        assert session.scalars(select(Conversation)).all() == []
