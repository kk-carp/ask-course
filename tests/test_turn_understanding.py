import json

from backend.config import settings
from backend.infra.generate import ChatResult, ChatUsage
from backend.services import turn_understanding
from backend.services.course_catalog_service import OfficialCourse

CATALOG = (OfficialCourse("43", "测试四足课程", "巡检"), OfficialCourse("99", "测试机械臂课程", "抓取"))


def parse(question, profile=None):
    return turn_understanding.understand_turn(question, page_course_id="43", profile=profile or {}, history=[], catalog=CATALOG)


def test_single_semantic_parse_extracts_all_fields_and_correction(monkeypatch):
    monkeypatch.setattr(settings, "chat_api_key", "test")
    calls = []

    def complete(messages):
        calls.append(messages)
        return ChatResult(json.dumps({"questions": ["想学机械臂"], "intent": "recommend", "course_id": "99", "profile_updates": {"basis": "basic", "hardware": "no", "weekly_hours": 4}}), ChatUsage(20, 10))

    monkeypatch.setattr(turn_understanding, "complete_chat", complete)
    result = parse("刚才说错了，机器已经还回去了，每星期四小时", {"hardware": "yes"})
    assert result.profile_updates == {"basis": "basic", "hardware": "no", "weekly_hours": 4}
    assert result.course_id == "99" and len(calls) == 1
    assert result.prompt_tokens == 20


def test_hallucinated_course_and_invalid_profile_are_rejected(monkeypatch):
    monkeypatch.setattr(settings, "chat_api_key", "test")
    monkeypatch.setattr(turn_understanding, "complete_chat", lambda *_a: ChatResult(json.dumps({"questions": ["多少钱"], "course_id": "666", "profile_updates": {"price": 1, "weekly_hours": True}, "compare_ids": ["666"]})))
    result = parse("价格多少")
    assert result.course_id == "43" and result.profile_updates == {} and result.compare_ids == []


def test_model_failure_preserves_explicit_multi_questions(monkeypatch):
    monkeypatch.setattr(settings, "chat_api_key", "test")
    monkeypatch.setattr(turn_understanding, "complete_chat", lambda *_a: ChatResult("not json"))
    assert len(parse("价格多少？能看多久？有优惠吗？").questions) == 3


def test_ordinal_and_comparison_without_model(monkeypatch):
    monkeypatch.setattr(settings, "chat_api_key", "")
    profile = {"_candidate_course_ids": ["43", "99"], "_selected_course_id": "43"}
    assert parse("第二门价格多少", profile).course_id == "99"
    assert parse("这两门有什么区别", profile).compare_ids == ["43", "99"]
    assert parse("当前页面这门课价格多少", profile).course_id == "43"
