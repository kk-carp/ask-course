"""Customer-owned website history. Lock the session for all writes and tombstones."""

import json
import re
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from backend.config import settings
from backend.models import VisitorConsultation, VisitorTurn
from backend.schemas import AskResponse
from backend.services.consultation_service import load_owned


def now():
    return datetime.now(timezone.utc)


def owned(session, conversation_id, visitor_id, *, lock=False):
    if lock:
        # Refresh identities after acquiring a lock (a concurrent delete may have committed).
        session.scalar(
            select(VisitorConsultation)
            .where(VisitorConsultation.id == conversation_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    row = load_owned(session, conversation_id, visitor_id)
    if row is None or not row.widget_session:
        raise HTTPException(404, "会话不存在或已过期")
    return row


def descriptor(row):
    return {
        "id": row.id,
        "title": row.title,
        "custom_title": row.custom_title,
        "last_activity_at": row.last_activity_at,
        "course_id": row.course_id,
    }


def create(session, visitor_id, request_id):
    previous = session.scalar(
        select(VisitorConsultation).where(
            VisitorConsultation.creation_key == request_id
        )
    )
    if previous:
        return descriptor(owned(session, previous.id, visitor_id))
    row = VisitorConsultation(
        visitor_id=visitor_id,
        widget_session=True,
        creation_key=request_id,
        last_activity_at=now(),
    )
    session.add(row)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        previous = session.scalar(
            select(VisitorConsultation).where(
                VisitorConsultation.creation_key == request_id
            )
        )
        if previous is None:
            raise
        return descriptor(owned(session, previous.id, visitor_id))
    return descriptor(row)


def begin_turn(session, conversation_id, visitor_id, request_id, question):
    row = owned(session, conversation_id, visitor_id, lock=True)
    pending = list(
        session.scalars(
            select(VisitorTurn).where(
                VisitorTurn.conversation_id == row.id,
                VisitorTurn.response_json.is_(None),
            )
        )
    )
    for turn in list(pending):
        created = (
            turn.created_at.replace(tzinfo=timezone.utc)
            if turn.created_at.tzinfo is None
            else turn.created_at
        )
        if turn.response_json is None and created < now() - timedelta(minutes=15):
            session.delete(turn)
            pending.remove(turn)
    session.flush()
    existing = session.scalar(
        select(VisitorTurn).where(
            VisitorTurn.conversation_id == row.id, VisitorTurn.request_id == request_id
        )
    )
    if existing:
        if existing.question != question:
            raise HTTPException(409, "请求编号已用于其他问题")
        if existing.response_json:
            return AskResponse.model_validate_json(existing.response_json), False, None
        raise HTTPException(409, "本次提问仍在处理中，请稍后重试")
    if pending:
        raise HTTPException(409, "请等待上一条问题完成")
    record = VisitorTurn(
        conversation_id=row.id, request_id=request_id, question=question
    )
    session.add(record)
    row.last_activity_at = now()
    first = (
        session.scalar(
            select(func.count())
            .select_from(VisitorTurn)
            .where(
                VisitorTurn.conversation_id == row.id,
                VisitorTurn.response_json.is_not(None),
            )
        )
        == 0
    )
    session.commit()
    return None, first, record.id


def finish_turn(
    session, conversation_id, visitor_id, request_id, question, response, claim_id=None
):
    row = owned(session, conversation_id, visitor_id, lock=True)
    turn = session.scalar(
        select(VisitorTurn).where(
            VisitorTurn.conversation_id == row.id, VisitorTurn.request_id == request_id
        )
    )
    if turn is None or (claim_id is not None and turn.id != claim_id):
        raise HTTPException(409, "本次提问已取消")
    if turn.response_json:
        return
    turn.response_json = response.model_dump_json()
    history = json.loads(row.history_json or "[]")
    history.extend(
        [
            {"role": "user", "content": question},
            {"role": "assistant", "content": response.answer},
        ]
    )
    row.history_json = json.dumps(history[-6:], ensure_ascii=False)
    row.last_activity_at = now()
    if not row.custom_title:
        text = " ".join(item["content"] for item in history if item["role"] == "user")
        subject = next(
            (
                label
                for pattern, label in (
                    (r"四足|机器狗", "四足机器人"),
                    (r"机械臂|抓取", "智能机械臂"),
                    (r"大模型|人工智能|\bAI\b", "AI 大模型"),
                )
                if re.search(pattern, text, re.IGNORECASE)
            ),
            "",
        )
        topics = [
            label
            for pattern, label in (
                (r"推荐|选课|适合", "选课建议"),
                (r"基础|入门", "学习基础"),
                (r"硬件|设备|电脑", "设备要求"),
                (r"价格|多少钱|费用", "课程费用"),
                (r"目录|内容|项目|学什么", "课程内容"),
                (r"顾问|人工|联系", "顾问咨询"),
            )
            if re.search(pattern, text)
        ][:2]
        title = (subject + "：" if subject and topics else subject) + "与".join(topics)
        row.title = (title or re.sub(r"\s+", " ", question).strip())[:26] or "课程咨询"
    session.commit()


def abandon_turn(session, conversation_id, visitor_id, request_id, claim_id=None):
    # Preserve completed answers; failed requests can safely retry with the same key.
    try:
        row = owned(session, conversation_id, visitor_id, lock=True)
    except HTTPException:
        session.rollback()
        return
    turn = session.scalar(
        select(VisitorTurn).where(
            VisitorTurn.conversation_id == row.id, VisitorTurn.request_id == request_id
        )
    )
    if (
        turn
        and turn.response_json is None
        and (claim_id is None or turn.id == claim_id)
    ):
        session.delete(turn)
        session.commit()


def cutoff():
    return now() - timedelta(hours=settings.visitor_consultation_hours)
