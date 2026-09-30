import json

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend import db
from backend.config import settings
from backend.main import app
from backend.models import VisitorConsultation
from backend.services.course_catalog_service import OfficialCourse
from backend.services.qa_service import AskResult


def test_guest_profile_and_question_share_one_owned_conversation(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    VisitorConsultation.__table__.create(engine)
    factory = sessionmaker(engine)
    monkeypatch.setattr(db, "SessionLocal", factory)
    monkeypatch.setattr(db, "init_engine", lambda: engine)
    monkeypatch.setattr(settings, "chat_api_key", "")
    catalog = (OfficialCourse("43", "四足机器人无人巡检实训营", "巡检编排"),)
    for module in (
        "backend.services.consultation_service",
        "backend.services.intent_router",
        "backend.services.ask_orchestrator",
    ):
        monkeypatch.setattr(f"{module}.load_recommendable_courses", lambda: catalog)
    monkeypatch.setattr("backend.services.consultation_service.load_approved_courses", lambda: ())
    monkeypatch.setattr("backend.services.ask_orchestrator.get_approved_course", lambda *_a, **_k: None)
    monkeypatch.setattr(
        "backend.services.ask_orchestrator.course_context_for_content",
        lambda *_args: ("43", []),
    )
    monkeypatch.setattr("backend.services.ask_orchestrator.public_fact_topic", lambda _q: None)
    seen = {}

    def answer_question(**kwargs):
        seen.update(kwargs)
        return AskResult(answer="依据当前课程资料回答", hit=True, sources=[])

    monkeypatch.setattr("backend.services.ask_orchestrator.answer_question", answer_question)
    client = TestClient(app)
    first = client.post("/ask", json={"question": "学过ros，想就业", "channel": "internal_tool"})
    assert first.status_code == 200, first.text
    first_data = first.json()
    assert first_data["intent"] == "recommend"
    assert first_data["conversation_id"]
    assert "通过课程完成什么" in first_data["answer"]

    second = client.post("/ask", json={
        "question": "想做机器人巡检", "channel": "internal_tool",
        "conversation_id": first_data["conversation_id"],
    })
    assert second.status_code == 200, second.text
    assert second.json()["conversation_id"] == first_data["conversation_id"]
    assert [item["id"] for item in second.json()["related_courses"]] == ["43"]

    third = client.post("/ask", json={
        "question": "证书怎么拿？", "channel": "internal_tool",
        "conversation_id": first_data["conversation_id"],
    })
    assert third.status_code == 200, third.text
    assert ("user", "想做机器人巡检") in seen["visitor_history"]
    with factory() as session:
        row = session.get(VisitorConsultation, first_data["conversation_id"])
        profile = json.loads(row.profile_json)
        assert profile["basis"] == "basic"
        assert "巡检" in profile["goal"]
    assert TestClient(app).post("/ask", json={
        "question": "证书怎么拿？", "channel": "internal_tool",
        "conversation_id": first_data["conversation_id"],
    }).status_code == 404
    engine.dispose()


def test_python_and_ros_background_advances_course_selection(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    VisitorConsultation.__table__.create(engine)
    factory = sessionmaker(engine)
    monkeypatch.setattr(db, "SessionLocal", factory)
    monkeypatch.setattr(db, "init_engine", lambda: engine)
    monkeypatch.setattr(settings, "chat_api_key", "")
    catalog = (OfficialCourse("99", "智能机械臂抓取与操作实训营", "机械臂抓取与操作"),)
    monkeypatch.setattr(
        "backend.services.consultation_service.load_approved_courses", lambda: ()
    )
    for module in (
        "backend.services.consultation_service",
        "backend.services.intent_router",
        "backend.services.ask_orchestrator",
    ):
        monkeypatch.setattr(f"{module}.load_recommendable_courses", lambda: catalog)
    monkeypatch.setattr("backend.services.ask_orchestrator.get_approved_course", lambda *_a, **_k: None)
    client = TestClient(app)
    # 无方向开场进问诊；有方向且目录命中会直接列课，不走多轮画像。
    first = client.post("/ask", json={"question": "推荐一门适合我的课程", "channel": "internal_tool"})
    assert first.status_code == 200
    assert "通过课程完成什么" in first.json()["answer"]
    second = client.post("/ask", json={
        "question": "想学机械臂",
        "channel": "internal_tool",
        "conversation_id": first.json()["conversation_id"],
    })
    assert second.status_code == 200
    assert [item["id"] for item in second.json()["related_courses"]] == ["99"]
    assert second.json()["related_courses"][0]["purchase_url"] is None
    with factory() as session:
        row = session.get(VisitorConsultation, first.json()["conversation_id"])
        assert "机械臂" in json.loads(row.profile_json)["goal"]
    engine.dispose()


def test_guest_directed_recommend_lists_without_consultation(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    VisitorConsultation.__table__.create(engine)
    factory = sessionmaker(engine)
    monkeypatch.setattr(db, "SessionLocal", factory)
    monkeypatch.setattr(db, "init_engine", lambda: engine)
    monkeypatch.setattr(settings, "chat_api_key", "")
    catalog = (OfficialCourse("43", "四足机器人无人巡检实训营", "巡检"),)
    for module in (
        "backend.services.consultation_service",
        "backend.services.intent_router",
        "backend.services.ask_orchestrator",
    ):
        monkeypatch.setattr(f"{module}.load_recommendable_courses", lambda: catalog)
    monkeypatch.setattr("backend.services.ask_orchestrator.get_approved_course", lambda *_a, **_k: None)
    monkeypatch.setattr("backend.services.intent_router.load_approved_courses", lambda: ())
    monkeypatch.setattr(
        "backend.services.ask_orchestrator.answer_question",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("must not RAG")),
    )
    client = TestClient(app)
    response = client.post(
        "/ask",
        json={"question": "有没有四足机器人巡检的课？", "channel": "internal_tool"},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["intent"] == "recommend"
    assert [item["id"] for item in data["related_courses"]] == ["43"]
    assert "四足机器人无人巡检实训营" in data["answer"]
    assert "通过课程完成什么" not in data["answer"]
    assert data["related_courses"][0]["source_url"].endswith("/43")
    engine.dispose()


def test_undirected_opener_ignores_stale_visitor_profile(monkeypatch):
    """重启后 cookie 仍在时，无方向开场不得沿用旧 goal 直接荐课。"""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    VisitorConsultation.__table__.create(engine)
    factory = sessionmaker(engine)
    monkeypatch.setattr(db, "SessionLocal", factory)
    monkeypatch.setattr(db, "init_engine", lambda: engine)
    monkeypatch.setattr(settings, "chat_api_key", "")
    catalog = (OfficialCourse("99", "智能机械臂抓取与操作实训营", "机械臂抓取与操作"),)
    for module in (
        "backend.services.consultation_service",
        "backend.services.intent_router",
        "backend.services.ask_orchestrator",
    ):
        monkeypatch.setattr(f"{module}.load_recommendable_courses", lambda: catalog)
    monkeypatch.setattr("backend.services.consultation_service.load_approved_courses", lambda: ())
    monkeypatch.setattr("backend.services.ask_orchestrator.get_approved_course", lambda *_a, **_k: None)

    client = TestClient(app)
    seeded = client.post("/ask", json={"question": "想学机械臂", "channel": "internal_tool"})
    assert seeded.status_code == 200
    assert [item["id"] for item in seeded.json()["related_courses"]] == ["99"]

    again = client.post("/ask", json={"question": "推荐一门适合我的课程", "channel": "internal_tool"})
    assert again.status_code == 200, again.text
    data = again.json()
    assert data["conversation_id"] != seeded.json()["conversation_id"]
    assert "通过课程完成什么" in data["answer"]
    assert data["related_courses"] == []
    with factory() as session:
        row = session.get(VisitorConsultation, data["conversation_id"])
        profile = json.loads(row.profile_json)
        assert "goal" not in profile
        assert profile.get("_pending_field") == "goal"
    engine.dispose()
