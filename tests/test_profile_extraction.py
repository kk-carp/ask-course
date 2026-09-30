import pytest

from backend.config import settings
from backend.services.profile_extraction import extract_profile_updates, looks_like_profile


@pytest.mark.parametrize(
    ("text", "field", "expected"),
    [
        ("想就业，方向是机械臂", "goal", "想就业，方向是机械臂"),
        ("我准备做机器人巡检", "goal", "我准备做机器人巡检"),
        ("没有基础", "basis", "none"),
        ("我会Python", "basis", "basic"),
        ("学过C++", "basis", "basic"),
        ("做过机器人项目", "basis", "experienced"),
        ("没有项目经验，学过Python", "basis", "basic"),
        ("没有机器狗", "hardware", "no"),
        ("没硬件", "hardware", "no"),
        ("有一台Go2", "hardware", "yes"),
        ("不确定有没有硬件", "hardware", "unknown"),
        ("一周4小时", "weekly_hours", 4),
        ("每周大约三小时", "weekly_hours", 3),
    ],
)
def test_common_profile_phrasings(monkeypatch, text, field, expected):
    monkeypatch.setattr(settings, "chat_api_key", "")
    assert looks_like_profile(text)
    assert extract_profile_updates(text, {})[field] == expected


def test_one_message_can_fill_multiple_fields(monkeypatch):
    monkeypatch.setattr(settings, "chat_api_key", "")
    assert extract_profile_updates("想学机械臂，没硬件，每周三小时", {}) == {
        "goal": "想学机械臂，没硬件，每周三小时",
        "hardware": "no",
        "weekly_hours": 3,
    }
