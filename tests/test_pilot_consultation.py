from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend import db
from backend.config import settings
from backend.db import get_session
from backend.main import app
from backend.models import FunnelEvent, PilotControl, VisitorConsultation
from backend.schemas import OwnerInfo
from backend.services.approved_courses import ApprovedCourse, parse_approved_courses
from backend.services.course_catalog_service import OfficialCourse
from backend.services.intent_router import ANSWER_COURSE_UNAVAILABLE, handle_routed_turn


COURSE = ApprovedCourse(
    id="43",
    title="机器人巡检课程",
    audience="有编程基础的学员",
    prerequisites="Python 基础",
    goals=("完成机器人巡检",),
    goal_keywords=("巡检", "机器人"),
    requires_hardware=False,
    min_basis="basic",
    min_weekly_hours=3,
    purchase_url="https://www.arborseek.com/course/43",
    source_url="https://www.arborseek.com/course/43",
)


def test_catalog_rejects_draft_placeholder_and_wrong_purchase_url():
    base = dict(
        id="43",
        status="approved",
        title="机器人巡检",
        audience="工程师",
        prerequisites="Python",
        goals=["巡检"],
        goal_keywords=["巡检"],
        requires_hardware=False,
        min_basis="basic",
        min_weekly_hours=3,
        purchase_url=COURSE.purchase_url,
        reviewer="运营甲",
        reviewed_at="2026-09-24",
        review_checks={
            "sale_status_confirmed": True,
            "purchase_page_checked": True,
            "course_facts_checked": True,
            "course_content_checked": True,
            "presale_contact_checked": True,
        },
    )
    assert len(parse_approved_courses({"courses": [base]})) == 1
    assert parse_approved_courses({"courses": [{**base, "status": "draft"}]}) == ()
    assert parse_approved_courses({"courses": [{**base, "review_checks": {}}]}) == ()
    assert parse_approved_courses({"courses": [{**base, "reviewer": "待填写"}]}) == ()
    assert (
        parse_approved_courses(
            {"courses": [{**base, "purchase_url": "https://evil.example/course/43"}]}
        )
        == ()
    )
    assert parse_approved_courses(
        {"courses": [{**base, "purchase_url": COURSE.purchase_url + "?redirect=https://evil.example"}]}
    ) == ()


def test_unknown_course_never_emits_purchase_url(monkeypatch):
    monkeypatch.setattr(
        "backend.services.intent_router.get_approved_course", lambda _id: None
    )
    routed = handle_routed_turn("怎么付款", course_id="999")
    assert routed.result.answer == ANSWER_COURSE_UNAVAILABLE
    assert routed.related_courses == ()


