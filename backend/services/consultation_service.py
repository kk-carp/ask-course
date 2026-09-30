"""售前问诊状态机；未完成购买审核的课程只展示官网事实，不生成购买入口。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.config import settings
from backend.models import VisitorConsultation
from backend.services.approved_courses import (
    basis_level,
    load_approved_courses,
    load_recommendable_courses,
)
from backend.services.course_catalog_service import search_related_courses
from backend.services.handoff_service import resolve_handoff

FIELDS = ("goal", "basis", "hardware", "weekly_hours")
QUESTIONS = {
    "goal": "你主要想通过课程完成什么？例如学习 ROS、机器人巡检或机械臂操作。",
    "basis": "你目前的编程和机器人基础如何？",
    "hardware": "你有可用于练习的机器人硬件吗？",
    "weekly_hours": "每周大约能投入多少小时？",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _expired(row: VisitorConsultation) -> bool:
    updated = row.updated_at or row.created_at or _now()
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    return updated < _now() - timedelta(hours=settings.visitor_consultation_hours)


def load_owned(
    session: Session, consultation_id: str, visitor_id: str
) -> VisitorConsultation | None:
    row = session.scalar(
        select(VisitorConsultation).where(
            VisitorConsultation.id == consultation_id,
            VisitorConsultation.visitor_id == visitor_id,
        )
    )
    return row if row is not None and not _expired(row) else None


def get_or_create_dialogue(
    session: Session, visitor_id: str, course_id: str | None,
    conversation_id: str | None = None,
) -> VisitorConsultation:
    """自由问答与问诊复用访客状态；指定 ID 校验归属和有效期，支持跨页面。"""
    if conversation_id:
        row = load_owned(session, conversation_id, visitor_id)
        if row is None:
            raise ValueError("会话不存在或已过期")
        return row
    row = session.scalar(
        select(VisitorConsultation)
        .where(
            VisitorConsultation.visitor_id == visitor_id,
            VisitorConsultation.course_id == course_id,
        )
        .order_by(VisitorConsultation.updated_at.desc(), VisitorConsultation.created_at.desc())
        .limit(1)
    )
    if row is not None and not _expired(row):
        return row
    row = VisitorConsultation(visitor_id=visitor_id, course_id=course_id, profile_json="{}", history_json="[]")
    session.add(row)
    session.flush()
    return row


def dialogue_history(row: VisitorConsultation) -> list[tuple[str, str]]:
    return [(item["role"], item["content"]) for item in json.loads(row.history_json or "[]")]


def remember_turn(session: Session, row: VisitorConsultation, question: str, answer_text: str) -> None:
    history = json.loads(row.history_json or "[]")
    history.extend((
        {"role": "user", "content": question},
        {"role": "assistant", "content": answer_text},
    ))
    row.history_json = json.dumps(history[-6:], ensure_ascii=False)
    row.updated_at = _now()
    session.commit()


def validate_answer(field: str, value: object) -> object:
    if field == "goal":
        if not isinstance(value, str) or not 2 <= len(value.strip()) <= 200:
            raise ValueError("学习目标须为 2–200 字。")
        return value.strip()
    if field == "basis" and isinstance(value, str) and value in {"none", "basic", "experienced"}:
        return value
    if field == "hardware" and isinstance(value, str) and value in {"yes", "no", "unknown"}:
        return value
    if field == "weekly_hours" and type(value) is int and 1 <= value <= 80:
        return value
    raise ValueError("问诊答案不在允许范围内。")


def _recommend(profile: dict, course_id: str | None) -> list[dict]:
    goal = profile["goal"].casefold()
    ranked: list[tuple[float, str, dict]] = []
    approved = load_approved_courses()
    for item in approved:
        if "basis" in profile and basis_level(profile["basis"]) < basis_level(item.min_basis):
            continue
        if item.requires_hardware and profile.get("hardware") in {"no", "unknown"}:
            continue
        if "weekly_hours" in profile and profile["weekly_hours"] < item.min_weekly_hours:
            continue
        matched = [word for word in item.goal_keywords if word.casefold() in goal]
        if not matched:
            continue
        missing = []
        if item.min_basis != "none" and "basis" not in profile:
            missing.append("basis")
        if item.requires_hardware and "hardware" not in profile:
            missing.append("hardware")
        if "weekly_hours" not in profile:
            missing.append("weekly_hours")
        score = len(matched) + (0.1 if item.id == course_id else 0)
        reason = (
            f"你想了解「{matched[0]}」，这门课的学习目标包括：{item.goals[0]}。"
            f"基础要求：{item.prerequisites}；建议每周至少投入 {item.min_weekly_hours} 小时。"
        )
        if item.requires_hardware:
            reason += "需要可用于练习的机器人硬件。"
        ranked.append(
            (
                score,
                item.id,
                {
                    "id": item.id,
                    "title": item.title,
                    "reason": reason,
                    "audience": item.audience,
                    "prerequisites": item.prerequisites,
                    "purchase_url": item.purchase_url,
                    "source_url": item.source_url,
                    "missing_fields": missing,
                },
            )
        )
    ranked.sort(key=lambda row: (-row[0], row[1]))
    recommendations = [entry for _, _, entry in ranked[:3]]
    # 已知不符合要求的课程不能从官网简介分支重新进入推荐。
    selected = {item.id for item in approved}
    candidates = search_related_courses(
        profile["goal"], courses=load_recommendable_courses()
    )
    for item in candidates:
        if len(recommendations) == 3:
            break
        if item.course_id in selected:
            continue
        recommendations.append({
            "id": item.course_id,
            "title": item.title,
            "reason": (
                f"这门课与你的学习方向相关。官网介绍：{item.description or item.title}"
                "\n目前的公开资料不足以确认个人适配条件，可以先了解课程内容和学习方式。"
            ),
            "audience": "",
            "prerequisites": "",
            "purchase_url": None,
            "source_url": f"https://www.arborseek.com/course/{item.course_id}",
            # 官网简介无法证明硬件门槛；先给相关课程，再让访客自愿补充条件。
            "missing_fields": ["hardware"] if (
                "hardware" not in profile
                and any(word in item.title for word in ("机器人", "机械臂", "四足"))
            ) else [],
        })
        selected.add(item.course_id)
    return recommendations


def present(session: Session, row: VisitorConsultation) -> dict:
    profile = {key: value for key, value in json.loads(row.profile_json).items() if key in FIELDS}
    next_field = "goal" if "goal" not in profile else None
    recommendations: list[dict] = []
    owner = None
    status = "collecting"
    enterprise = "goal" in profile and any(
        word in profile["goal"]
        for word in ("企业定制", "公司定制", "团队培训", "对公培训")
    )
    if enterprise:
        status = "handoff"
    elif "goal" in profile:
        recommendations = _recommend(profile, row.course_id)
        if recommendations:
            status = "recommended"
            missing = recommendations[0]["missing_fields"]
            next_field = missing[0] if missing else None
        elif row.course_id and all(field in profile for field in ("goal", "basis", "hardware", "weekly_hours")):
            # 指定课程页上画像已齐但仍不匹配 → 转顾问，避免空推荐。
            status = "handoff"
            next_field = None
        else:
            status = "no_match"
            next_field = "goal"
    if status == "handoff":
        resolved = resolve_handoff(
            question=profile.get("goal", "选课咨询"),
            course_id=row.course_id,
            session=session,
        )
        owner = resolved.owner.model_dump(mode="json")
    summary = None
    if status == "handoff":
        basis_label = {"none": "零基础", "basic": "有基础", "experienced": "有项目经验"}.get(
            profile.get("basis"), "未填写"
        )
        hardware_label = {"yes": "有", "no": "没有", "unknown": "暂不确定"}.get(
            profile.get("hardware"), "未填写"
        )
        weekly_hours = profile.get("weekly_hours")
        summary = "\n".join(
            [
                "课程咨询摘要",
                f"当前课程：{row.course_id or '尚未选择'}",
                f"学习目标：{profile.get('goal', '未填写')}",
                f"现有基础：{basis_label}",
                f"练习硬件：{hardware_label}",
                f"每周投入：{weekly_hours} 小时" if weekly_hours is not None else "每周投入：未填写",
            ]
        )
    return {
        "id": row.id,
        "course_id": row.course_id,
        "status": status,
        "profile": profile,
        "next_field": next_field if status != "handoff" else None,
        "question": QUESTIONS[next_field] if next_field and status != "handoff" else None,
        "recommendations": recommendations,
        "owner": owner,
        "summary": summary,
    }


def start(session: Session, visitor_id: str, course_id: str | None, known_profile: dict | None = None) -> dict:
    profile = {field: validate_answer(field, value) for field, value in (known_profile or {}).items()}
    row = VisitorConsultation(visitor_id=visitor_id, course_id=course_id, profile_json=json.dumps(profile, ensure_ascii=False))
    session.add(row)
    session.commit()
    session.refresh(row)
    return present(session, row)


def answer(
    session: Session, row: VisitorConsultation, field: str, value: object
) -> dict:
    profile = json.loads(row.profile_json)
    if field not in FIELDS:
        raise ValueError("未知的选课信息字段。")
    profile[field] = validate_answer(field, value)
    row.profile_json = json.dumps(profile, ensure_ascii=False)
    row.updated_at = _now()
    session.commit()
    session.refresh(row)
    return present(session, row)
