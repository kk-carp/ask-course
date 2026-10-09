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
from backend.services.course_facts import fact_topic

_DRAFTS = Path(__file__).resolve().parents[2] / "data" / "official_course_drafts"

ANSWER_PUBLIC_INSUFFICIENT = (
    "当前公开资料不足以回答这一点。你可以查看官网课程详情，或向课程顾问确认。"
)


def public_fact_topic(question: str) -> str | None:
    """复用事实主题；快照仅补充概览、基础、硬件与公开授课方式。"""
    topic = fact_topic(question)
    if topic == "schedule":
        # 开课日期不能用课程简介代答；这里只允许公开授课方式。
        return "overview" if re.search(r"学习方式|怎么上课|如何上课|线上|录播", question) else None
    return {"hardware": "hardware", "basis": "basis", "outline": "overview"}.get(topic)


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
