"""用已采集的官网文字回答概览问题；未公开的要求明确保留未知。

数据边界：
- approved / recommendable：可进入推荐与卡片
- draft（official_course_drafts）：仅支撑公开事实，不可单独作为购买依据
- 公开事实不足时返回依据不足，调用方不得再对本轮跑 RAG 编造官网事实
"""

import json
import re
from pathlib import Path

from backend.services.course_catalog_service import OfficialCourse

_DRAFTS = Path(__file__).resolve().parents[2] / "data" / "official_course_drafts"

ANSWER_PUBLIC_INSUFFICIENT = (
    "当前公开资料不足以回答这一点。你可以查看官网课程详情，或向课程顾问确认。"
)

_TOPIC_PATTERNS = (
    ("hardware", r"硬件|设备|自备|真机"),
    ("basis", r"什么基础|基础要求|零基础|入门门槛"),
    ("overview", r"学什么|学哪些|课程内容|具体.*内容|讲什么|课程介绍|学习方式|怎么上课|如何上课|线上|录播"),
)


def public_fact_topic(question: str) -> str | None:
    """识别是否在问官网可公开的事实类问题。"""
    for name, pattern in _TOPIC_PATTERNS:
        if re.search(pattern, question or ""):
            return name
    return None


def answer_public_question(question: str, course: OfficialCourse) -> str | None:
    topic = public_fact_topic(question)
    if topic is None or not course.course_id.isdigit():
        return None
    try:
        snapshot = json.loads((_DRAFTS / f"{course.course_id}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        snapshot = {}
    description = course.description or snapshot.get("description", "")
    subtitle = snapshot.get("subtitle", "")
    features = snapshot.get("course_features", [])
    if topic == "hardware":
        return (
            f"「{course.title}」的官网介绍：{description}\n"
            "现有资料没有明确说明学员是否必须自备硬件，因此我还不能确认没有硬件时能完成哪些练习。"
            "可以先查看官网课程详情，购买前再向课程顾问确认这一点。"
        )
    if topic == "basis":
        relevant = [item["content"] for item in features if "基础" in item.get("title", "")]
        evidence = "；".join([subtitle, *relevant]).strip("；")
        return f"「{course.title}」的官网说明：{evidence or '暂未公开明确的基础要求'}。更具体的前置技能要求仍需课程方确认。"
    facts = "；".join(f"{item['title']}：{item['content']}" for item in features)
    if not description and not facts:
        return None
    return f"「{course.title}」的官网介绍：{description}" + (f"\n{facts}" if facts else "")
