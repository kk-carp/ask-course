from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend import db
from backend.config import settings
from backend.main import app
from backend.models import VisitorConsultation
from backend.schemas import OwnerInfo
from backend.services.course_catalog_service import OfficialCourse
from backend.services.approved_courses import ApprovedCourse
from backend.services.intent_router import (
    ANSWER_ASK_BASIS,
    Intent,
    classify_intent,
    handle_routed_turn,
)

QR = "https://publicqn.arborseek.com/tstj/images/1785143748273.png"
CATALOG = (
    OfficialCourse("43", "四足机器人无人巡检实训营", "巡检"),
    OfficialCourse("99", "智能机械臂抓取与操作实训营", "抓取"),
    OfficialCourse("12", "机器人操作系统之认识ROS", "ROS"),
)
APPROVED = ApprovedCourse(
    id="43", title="四足机器人无人巡检实训营", audience="有编程基础的学员",
    prerequisites="Python 基础", goals=("完成巡检任务",), goal_keywords=("巡检",),
    requires_hardware=False, min_basis="basic", min_weekly_hours=3,
    purchase_url="https://www.arborseek.com/course/43",
    source_url="https://www.arborseek.com/course/43",
)


def test_classify_default_openers() -> None:
    assert classify_intent("推荐一门适合我的课程") is Intent.recommend
    assert classify_intent("按我的基础帮我选课") is Intent.recommend
    assert classify_intent("我想找课程顾问") is Intent.advisor
    assert classify_intent("这门课适合我吗？") is Intent.recommend
    assert classify_intent("我想学巡检，这门课的目录是什么？") is Intent.content
    assert classify_intent("还有其他具身智能方向的课程吗，我想看所有相关课程") is Intent.recommend


def test_browse_related_courses_lists_without_rag_miss(monkeypatch) -> None:
    catalog = (
        OfficialCourse("43", "四足机器人无人巡检实训营", "巡检"),
        OfficialCourse("99", "智能机械臂抓取与操作实训营", "抓取"),
    )
    monkeypatch.setattr(
        "backend.services.intent_router.load_recommendable_courses", lambda: catalog
    )
    monkeypatch.setattr("backend.services.intent_router.load_approved_courses", lambda: ())
    routed = handle_routed_turn("还有其他具身智能方向的课程吗，我想看所有相关课程")
    assert routed.handled
    assert routed.intent is Intent.recommend
    assert {item.id for item in routed.related_courses} >= {"43", "99"}
    assert "较相关的有" in routed.result.answer
    assert "知识库" not in routed.result.answer


def test_goal_and_basis_answer_routes_to_course_selection() -> None:
    routed = handle_routed_turn("学过ros，想就业")
    assert routed.handled
    assert routed.intent is Intent.recommend
    assert "学过 ROS" in routed.result.answer
    assert "就业" in routed.result.answer
    assert routed.result.owner is None


def test_employment_profile_skips_knowledge_miss_and_handoff(monkeypatch) -> None:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    VisitorConsultation.__table__.create(engine)
    monkeypatch.setattr(db, "SessionLocal", sessionmaker(engine))
    monkeypatch.setattr(db, "init_engine", lambda: engine)
    monkeypatch.setattr(settings, "chat_api_key", "")
    monkeypatch.setattr(
        "backend.routes.ask.iter_answer_events",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("unexpected knowledge retrieval")),
    )
    response = TestClient(app).post(
        "/ask/stream",
        json={"question": "学过ros，想就业", "channel": "internal_tool"},
    )
    assert response.status_code == 200
    assert '"intent": "recommend"' in response.text
    assert "知识库中没有足够依据" not in response.text
    assert '"owner": null' in response.text
    engine.dispose()


def test_classify_priority_commercial_over_recommend() -> None:
    assert classify_intent("这门课能讲价吗") is Intent.commercial
    assert classify_intent("怎么开发票") is Intent.commercial


def test_undirected_recommend_does_not_call_catalog(monkeypatch) -> None:
    def boom(*_args, **_kwargs):
        raise AssertionError("undirected recommend must not call course list")

    monkeypatch.setattr(
        "backend.services.intent_router.search_related_courses", boom
    )
    routed = handle_routed_turn("推荐一门适合我的课程")
    assert routed.handled
    assert routed.intent is Intent.recommend
    assert routed.result.answer == ANSWER_ASK_BASIS
    assert routed.related_courses == ()
    assert routed.result.llm_called is False


def test_directed_recommend_lists_course_names(monkeypatch) -> None:
    monkeypatch.setattr("backend.services.intent_router.load_approved_courses", lambda: (APPROVED,))
    monkeypatch.setattr("backend.services.intent_router.load_recommendable_courses", lambda: (CATALOG[0],))
    monkeypatch.setattr("backend.services.intent_router.get_approved_course", lambda _id: APPROVED)
    monkeypatch.setattr(
        "backend.services.intent_router.search_related_courses",
        lambda question, **_kwargs: [
            item for item in CATALOG if "四足" in question or "巡检" in question
        ][:3],
    )
    called = {"retrieve": False}

    def fake_retrieve(*_args, **_kwargs):
        called["retrieve"] = True
        return []

    monkeypatch.setattr("backend.infra.retrieve.run_retrieval", fake_retrieve)

    routed = handle_routed_turn("有没有四足机器人巡检的课？")
    assert routed.handled
    assert routed.intent is Intent.recommend
    assert routed.related_courses
    assert "四足机器人无人巡检实训营" in routed.result.answer
    assert called["retrieve"] is False


def test_recommendable_course_has_no_purchase_link(monkeypatch) -> None:
    monkeypatch.setattr("backend.services.intent_router.load_recommendable_courses", lambda: (CATALOG[0],))
    monkeypatch.setattr("backend.services.intent_router.load_approved_courses", lambda: ())
    routed = handle_routed_turn("有没有四足机器人巡检的课？")
    assert [item.id for item in routed.related_courses] == ["43"]
    assert routed.related_courses[0].purchase_url is None


def test_pay_with_course_id_includes_detail_url(monkeypatch) -> None:
    monkeypatch.setattr("backend.services.intent_router.get_approved_course", lambda _id: APPROVED)
    monkeypatch.setattr(
        "backend.services.intent_router.search_related_courses",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("pay with course_id should not search by question")
        ),
    )
    routed = handle_routed_turn("怎么付款", course_id="43")
    assert routed.handled
    assert routed.intent is Intent.pay
    assert routed.related_courses[0].purchase_url == APPROVED.purchase_url
    assert "付款" in routed.result.answer
    assert routed.result.llm_called is False


def test_advisor_handoff_without_rag(monkeypatch) -> None:
    owner = OwnerInfo(
        configured=True,
        topic_key="43",
        topic_name="四足",
        name="课程顾问",
        contact=QR,
    )
    monkeypatch.setattr(
        "backend.services.intent_router.resolve_handoff",
        lambda **_kwargs: type("H", (), {"owner": owner, "route": "course_api"})(),
    )
    monkeypatch.setattr(
        "backend.services.intent_router.search_related_courses",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("no list")),
    )
    routed = handle_routed_turn("我想找课程顾问", course_id="43")
    assert routed.handled
    assert routed.intent is Intent.advisor
    assert routed.result.owner is not None
    assert routed.result.owner.contact == QR
    assert routed.result.llm_called is False


def test_content_intent_not_handled() -> None:
    routed = handle_routed_turn("这门课适合零基础吗？", course_id="43")
    assert routed.handled is False
    assert routed.intent is Intent.content