def test_consultation_flow_is_owned_and_purchase_is_revalidated(monkeypatch):
    monkeypatch.setattr("backend.routes.consultations.validate_purchase_destination", lambda course: course.purchase_url)
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    VisitorConsultation.__table__.create(engine)
    FunnelEvent.__table__.create(engine)
    PilotControl.__table__.create(engine)
    factory = sessionmaker(engine)
    monkeypatch.setattr("backend.db.SessionLocal", factory)

    def session_override():
        with factory() as session:
            yield session

    app.dependency_overrides[get_session] = session_override
    monkeypatch.setattr(settings, "pilot_course_ids", "43")
    monkeypatch.setattr(settings, "pilot_percent", 100)
    monkeypatch.setattr(
        "backend.routes.consultations.get_approved_course",
        lambda _id, **_kwargs: COURSE,
    )
    monkeypatch.setattr(
        "backend.services.pilot_service.course_ready", lambda _session, _id: True
    )
    monkeypatch.setattr(
        "backend.services.pilot_service.get_approved_course", lambda _id: COURSE
    )
    monkeypatch.setattr(
        "backend.services.consultation_service.load_approved_courses", lambda: (COURSE,)
    )
    monkeypatch.setattr(
        "backend.services.consultation_service.load_recommendable_courses", lambda: ()
    )
    monkeypatch.setattr(
        "backend.services.consultation_service.resolve_handoff",
        lambda **_kwargs: type("H", (), {"owner": OwnerInfo(configured=False)})(),
    )
    try:
        client = TestClient(app)
        assert client.get("/widget/config", params={"course_id": "43"}).json()[
            "enabled"
        ]
        assert client.get("/widget/config", params={"course_id": "43"}).json()[
            "default_prompts"
        ][0] == "推荐一门适合我的课程"
        created = client.post("/consultations", json={"course_id": "43"}).json()
        assert created["next_field"] == "goal"
        known = client.post("/consultations", json={"course_id": "43", "known_profile": {"basis": "basic"}}).json()
        assert known["next_field"] == "goal"
        after_goal = client.post(f"/consultations/{known['id']}/answers", json={"field": "goal", "value": "机器人巡检"}).json()
        assert after_goal["next_field"] == "weekly_hours"
        assert client.post("/consultations", json={"course_id": "43", "known_profile": {"basis": "invented"}}).status_code == 422
        consultation_id = created["id"]
        assert (
            TestClient(app).get(f"/consultations/{consultation_id}").status_code == 404
        )
        for field, value in (
            ("goal", "我想做机器人巡检"),
            ("basis", "basic"),
            ("hardware", "no"),
            ("weekly_hours", 4),
        ):
            response = client.post(
                f"/consultations/{consultation_id}/answers",
                json={"field": field, "value": value},
            )
            assert response.status_code == 200, response.text
        result = response.json()
        assert result["status"] == "recommended"
        assert result["recommendations"][0]["id"] == "43"
        assert "巡检" in result["recommendations"][0]["reason"]
        assert client.post("/purchase/43").json()["url"] == COURSE.purchase_url
        with factory() as session:
            assert session.scalar(select(FunnelEvent.event_name)) == "purchase_click"
            session.add(PilotControl(id=1, percent=0))
            session.commit()
        assert (
            client.get("/widget/config", params={"course_id": "43"}).json()["enabled"]
            is False
        )
        assert client.post("/purchase/43").status_code == 404
        assert (
            client.post(
                "/ask",
                json={
                    "question": "这门课适合我吗",
                    "course_id": "43",
                    "channel": "course_page",
                },
            ).status_code
            == 404
        )
        with factory() as session:
            session.get(PilotControl, 1).percent = 100
            session.commit()
        monkeypatch.setattr(
            "backend.routes.consultations.get_approved_course",
            lambda _id, **_kwargs: None,
        )
        assert client.post("/purchase/43").status_code == 404
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_hard_filter_and_handoff(monkeypatch):
    from backend.models import VisitorConsultation
    from backend.services.consultation_service import present

    monkeypatch.setattr(
        "backend.services.consultation_service.load_approved_courses", lambda: (COURSE,)
    )
    monkeypatch.setattr(
        "backend.services.consultation_service.load_recommendable_courses", lambda: ()
    )
    monkeypatch.setattr(
        "backend.services.consultation_service.resolve_handoff",
        lambda **_kwargs: type("H", (), {"owner": OwnerInfo(configured=False)})(),
    )
    row = VisitorConsultation(
        id="one",
        visitor_id="v",
        course_id="43",
        profile_json='{"goal":"机器人巡检","basis":"none","hardware":"no","weekly_hours":4}',
    )
    result = present(None, row)
    assert result["status"] == "handoff"
    assert result["recommendations"] == []
    assert "机器人巡检" in result["summary"]


def test_uncertain_hardware_does_not_recommend_hardware_course(monkeypatch):
    from dataclasses import replace

    from backend.services.consultation_service import present

    hardware_course = replace(COURSE, requires_hardware=True)
    seen = {}

    def handoff(**kwargs):
        seen.update(kwargs)
        return type("H", (), {"owner": OwnerInfo(configured=False)})()

    monkeypatch.setattr(
        "backend.services.consultation_service.load_approved_courses",
        lambda: (hardware_course,),
    )
    monkeypatch.setattr(
        "backend.services.consultation_service.load_recommendable_courses", lambda: ()
    )
    monkeypatch.setattr("backend.services.consultation_service.resolve_handoff", handoff)
    row = VisitorConsultation(
        id="uncertain",
        visitor_id="v",
        course_id="43",
        profile_json='{"goal":"机器人巡检","basis":"basic","hardware":"unknown","weekly_hours":4}',
    )
    result = present(None, row)
    assert result["status"] == "handoff"
    assert result["recommendations"] == []
    assert seen["course_id"] == "43"


