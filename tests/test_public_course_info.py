from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend import db
from backend.config import settings
from backend.main import app
from backend.models import VisitorConsultation
from backend.services.course_catalog_service import OfficialCourse
from backend.services.public_course_info import (
    ANSWER_PUBLIC_INSUFFICIENT,
    answer_public_question,
    public_fact_topic,
)


def test_public_fact_topic_detects_overview_and_hardware() -> None:
    assert public_fact_topic("课程具体学什么？") == "overview"
    assert public_fact_topic("没有真机能学吗？") == "hardware"
    assert public_fact_topic("今天天气怎么样") is None


def test_snapshot_topics_share_fact_priority_and_do_not_answer_dates() -> None:
    assert public_fact_topic("价格包含硬件吗？") is None
    assert public_fact_topic("课程什么时候开课？") is None
    assert public_fact_topic("课程如何上课？") == "overview"
    assert public_fact_topic("需要什么先修知识？") == "basis"


def test_overview_without_draft_facts_returns_none(monkeypatch) -> None:
    empty = Path(__file__).resolve().parent / "_missing_official_drafts"
    monkeypatch.setattr("backend.services.public_course_info._DRAFTS", empty)
    course = OfficialCourse("777", "空壳课", "")
    assert answer_public_question("课程具体学什么？", course) is None
    assert ANSWER_PUBLIC_INSUFFICIENT


def test_public_insufficient_skips_rag(monkeypatch) -> None:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    VisitorConsultation.__table__.create(engine)
    factory = sessionmaker(engine)
    monkeypatch.setattr(db, "SessionLocal", factory)
    monkeypatch.setattr(db, "init_engine", lambda: engine)
    monkeypatch.setattr(settings, "chat_api_key", "")
    course = OfficialCourse("777", "空壳课", "")
    monkeypatch.setattr(
        "backend.services.ask_orchestrator.load_recommendable_courses",
        lambda: (course,),
    )
    monkeypatch.setattr(
        "backend.services.course_catalog_service.get_course_by_id",
        lambda _id: course,
    )
    monkeypatch.setattr(
        "backend.services.ask_orchestrator.answer_public_question",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "backend.services.ask_orchestrator.answer_question",
        lambda **_k: (_ for _ in ()).throw(AssertionError("must not RAG")),
    )
    client = TestClient(app)
    response = client.post(
        "/ask",
        json={
            "question": "课程具体学什么？",
            "course_id": "777",
            "channel": "internal_tool",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["intent"] == "course_info"
    assert data["answer"] == ANSWER_PUBLIC_INSUFFICIENT
    assert data["hit"] is False
    assert data["related_courses"][0]["id"] == "777"
    engine.dispose()
