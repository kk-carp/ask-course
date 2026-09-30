import httpx
import pytest

from backend.services import course_facts
from backend.services.intent_router import Intent, classify_intent


@pytest.mark.parametrize("value,expected", [(600, "600"), ("1999.00", "1999"), (0, "0"), (None, None), ("NaN", None), (-1, None)])
def test_price_units_are_preserved(value, expected):
    assert course_facts._money(value) == expected


def test_public_promotion_is_not_negotiation():
    assert classify_intent("有优惠吗？") is Intent.content
    assert classify_intent("还能便宜一点吗？") is Intent.commercial


def test_materials_override_old_unknown_hardware():
    answer, sources = course_facts.answer_course_fact("没有真机能学吗？", "99")
    assert "允许仿真练习" in answer
    assert "Ubuntu 22.04" in answer
    assert sources[0]["source"].startswith("docs/")


def test_validity_conflict_is_explicit():
    answer, sources = course_facts.answer_course_fact("能看多久？", "43")
    assert "冲突" in answer
    assert sources[0]["status"] == "conflict"


def test_live_price_and_promotion(monkeypatch):
    monkeypatch.setattr(course_facts, "live_course", lambda _: ({"id": 42, "price": 599, "original_price": "1999.00"}, "2026-09-30"))
    answer, sources = course_facts.answer_course_fact("有优惠吗？", "42")
    assert "599 元" in answer and "1999 元" in answer
    assert "未提供额外" in answer
    assert sources[0]["status"] == "official"


def test_expired_price_is_not_returned_on_failure(monkeypatch):
    monkeypatch.setattr(course_facts, "_cache", {"42": (0, {"id": 42, "price": 1}, "old")})
    monkeypatch.setattr(httpx.Client, "get", lambda *_a, **_k: (_ for _ in ()).throw(httpx.ConnectError("offline")))
    answer, sources = course_facts.answer_course_fact("价格多少？", "42")
    assert "无法读取" in answer and sources == []
