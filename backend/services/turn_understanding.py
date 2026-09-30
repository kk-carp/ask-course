"""一次解析本轮问题、课程指代与画像变化，失败回退到明确规则。"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from backend.config import settings
from backend.infra.generate import complete_chat
from backend.services.consultation_service import validate_answer
from backend.services.course_catalog_service import OfficialCourse
from backend.services.intent_router import classify_intent
from backend.services.course_facts import fact_topic
from backend.services.profile_extraction import extract_profile_updates
from backend.services.question_decomposition import split_questions

_log = logging.getLogger(__name__)


class ParsedTurn(BaseModel):
    questions: list[str] = Field(min_length=1, max_length=5)
    intent: str = "content"
    course_id: str | None = None
    profile_updates: dict = Field(default_factory=dict)
    compare_ids: list[str] = Field(default_factory=list, max_length=3)


@dataclass
class Understanding:
    questions: list[str]
    intent: str
    course_id: str | None = None
    profile_updates: dict = field(default_factory=dict)
    compare_ids: list[str] = field(default_factory=list)
    llm_called: bool = False
    prompt_tokens: int = 0
    completion_tokens: int = 0


def understand_turn(question: str, *, page_course_id: str | None, profile: dict,
                    history: list, catalog: tuple[OfficialCourse, ...]) -> Understanding:
    candidates = profile.get("_candidate_course_ids", [])
    selected = profile.get("_selected_course_id") or page_course_id
    fallback = Understanding(
        questions=split_questions(question)[:5], intent=classify_intent(question).value,
        course_id=selected,
        profile_updates=extract_profile_updates(question, profile, profile.get("_pending_field"), use_model=False),
    )
    ordinal = re.search(r"第([一二三123])(?:门|个|款)", question)
    explicit = next((x.course_id for x in catalog if x.title in question or
                     re.search(rf"(?:课程\s*(?:ID\s*)?{re.escape(x.course_id)})(?!\d)", question, re.I)), None)
    if explicit:
        fallback.course_id = explicit
    if ordinal:
        index = "一二三".find(ordinal.group(1)) if not ordinal.group(1).isdigit() else int(ordinal.group(1)) - 1
        if 0 <= index < len(candidates):
            fallback.course_id = candidates[index]
    if re.search(r"(?:这|那)(?:两|几|三)门|对比|比较|区别", question) and len(candidates) >= 2:
        fallback.compare_ids = candidates[:3]
    if re.search(r"当前页面|这页|页面上", question):
        fallback.course_id = page_course_id
    reference_locked = bool(explicit or ordinal or re.search(
        r"当前页面|这页|页面上|这门课|这个课|该课|^(?:找人工|找课程顾问|找顾问|联系顾问|转人工)$", question))
    if not settings.chat_api_key:
        return fallback
    allowed = {item.course_id for item in catalog} | set(candidates)
    if page_course_id:
        allowed.add(page_course_id)
    try:
        result = complete_chat([
            {"role": "system", "content": (
                "你是课程咨询语义解析器，仅返回 JSON。不要回答问题、选课、编造事实或链接。"
                "questions 必须是访客本轮表达的请求或问题，绝不能生成你想追问访客的问题。"
                "画像陈述原样保留为一个请求。例：访客说‘想学机械臂，没硬件’时，questions=[原话]，intent=recommend。"
                "字段 questions（最多5个可独立回答的问题，保留目标与否定，画像陈述不拆开）；"
                "intent（content/recommend/pay/commercial/advisor）；course_id（明确指代的已提供ID或null）；"
                "compare_ids（仅明确要求比较时给已提供ID）；profile_updates（仅本轮明确表达或纠正的字段）。"
                "画像字段 goal=具体技术/应用方向，basis=none/basic/experienced，hardware=yes/no/unknown，"
                "weekly_hours=1到80整数。修正覆盖旧值，没说的字段不要填。"
                "区分当前页面课程与正在咨询课程；第几门按候选顺序；指代不清不要猜。"
                "公开优惠属于content，要求个别让价、退款、发票属于commercial。"
            )},
            {"role": "user", "content": json.dumps({
                "question": question, "page_course_id": page_course_id,
                "profile": profile, "history": history[-6:],
                "courses": [{"id": x.course_id, "title": x.title} for x in catalog],
            }, ensure_ascii=False)},
        ])
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", result.text.strip())
        parsed = ParsedTurn.model_validate_json(raw)
        updates = {}
        for key, value in parsed.profile_updates.items():
            try:
                updates[key] = validate_answer(key, value)
            except ValueError:
                continue
        if not all(isinstance(x, str) and 0 < len(x.strip()) <= 2000 for x in parsed.questions):
            return fallback
        intent = parsed.intent if parsed.intent in {"content", "recommend", "pay", "commercial", "advisor"} else fallback.intent
        # 明确的事实查询不受模型的商业意图猜测影响。
        if fallback.intent == "content" and fact_topic(question):
            intent = "content"
        return Understanding(
            questions=[question] if len(parsed.questions) == 1 else parsed.questions,
            intent=intent,
            course_id=fallback.course_id if reference_locked else parsed.course_id if parsed.course_id in allowed else fallback.course_id,
            profile_updates=updates,
            compare_ids=[x for x in parsed.compare_ids if x in allowed],
            llm_called=True, prompt_tokens=result.usage.prompt_tokens, completion_tokens=result.usage.completion_tokens,
        )
    except Exception as exc:
        _log.warning("turn understanding unavailable (%s); using explicit rules", type(exc).__name__)
        return fallback
