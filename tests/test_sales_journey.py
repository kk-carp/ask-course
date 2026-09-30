import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend import db
from backend.config import settings
from backend.main import app
from backend.models import VisitorConsultation
from backend.schemas import OwnerInfo, SourceItem
from backend.services.qa_service import AskResult
from backend.services.consultation_service import QUESTIONS
from backend.services.course_catalog_service import OfficialCourse

COURSES = (
    OfficialCourse("42", "高校大学生AI大模型企业实战训练营", "面向大学生的 AI 大模型实战训练营"),
    OfficialCourse("43", "四足机器人无人巡检实训营", "ROS2 通信、SLAM 建图与巡检编排"),
    OfficialCourse("99", "智能机械臂抓取与操作实训营", "ROS2 通信、MoveIt2 运动规划、视觉定位与手眼标定，讲师端真机演示"),
)


@pytest.fixture
def sales_chat(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    VisitorConsultation.__table__.create(engine)
    factory = sessionmaker(engine)
    monkeypatch.setattr(db, "SessionLocal", factory)
    monkeypatch.setattr(db, "init_engine", lambda: engine)
    monkeypatch.setattr(settings, "chat_api_key", "")
    monkeypatch.setattr("backend.services.course_facts.live_course", lambda cid: ({"id": int(cid), "price": 899, "original_price": "1299.00"}, "2026-09-30"))
    for module in (
        "backend.services.ask_orchestrator",
        "backend.services.consultation_service",
        "backend.services.intent_router",
    ):
        monkeypatch.setattr(f"{module}.load_recommendable_courses", lambda: COURSES)
    monkeypatch.setattr("backend.services.consultation_service.load_approved_courses", lambda: ())
    monkeypatch.setattr("backend.services.intent_router.load_approved_courses", lambda: ())
    monkeypatch.setattr("backend.services.ask_orchestrator.get_approved_course", lambda *_a, **_k: None)
    monkeypatch.setattr(
        "backend.services.ask_orchestrator.answer_question",
        lambda **kwargs: pytest.fail("课程选购对话不应误入知识库"),
    )
    client = TestClient(app)
    yield client, factory
    engine.dispose()


def send(client, question, conversation_id=None, course_id=None):
    response = client.post("/ask", json={
        "question": question, "channel": "internal_tool",
        "conversation_id": conversation_id, "course_id": course_id,
    })
    assert response.status_code == 200, response.text
    return response.json()


def test_recommend_first_then_answer_course_questions_and_switch_goal(sales_chat):
    client, _ = sales_chat
    first = send(client, "想学机械臂")
    assert [item["id"] for item in first["related_courses"]] == ["99"]
    assert first["owner"] is None
    assert "每周大约" not in first["answer"]
    assert "如果方便" in first["answer"]
    assert "你有可用于" in first["answer"]
    cid = first["conversation_id"]
    second = send(client, "没有", cid)
    assert "没有练习硬件" in second["answer"]
    assert second["related_courses"][0]["id"] == "99"
    detail = send(client, "课程具体学什么？", cid)
    assert detail["intent"] == "course_info"
    assert "MoveIt2" in detail["answer"]
    assert detail["related_courses"][0]["source_url"].endswith("/99")
    hardware = send(client, "没有真机能学吗？", cid)
    assert "允许仿真练习" in hardware["answer"]
    assert hardware["fact_sources"]
    assert hardware["owner"] is None
    changed = send(client, "还是想学大模型", cid)
    assert [item["id"] for item in changed["related_courses"]] == ["42"]


def test_old_hardware_question_accepts_bare_no(sales_chat):
    client, factory = sales_chat
    first = send(client, "想学机械臂")
    cid = first["conversation_id"]
    with factory() as session:
        row = session.get(VisitorConsultation, cid)
        row.profile_json = json.dumps({"goal": "想学机械臂", "basis": "basic"})
        row.history_json = json.dumps([{"role": "assistant", "content": "已记录。" + QUESTIONS["hardware"]}])
        session.commit()
    result = send(client, "没有", cid)
    assert result["related_courses"][0]["id"] == "99"
    assert result["owner"] is None
    with factory() as session:
        assert json.loads(session.get(VisitorConsultation, cid).profile_json)["hardware"] == "no"


def test_explicit_handoff_uses_last_recommended_course(sales_chat, monkeypatch):
    client, _ = sales_chat
    seen = {}

    def handoff(**kwargs):
        seen.update(kwargs)
        return type("H", (), {"owner": OwnerInfo(configured=False)})()

    monkeypatch.setattr("backend.services.intent_router.resolve_handoff", handoff)
    first = send(client, "想学机械臂")
    result = send(client, "找人工", first["conversation_id"])
    assert result["intent"] == "advisor"
    assert seen["course_id"] == "99"


def test_page_context_handoff_follows_selected_other_course(sales_chat, monkeypatch):
    client, _ = sales_chat
    seen = {}

    def handoff(**kwargs):
        seen.update(kwargs)
        return type("H", (), {"owner": OwnerInfo(configured=False)})()

    monkeypatch.setattr("backend.services.intent_router.resolve_handoff", handoff)
    first = send(client, "想学机械臂", course_id="43")
    assert [item["id"] for item in first["related_courses"]] == ["99"]
    result = send(client, "找人工", first["conversation_id"], course_id="43")
    assert result["intent"] == "advisor"
    assert seen["course_id"] == "99"


def test_recommend_list_binds_course_for_commercial_handoff(sales_chat, monkeypatch):
    client, factory = sales_chat
    seen = {}

    def handoff(**kwargs):
        seen.update(kwargs)
        return type("H", (), {"owner": OwnerInfo(configured=False)})()

    monkeypatch.setattr("backend.services.intent_router.resolve_handoff", handoff)
    first = send(client, "大模型方向有推荐的课程吗")
    assert [item["id"] for item in first["related_courses"]] == ["42"]
    with factory() as session:
        profile = json.loads(
            session.get(VisitorConsultation, first["conversation_id"]).profile_json
        )
        assert profile["_selected_course_id"] == "42"
    result = send(client, "还能便宜一点吗？", first["conversation_id"])
    assert result["intent"] == "commercial"
    assert seen["course_id"] == "42"


def test_no_course_match_does_not_automatically_handoff(sales_chat):
    client, _ = sales_chat
    result = send(client, "想学视觉，推荐课程")
    assert result["related_courses"] == []
    assert result["owner"] is None
    assert "没有找到" in result["answer"]


def test_three_questions_answer_individually_and_save_one_turn(sales_chat, monkeypatch):
    client, factory = sales_chat
    seen = []
    source = SourceItem(document_id=uuid4(), title="审核课程资料", space_id="course", snippet="价格 599 元，可观看 12 个月")

    def knowledge(**kwargs):
        seen.append((kwargs["question"], kwargs["course_id"]))
        answer = "资料中列出的价格为 599 元。" if "价格" in kwargs["question"] else "资料中说明可观看 12 个月。"
        return AskResult(answer=answer, hit=True, sources=[source], llm_called=True, prompt_tokens=10)

    owner = OwnerInfo(configured=True, topic_key="99", name="机械臂顾问", contact="https://example.com/contact")

    def handoff(**kwargs):
        assert kwargs["course_id"] == "99"
        return type("H", (), {"owner": owner})()

    monkeypatch.setattr("backend.services.ask_orchestrator.answer_question", knowledge)
    monkeypatch.setattr("backend.services.intent_router.resolve_handoff", handoff)
    first = send(client, "想学机械臂")
    question = "这个课程价格多少？能看多久？有优惠吗？"
    result = send(client, question, first["conversation_id"])
    assert result["intent"] == "multi_question"
    assert "899 元" in result["answer"]
    assert "期限资料存在冲突" in result["answer"]
    assert "课程顾问确认" in result["answer"]
    assert seen == []
    assert result["owner"] is None
    assert result["prompt_tokens"] == 0
    assert len(result["fact_sources"]) == 3
    with factory() as session:
        history = json.loads(session.get(VisitorConsultation, first["conversation_id"]).history_json)
        assert len(history) == 4
        assert history[-2] == {"role": "user", "content": question}
        assert history[-1]["content"] == result["answer"]


def test_mixed_public_answer_and_handoff_keeps_both(sales_chat, monkeypatch):
    client, _ = sales_chat
    owner = OwnerInfo(configured=True, topic_key="99", name="机械臂顾问", contact="https://example.com/contact")

    def handoff(**kwargs):
        assert kwargs["course_id"] == "99"
        return type("H", (), {"owner": owner})()

    monkeypatch.setattr("backend.services.intent_router.resolve_handoff", handoff)
    # 顾问问题在前；课程归属需要从整条消息取得，不能只看第一个子问题。
    result = send(client, "还能便宜一点吗？智能机械臂课程具体学什么？")
    assert result["intent"] == "multi_question"
    assert "MoveIt2" in result["answer"]
    assert result["owner"]["topic_key"] == "99"
    assert [item["id"] for item in result["related_courses"]] == ["99"]


@pytest.mark.parametrize("logged_in", [False, True])
def test_multi_question_stream_uses_individual_answers(sales_chat, monkeypatch, logged_in):
    client, _ = sales_chat
    if logged_in:
        context = SimpleNamespace(user=SimpleNamespace(id="admin", role="admin"), allowed_spaces=["course"])
        monkeypatch.setattr("backend.routes.ask.load_auth_context", lambda _request: context)
    monkeypatch.setattr(
        "backend.services.intent_router.resolve_handoff",
        lambda **kwargs: type("H", (), {"owner": OwnerInfo(configured=False)})(),
    )
    response = client.post("/ask/stream", json={
        "question": "这门课学什么？还能便宜一点吗？", "course_id": "99", "channel": "internal_tool",
    })
    assert response.status_code == 200, response.text
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    result = next(event for event in events if "answer" in event)
    assert result["intent"] == "multi_question"
    assert "MoveIt2" in result["answer"]
    assert "联系方式" in result["answer"]
    assert result["owner"]["configured"] is False
    assert "event: done" in response.text


def test_missing_three_question_facts_are_not_invented(sales_chat, monkeypatch):
    client, _ = sales_chat
    monkeypatch.setattr("backend.services.ask_orchestrator.answer_course_fact", lambda *_a: None)
    monkeypatch.setattr(
        "backend.services.ask_orchestrator.answer_question",
        lambda **kwargs: AskResult(answer="当前资料没有足够依据回答。", hit=False, sources=[]),
    )
    for module in ("ask_orchestrator", "intent_router"):
        monkeypatch.setattr(
            f"backend.services.{module}.resolve_handoff",
            lambda **kwargs: type("H", (), {"owner": OwnerInfo(configured=False)})(),
        )
    result = send(client, "价格多少？能看多久？还能便宜一点吗？", course_id="99")
    assert result["answer"].count("没有足够依据") == 2
    assert all(f"{index}." in result["answer"] for index in (1, 2, 3))
    assert result["hit"] is False
    assert result["sources"] == []
    assert result["owner"]["configured"] is False


def test_one_upstream_failure_keeps_other_answers(sales_chat, monkeypatch):
    from backend.errors import UpstreamServiceError

    client, _ = sales_chat

    def unavailable(**kwargs):
        raise UpstreamServiceError("模型暂不可用")

    monkeypatch.setattr("backend.services.ask_orchestrator.answer_question", unavailable)
    result = send(client, "讲师的研究方向是什么？课程具体学什么？", course_id="99")
    assert "这项查询暂时不可用" in result["answer"]
    assert "MoveIt2" in result["answer"]
    assert result["error_type"] == "upstream_error"
