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
from backend.models import FunnelEvent, PilotControl, VisitorConsultation, VisitorTurn
from backend.schemas import AskRequest, AskResponse
from backend.services import widget_history as history
from backend.services.course_scope import course_scope


@pytest.fixture
def store(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    for table in (
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