@pytest.mark.parametrize("basis,hardware,hours", [("none", "yes", 4), ("basic", "no", 4), ("basic", "yes", 1)])
def test_project_exploration_does_not_restore_ineligible_courses(monkeypatch, basis, hardware, hours):
    from dataclasses import replace
    from backend.services.consultation_service import _recommend

    monkeypatch.setattr("backend.services.consultation_service.load_approved_courses", lambda: (replace(COURSE, requires_hardware=True),))
    monkeypatch.setattr("backend.services.consultation_service.load_recommendable_courses", lambda: (OfficialCourse("43", COURSE.title, "巡检演示"),))
    assert _recommend({"goal": "保研项目", "basis": basis, "hardware": hardware, "weekly_hours": hours}, None) == []


def test_project_exploration_can_show_eligible_approved_course(monkeypatch):
    from backend.services.consultation_service import _recommend

    monkeypatch.setattr("backend.services.consultation_service.load_approved_courses", lambda: (COURSE,))
    monkeypatch.setattr("backend.services.consultation_service.load_recommendable_courses", lambda: (OfficialCourse("43", COURSE.title, "巡检演示"),))
    result = _recommend({"goal": "保研项目", "basis": "basic", "hardware": "no", "weekly_hours": 4}, None)
    assert result[0]["id"] == "43" and "先了解" in result[0]["reason"]


def test_recommendable_course_uses_official_description_without_purchase(monkeypatch):
    from backend.models import VisitorConsultation
    from backend.services.consultation_service import present

    monkeypatch.setattr(
        "backend.services.consultation_service.load_approved_courses", lambda: ()
    )
    monkeypatch.setattr(
        "backend.services.consultation_service.load_recommendable_courses",
        lambda: (OfficialCourse("43", "四足机器人无人巡检实训营", "ROS2 与巡检编排"),),
    )
    row = VisitorConsultation(
        id="candidate", visitor_id="v", course_id="43",
        profile_json='{"goal":"想学机器人巡检","basis":"none","hardware":"unknown","weekly_hours":2}',
    )
    result = present(None, row)
    assert result["status"] == "recommended"
    assert result["recommendations"][0]["purchase_url"] is None
    assert "不足以确认" in result["recommendations"][0]["reason"]


def test_direct_course_question_scopes_knowledge_retrieval(monkeypatch):
    from backend.services.qa_service import AskResult

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    VisitorConsultation.__table__.create(engine)
    monkeypatch.setattr(db, "SessionLocal", sessionmaker(engine))
    monkeypatch.setattr(db, "init_engine", lambda: engine)
    monkeypatch.setattr(settings, "chat_api_key", "")
    seen = {}

    def answer_question(**kwargs):
        seen.update(kwargs)
        return AskResult(answer="没有可用依据", hit=False, sources=[])

    monkeypatch.setattr("backend.services.ask_orchestrator.answer_question", answer_question)
    monkeypatch.setattr(
        "backend.services.ask_orchestrator.resolve_handoff",
        lambda **_kwargs: type("H", (), {"owner": OwnerInfo(configured=False)})(),
    )
    response = TestClient(app).post(
        "/ask", json={"question": "这门课有多少课时？", "course_id": "43"}
    )
    assert response.status_code == 200
    assert seen["course_id"] == "43"
    engine.dispose()


def test_strict_course_upload_requires_course_id(monkeypatch):
    from io import BytesIO
    from fastapi import UploadFile
    from backend.services import ingest_service

    monkeypatch.setattr(ingest_service, "is_loaded", lambda: True)
    monkeypatch.setattr(settings, "course_content_validation_mode", "strict")
    file = UploadFile(filename="course.md", file=BytesIO(b"content"))
    try:
        import pytest

        with pytest.raises(ValueError, match="course_id"):
            ingest_service.ingest_document(file, settings.course_space_id)
    finally:
        file.file.close()
