"""售前一轮问答编排：意图 → 问诊门闸 → 短路 → 公开信息 → RAG → 转人工。

目标优先级（整条主链遵守）：
1. 商业敏感 / 找顾问 → 转人工
2. 付款且已确认课 → 详情/购买引导
3. 有方向且能命中可推荐课 → 直接列课（不进问诊）
4. 无方向 / 命中为空 / 就业类 → 游客问诊
5. 已选课的公开事实 → official_course_drafts；不足则依据不足，本轮不 RAG
6. 其余 → RAG；有 related_courses 不转人工
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, replace
from uuid import UUID

from fastapi import HTTPException

from backend import db
from backend.config import settings
from backend.errors import ServiceUnavailableError, UpstreamServiceError
from backend.models import VisitorConsultation
from backend.schemas import AskRequest, AskResponse, OwnerInfo, RelatedCourse
from backend.services.approved_courses import (
    get_approved_course,
    load_recommendable_courses,
)
from backend.services.consultation_service import (
    FIELDS,
    QUESTIONS,
    dialogue_history,
    get_or_create_dialogue,
    load_owned,
    present,
    remember_turn,
)
from backend.services.conversation_service import ConversationNotFoundError
from backend.services.course_catalog_service import OfficialCourse, search_related_courses
from backend.services.handoff_service import resolve_handoff
from backend.services.intent_router import (
    Intent,
    classify_intent,
    handle_routed_turn,
    recommend_has_direction,
    should_enter_guest_consultation,
)
from backend.services.profile_extraction import extract_profile_updates, looks_like_profile
from backend.services.public_course_info import (
    ANSWER_PUBLIC_INSUFFICIENT,
    answer_public_question,
    public_fact_topic,
)
from backend.services.qa_service import AskResult, answer_question
from backend.services.course_facts import answer_course_fact
from backend.services.turn_understanding import Understanding, understand_turn
from backend.services.handoff_summary import build_handoff_summary
from backend.services.topic_owner_service import is_usable_contact

_log = logging.getLogger("backend.ask_orchestrator")


@dataclass(frozen=True)
class AskIdentity:
    allowed_spaces: list[str]
    user_id: str | None
    user_role: str | None
    visitor_id: str | None


def related_course_card(
    course: OfficialCourse,
    *,
    purchase_url: str | None = None,
) -> RelatedCourse:
    """官网详情链接与封面；购买链仅审核通过后才填。"""
    return RelatedCourse(
        id=course.course_id,
        title=course.title,
        description=course.description or None,
        purchase_url=purchase_url,
        source_url=f"https://www.arborseek.com/course/{course.course_id}",
        cover_url=course.cover_url,
    )


def to_response(
    result: AskResult,
    related: list[RelatedCourse] | None = None,
    *,
    intent: str | None = None,
) -> AskResponse:
    return AskResponse(
        answer=result.answer,
        hit=result.hit,
        sources=result.sources,
        conversation_id=result.conversation_id,
        owner=result.owner,
        related_courses=related or [],
        intent=intent,
        error_type=result.error_type,
        llm_called=result.llm_called,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
    )


def course_context_for_content(
    question: str, course_id: str | None
) -> tuple[str | None, list[RelatedCourse]]:
    """内容问答：已指定课程则沿用；未指定时用可推荐列表辅助。"""
    explicit = (course_id or "").strip()
    if explicit:
        return explicit, []
    matches = search_related_courses(question, courses=load_recommendable_courses())
    related = [related_course_card(item) for item in matches]
    resolved = matches[0].course_id if matches else None
    return resolved, related


def apply_handoff(
    result: AskResult,
    *,
    question: str,
    course_id: str | None,
    related_courses: list[RelatedCourse] | None = None,
) -> AskResult:
    """未命中时补转人工；已匹配课程则不转。不落工单。"""
    if result.hit:
        return result
    if related_courses:
        return result

    handoff = resolve_handoff(question=question, course_id=course_id)
    answer = result.answer
    if handoff.owner.configured and settings.handoff_miss_answer:
        answer = settings.handoff_miss_answer

    return replace(result, answer=answer, owner=handoff.owner)


def _prepare_guest_dialogue(
    visitor_id: str, payload: AskRequest, *, intent: Intent, understanding: Understanding | None = None
) -> tuple[str, list[tuple[str, str]], dict | None, str | None]:
    db.init_engine()
    if db.SessionLocal is None:
        raise ServiceUnavailableError("数据库会话未初始化")
    with db.SessionLocal() as session:
        # 无方向开场（默认问题）一律新开问诊：访客 cookie 跨重启仍在，
        # 若复用旧 VisitorConsultation 会带着旧 goal 直接荐课。
        fresh_undirected = (
            intent is Intent.recommend and not recommend_has_direction(payload.question)
        )
        if fresh_undirected:
            row = VisitorConsultation(
                visitor_id=visitor_id,
                course_id=payload.course_id,
                profile_json="{}",
                history_json="[]",
            )
            session.add(row)
            session.flush()
        else:
            try:
                row = get_or_create_dialogue(
                    session,
                    visitor_id,
                    payload.course_id,
                    str(payload.conversation_id) if payload.conversation_id else None,
                )
            except ValueError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
        history = dialogue_history(row)
        profile = json.loads(row.profile_json)
        pending = profile.get("_pending_field")
        if not pending and history and history[-1][0] == "assistant":
            pending = next(
                (
                    field
                    for field, question in QUESTIONS.items()
                    if history[-1][1].endswith(question)
                ),
                None,
            )
        updates = understanding.profile_updates.copy() if understanding else extract_profile_updates(payload.question, profile, pending, use_model=False)
        if understanding and understanding.course_id:
            profile["_selected_course_id"] = understanding.course_id
        selection = should_enter_guest_consultation(
            intent,
            payload.question,
            pending_field=pending,
            looks_like_profile_reply=looks_like_profile(payload.question, pending) or (
                bool(updates) and not re.search(r"[？?]|吗|什么|怎么|多少|多久|能否", payload.question)
            ),
        )
        preview = None
        if selection:
            # 无方向开场不应把开场句写成 goal。
            if fresh_undirected:
                updates.pop("goal", None)
                for key in FIELDS:
                    profile.pop(key, None)
            profile.update(updates)
            row.profile_json = json.dumps(profile, ensure_ascii=False)
            preview = present(session, row)
            preview["updates"] = updates
            profile["_pending_field"] = preview["next_field"]
            recommendations = preview["recommendations"]
            profile["_selected_course_id"] = (
                recommendations[0]["id"] if len(recommendations) == 1 else None
            )
        else:
            # 课程事实 / 有方向列课等会离开问诊槽位，避免下一轮误吃短答。
            profile.pop("_pending_field", None)
            profile.update(updates)
        row.profile_json = json.dumps(profile, ensure_ascii=False)
        session.commit()
        return (
            row.id,
            history,
            preview,
            profile.get("_selected_course_id") or payload.course_id,
        )


def _remember_guest_dialogue(
    visitor_id: str, dialogue_id: str, question: str, answer: str
) -> None:
    if db.SessionLocal is None:
        return
    with db.SessionLocal() as session:
        row = load_owned(session, dialogue_id, visitor_id)
        if row is not None:
            remember_turn(session, row, question, answer)


def _bind_selected_course(
    visitor_id: str, dialogue_id: str, course_id: str | None
) -> None:
    """把本轮唯一匹配的课写入游客会话，供后续「这个课 / 优惠 / 付款」沿用。"""
    key = (course_id or "").strip()
    if not key or db.SessionLocal is None:
        return
    with db.SessionLocal() as session:
        row = load_owned(session, dialogue_id, visitor_id)
        if row is None:
            return
        profile = json.loads(row.profile_json or "{}")
        if profile.get("_selected_course_id") == key:
            return
        profile["_selected_course_id"] = key
        row.profile_json = json.dumps(profile, ensure_ascii=False)
        session.commit()


def _course_id_to_bind(
    *,
    related: list[RelatedCourse] | tuple[RelatedCourse, ...],
    routed_course_id: str | None = None,
    resolved_course_id: str | None = None,
) -> str | None:
    """仅在唯一课卡或显式解析出单课时绑定，避免多候选误锁。"""
    if len(related) == 1:
        return related[0].id
    explicit = (routed_course_id or resolved_course_id or "").strip()
    return explicit or None


def _selection_response(preview: dict) -> tuple[AskResult, list[RelatedCourse]]:
    updates = preview.get("updates", {})
    acknowledgement = ""
    if "hardware" in updates:
        acknowledgement = {
            "no": "你目前没有练习硬件。",
            "yes": "你已有练习硬件。",
            "unknown": "硬件条件暂不确定。",
        }[updates["hardware"]]
    elif "basis" in updates:
        acknowledgement = {
            "none": "你目前是零基础。",
            "basic": "你已有一些编程或机器人基础。",
            "experienced": "你已有项目实践经验。",
        }[updates["basis"]]
    if preview["status"] == "collecting":
        return (
            AskResult(
                answer=f"{acknowledgement}{preview['question']}",
                hit=False,
                sources=[],
            ),
            [],
        )
    if preview["status"] == "recommended":
        related = [
            RelatedCourse(
                id=item["id"],
                title=item["title"],
                purchase_url=item.get("purchase_url"),
                source_url=item["source_url"],
                reason=item["reason"],
            )
            for item in preview["recommendations"]
        ]
        reasons = "\n".join(
            f"{item['title']}：{item['reason']}" for item in preview["recommendations"]
        )
        followup = (
            f"如果方便，也可以补充：{preview['question']}"
            if preview["question"]
            else "你可以继续问课程内容、学习方式，或查看官网详情。"
        )
        return (
            AskResult(
                answer=f"{acknowledgement}{reasons}\n\n{followup}",
                hit=False,
                sources=[],
            ),
            related,
        )
    if preview["status"] == "no_match":
        return (
            AskResult(
                answer=(
                    "目前可推荐课程里没有找到符合这个目标或已知学习条件的课程。"
                    "你也可以告诉我希望完成的具体任务，我再帮你缩小范围。"
                ),
                hit=False,
                sources=[],
            ),
            [],
        )
    owner = preview.get("owner")
    return (
        AskResult(
            answer="目前没有足够依据推荐课程，建议请课程顾问进一步确认。",
            hit=False,
            sources=[],
            owner=OwnerInfo.model_validate(owner) if owner else None,
        ),
        [],
    )


def _enrich_related(related: list[RelatedCourse]) -> list[RelatedCourse]:
    """补全详情链接、审核购买页与封面。"""
    enriched: list[RelatedCourse] = []
    for item in related[:3]:
        approved = get_approved_course(item.id)
        official = next(
            (
                course
                for course in load_recommendable_courses()
                if course.course_id == item.id
            ),
            None,
        )
        requirements, pending = list(item.requirements), list(item.pending)
        for query in ("基础要求", "硬件要求", "观看期限"):
            fact = answer_course_fact(query, item.id)
            if fact:
                if any(source["status"] in {"unknown", "conflict"} for source in fact[1]):
                    pending.append(f"{query}：{fact[0][:300]}")
                elif query != "观看期限":
                    requirements.append(f"{query}：{fact[0][:400]}")
        if not approved:
            pending.append("销售审核尚未完成，购买入口暂不开放。")
        enriched.append(
            RelatedCourse(
                id=item.id,
                title=item.title,
                description=item.description
                or (official.description if official else None),
                purchase_url=item.purchase_url
                or (approved.purchase_url if approved else None),
                source_url=item.source_url
                or f"https://www.arborseek.com/course/{item.id}",
                cover_url=item.cover_url
                or (official.cover_url if official else None),
                reason=item.reason or ("与当前咨询方向相关，依据官网课程介绍。" if official else None),
                requirements=list(dict.fromkeys(requirements)),
                pending=list(dict.fromkeys(pending)),
            )
        )
    return enriched


def run_ask_turn(payload: AskRequest, identity: AskIdentity) -> AskResponse:
    return next(data for name, data in iter_ask_turn(payload, identity) if name == "final")


def iter_ask_turn(payload: AskRequest, identity: AskIdentity):
    """每轮只解析一次，统一保存历史、候选顺序和本次理解的模型用量。"""
    profile, history = {}, []
    if identity.visitor_id and payload.conversation_id:
        db.init_engine()
        with db.SessionLocal() as session:
            row = load_owned(session, str(payload.conversation_id), identity.visitor_id)
            if row is None:
                raise HTTPException(status_code=404, detail="会话不存在或已过期")
            profile, history = json.loads(row.profile_json), dialogue_history(row)
            if not profile.get("_pending_field") and history and history[-1][0] == "assistant":
                profile["_pending_field"] = next((field for field, question in QUESTIONS.items() if history[-1][1].endswith(question)), None)
    understanding = understand_turn(payload.question, page_course_id=payload.course_id,
                                    profile=profile, history=history, catalog=load_recommendable_courses())
    if len(understanding.compare_ids) >= 2:
        dialogue_id = None
        if identity.visitor_id:
            dialogue_id, _, _, _ = _prepare_guest_dialogue(identity.visitor_id, payload, intent=Intent.content, understanding=understanding)
        cards, blocks, evidence = [], [], []
        catalog = {item.course_id: item for item in load_recommendable_courses()}
        for key in understanding.compare_ids:
            if key not in catalog:
                continue
            course = catalog[key]
            cards.append(related_course_card(course))
            lines = [f"「{course.title}」"]
            for query in ("课程目录", "基础要求", "硬件要求"):
                fact = answer_course_fact(query, key)
                if fact:
                    lines.append(f"{query}：{fact[0][:400]}")
                    evidence.extend(fact[1])
            blocks.append("\n".join(lines))
        response = AskResponse(answer="\n\n".join(blocks) or "请先选定需要比较的课程。",
                               hit=bool(evidence), related_courses=_enrich_related(cards), fact_sources=evidence,
                               conversation_id=UUID(dialogue_id) if dialogue_id else None, intent="compare")
    else:
        for name, data in _run_questions(payload, identity, understanding):
            if name == "final":
                response = data
            else:
                yield name, data
    response.llm_called = response.llm_called or understanding.llm_called
    response.prompt_tokens += understanding.prompt_tokens
    response.completion_tokens += understanding.completion_tokens
    if is_usable_contact(settings.handoff_fallback_contact):
        response.fallback_contact = settings.handoff_fallback_contact
    if identity.visitor_id and response.conversation_id:
        key = str(response.conversation_id)
        _remember_guest_dialogue(identity.visitor_id, key, payload.question, response.answer)
        with db.SessionLocal() as session:
            row = load_owned(session, key, identity.visitor_id)
            if row:
                saved = json.loads(row.profile_json)
                if response.related_courses and response.intent in {"recommend", "compare"}:
                    saved["_candidate_course_ids"] = [item.id for item in response.related_courses]
                    row.profile_json = json.dumps(saved, ensure_ascii=False)
                    session.commit()
                if response.owner:
                    response.handoff_summary = build_handoff_summary(
                        profile=saved, course_id=saved.get("_selected_course_id") or payload.course_id,
                        candidates=saved.get("_candidate_course_ids", []), question=payload.question,
                    )
    elif response.owner:
        response.handoff_summary = build_handoff_summary(profile={}, course_id=payload.course_id,
                                                        candidates=[x.id for x in response.related_courses], question=payload.question)
    yield "final", response


def _run_questions(payload: AskRequest, identity: AskIdentity, understanding: Understanding):
    questions = understanding.questions
    if len(questions) == 1:
        yield "final", _run_single_question(payload.model_copy(update={"question": questions[0]}), identity, record_history=False, understanding=understanding)
        return

    responses: list[AskResponse] = []
    failures: list[HTTPException] = []
    conversation_id = payload.conversation_id
    for question in questions:
        part = payload.model_copy(update={
            "question": question, "conversation_id": conversation_id,
        })
        try:
            result = _run_single_question(
                part, identity, record_history=False, context_question=payload.question,
                understanding=understanding,
            )
        except HTTPException as exc:
            if exc.status_code not in {502, 503}:
                raise
            failures.append(exc)
            result = AskResponse(
                answer="这项查询暂时不可用，请稍后重试。",
                hit=False,
                error_type="upstream_error" if exc.status_code == 502 else "service_unavailable",
            )
        conversation_id = result.conversation_id or conversation_id
        responses.append(result)
        yield "part", {"index": len(responses), "question": question, **result.model_dump(mode="json")}

    if len(failures) == len(questions):
        raise failures[0]

    owners = [result.owner for result in responses if result.owner is not None]
    response = AskResponse(
        answer="\n\n".join(
            f"{index}. {question}\n{result.answer}"
            for index, (question, result) in enumerate(zip(questions, responses), 1)
        ),
        hit=any(result.hit is True for result in responses),
        sources=list({
            (source.document_id, source.snippet): source
            for result in responses for source in result.sources
        }.values()),
        related_courses=list({
            item.id: item for result in responses for item in result.related_courses
        }.values())[:3],
        owner=next((owner for owner in owners if owner.configured), owners[0] if owners else None),
        conversation_id=conversation_id,
        intent="multi_question",
        error_type=next((result.error_type for result in responses if result.error_type), None),
        llm_called=any(result.llm_called for result in responses),
        prompt_tokens=sum(result.prompt_tokens for result in responses),
        completion_tokens=sum(result.completion_tokens for result in responses),
        fact_sources=[source for result in responses for source in result.fact_sources],
    )
    yield "final", response


def _run_single_question(
    payload: AskRequest, identity: AskIdentity, *, record_history: bool = True,
    context_question: str | None = None,
    understanding: Understanding | None = None,
) -> AskResponse:
    """执行一个问题；拆分出的问答由调用方合并后保存访客历史。"""
    allowed_spaces = identity.allowed_spaces
    user_id = identity.user_id
    user_role = identity.user_role
    visitor_id = identity.visitor_id

    intent = classify_intent(payload.question)
    if intent is Intent.content and understanding and len(understanding.questions) == 1:
        intent = Intent(understanding.intent)
    dialogue_id: str | None = None
    visitor_history: list[tuple[str, str]] = []
    dialogue_course_id = payload.course_id

    if user_id is None and visitor_id:
        try:
            dialogue_id, visitor_history, preview, dialogue_course_id = (
                _prepare_guest_dialogue(visitor_id, payload, intent=intent, understanding=understanding)
            )
        except ServiceUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        if preview is not None:
            result, related = _selection_response(preview)
            if record_history:
                _remember_guest_dialogue(
                    visitor_id, dialogue_id, payload.question, result.answer
                )
            bind_id = _course_id_to_bind(related=related)
            if bind_id:
                _bind_selected_course(visitor_id, dialogue_id, bind_id)
            return to_response(
                replace(result, conversation_id=UUID(dialogue_id)),
                _enrich_related(related),
                intent=Intent.recommend.value,
            )

    if context_question and not dialogue_course_id:
        matches = search_related_courses(
            context_question, courses=load_recommendable_courses()
        )
        if len(matches) == 1:
            dialogue_course_id = matches[0].course_id
            if dialogue_id and visitor_id:
                _bind_selected_course(visitor_id, dialogue_id, dialogue_course_id)

    routed = handle_routed_turn(payload.question, course_id=dialogue_course_id,
                                intent_override=understanding.intent if understanding and len(understanding.questions) == 1 else None)
    if routed.handled:
        _log.info("ask short-circuit intent=%s", routed.intent.value)
        result = routed.result
        related = list(routed.related_courses)
        if dialogue_id and visitor_id:
            if record_history:
                _remember_guest_dialogue(
                    visitor_id, dialogue_id, payload.question, result.answer
                )
            bind_id = _course_id_to_bind(
                related=related, routed_course_id=routed.course_id
            )
            # 推荐列课唯一命中时写入会话；付款/顾问短路沿用已绑定课。
            if routed.intent is Intent.recommend and bind_id:
                _bind_selected_course(visitor_id, dialogue_id, bind_id)
            result = replace(result, conversation_id=UUID(dialogue_id))
        return to_response(
            result,
            _enrich_related(related),
            intent=routed.intent.value,
        )

    course_id, related = course_context_for_content(
        payload.question, dialogue_course_id
    )
    if (
        dialogue_id
        and visitor_id
        and course_id
        and not dialogue_course_id
        and re.search(r"这门课|这个课|该课", payload.question or "")
    ):
        _bind_selected_course(visitor_id, dialogue_id, course_id)
        dialogue_course_id = course_id

    official = next(
        (
            item
            for item in load_recommendable_courses()
            if item.course_id == course_id
        ),
        None,
    )
    if official is None and course_id:
        from backend.services.course_catalog_service import get_course_by_id

        official = get_course_by_id(course_id)

    topic = public_fact_topic(payload.question)
    fact = answer_course_fact(payload.question, course_id) if course_id else None
    if fact is not None:
        answer, evidence = fact
        if dialogue_id and visitor_id and record_history:
            _remember_guest_dialogue(visitor_id, dialogue_id, payload.question, answer)
        return AskResponse(
            answer=answer, hit=bool(evidence) and all(x["status"] not in {"unknown", "conflict"} for x in evidence),
            fact_sources=evidence, conversation_id=UUID(dialogue_id) if dialogue_id else None,
            related_courses=_enrich_related([related_course_card(official)]) if official else [],
            intent="course_info",
        )
    if official and topic:
        public_answer = answer_public_question(payload.question, official)
        answered = public_answer is not None
        result = AskResult(
            answer=public_answer or ANSWER_PUBLIC_INSUFFICIENT,
            hit=answered,
            sources=[],
        )
        card = [related_course_card(official)]
        if dialogue_id and visitor_id:
            if record_history:
                _remember_guest_dialogue(
                    visitor_id, dialogue_id, payload.question, result.answer
                )
            _bind_selected_course(visitor_id, dialogue_id, official.course_id)
            result = replace(result, conversation_id=UUID(dialogue_id))
        return to_response(result, _enrich_related(card), intent="course_info")

    try:
        result = answer_question(
            allowed_spaces=allowed_spaces,
            question=payload.question,
            user_id=user_id,
            user_role=user_role,
            conversation_id=payload.conversation_id if user_id is not None else None,
            course_id=course_id,
            visitor_history=visitor_history if user_id is None else None,
        )
        result = apply_handoff(
            result,
            question=payload.question,
            course_id=course_id,
            related_courses=related,
        )
    except HTTPException:
        raise
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ServiceUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except UpstreamServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="问答处理失败") from exc

    if dialogue_id and visitor_id:
        if record_history:
            _remember_guest_dialogue(
                visitor_id, dialogue_id, payload.question, result.answer
            )
        if course_id and len(related) <= 1:
            _bind_selected_course(visitor_id, dialogue_id, course_id)
        result = replace(result, conversation_id=UUID(dialogue_id))
    return to_response(
        result, _enrich_related(related), intent=Intent.content.value
    )
