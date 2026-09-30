"""只从访客原话提取选课画像；模型不决定课程、价格或购买入口。"""

from __future__ import annotations

import json
import re

from backend.config import settings
from backend.services.consultation_service import validate_answer

_SPECIFIC_GOAL = re.compile(r"ROS|巡检|机械臂|抓取|导航|SLAM|大模型|智能体|编程|视觉", re.I)
_GOAL_STATEMENT = re.compile(r"(?:想学|想学习|想做|希望做|准备做|打算做|目标是|方向是)(.{0,100})")
_HARDWARE = r"(?:硬件|机器人|机器狗|Go2|设备|机械臂)"
_HOUR_NUMBERS = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def looks_like_profile(text: str, expected_field: str | None = None) -> bool:
    if any(mark in text for mark in "？?吗么"):
        return False
    return bool(_rules(text) or _contextual_reply(text, expected_field)) or bool(re.search(r"想学|想做|想就业|想求职", text))


def _contextual_reply(text: str, field: str | None) -> dict:
    """短回答只解释为上一问的答案，不能脱离上下文猜测。"""
    value = text.strip().strip("，。！! ")
    choices = {
        "hardware": {"没有": "no", "没": "no", "无": "no", "暂时没有": "no", "有": "yes", "有的": "yes", "不确定": "unknown", "不知道": "unknown"},
        "basis": {"没有": "none", "没学过": "none", "不会": "none", "有": "basic", "学过": "basic", "学过一点": "basic", "会一点": "basic", "有一点": "basic"},
    }
    if field in choices and value in choices[field]:
        return {field: choices[field][value]}
    if field == "weekly_hours":
        return _rules(f"每周{value}" if "小时" in value else f"每周{value}小时")
    if field == "goal" and _SPECIFIC_GOAL.search(value) and not re.search(r"[？?]|怎么|什么|多少", value):
        return {"goal": value[:200]}
    return {}


def _rules(text: str) -> dict:
    found: dict = {}
    if re.search(r"零基础|没(?:有)?(?:学过编程|编程基础|基础)|无(?:编程)?基础", text):
        found["basis"] = "none"
    elif not re.search(r"没有项目经验|没做过项目|无项目经验", text) and re.search(
        r"做过.{0,8}项目|有项目经验|项目经验丰富", text
    ):
        found["basis"] = "experienced"
    elif re.search(
        r"有一定基础|有点基础|(?<!没)(?<!没有)学过\s*(?:Python|ROS|C\+\+|编程)|"
        r"(?<!不)(?:会|懂)\s*(?:Python|ROS|C\+\+|编程)|有(?:编程|Python|ROS)基础",
        text, re.I,
    ):
        found["basis"] = "basic"
    if re.search(r"不确定|不知道|不清楚|暂不清楚", text) and re.search(_HARDWARE, text, re.I):
        found["hardware"] = "unknown"
    elif re.search(rf"(?:没有|没|无).{{0,4}}{_HARDWARE}", text, re.I):
        found["hardware"] = "no"
    elif re.search(rf"(?:有|具备).{{0,8}}{_HARDWARE}", text, re.I):
        found["hardware"] = "yes"
    hours = re.search(
        r"(?:每周|一周|每星期|一星期).{0,8}?(\d{1,2}|[一二两三四五六七八九十])"
        r"(?:\s*[-到至~]\s*(?:\d{1,2}|[一二两三四五六七八九十]))?\s*(?:个)?小时",
        text,
    )
    if hours:
        number = hours.group(1)
        found["weekly_hours"] = int(number) if number.isdigit() else _HOUR_NUMBERS[number]
    goal_statement = _GOAL_STATEMENT.search(text)
    if goal_statement and _SPECIFIC_GOAL.search(goal_statement.group(1)):
        found["goal"] = text.strip()[:200]
    elif _SPECIFIC_GOAL.fullmatch(text.strip()):
        found["goal"] = text.strip()
    return found


def extract_profile_updates(text: str, current: dict, expected_field: str | None = None) -> dict:
    """模型仅做保守槽位提取；失败时按明确措辞提取，未知项继续追问。"""
    proposal = {**_contextual_reply(text, expected_field), **_rules(text)}
    goal_statement = _GOAL_STATEMENT.search(text)
    if settings.chat_api_key and not proposal:
        from backend.infra.generate import complete_chat

        try:
            result = complete_chat([
                {
                    "role": "system",
                    "content": (
                        "从访客本轮原话提取选课信息，仅输出 JSON 对象。允许键："
                        "goal（具体技术/应用目标，不要只写就业、竞赛等宽泛目的）、"
                        "basis（none/basic/experienced）、hardware（yes/no/unknown）、"
                        "weekly_hours（1-80 的整数）。只填明确说出的信息；不推断、不推荐课程。"
                        f"上一问对应的字段：{expected_field or '无'}。短回答仅按该字段解释。"
                    ),
                },
                {"role": "user", "content": text[:500]},
            ])
            parsed = json.loads(result.text)
            if isinstance(parsed, dict):
                proposal = {**parsed, **proposal}
        except Exception:
            pass
    updates: dict = {}
    for field in ("goal", "basis", "hardware", "weekly_hours"):
        if field not in proposal:
            continue
        try:
            value = validate_answer(field, proposal[field])
        except ValueError:
            continue
        if field == "goal" and expected_field != "goal" and not _SPECIFIC_GOAL.fullmatch(text.strip()) and (
            not goal_statement or not _SPECIFIC_GOAL.search(goal_statement.group(1))
        ):
            continue
        if current.get(field) != value:
            updates[field] = value
    return updates
