"""Customer-owned website history. Lock the session for all writes and tombstones."""

import json
import re
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.attributes import flag_modified

from backend.config import settings
from backend.domain.website_owner import as_owner
from backend.models import VisitorConsultation, VisitorTurn
from backend.schemas import AskResponse
from backend.services.consultation_access import active_filter, load_owned
from backend.services.website_identity import customer_owner


def now():
    return datetime.now(timezone.utc)


def owned(session, conversation_id, owner, *, lock=False):
    row = load_owned(session, conversation_id, owner, lock=lock)
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


def create(session, owner, request_id):
    previous = session.scalar(
        select(VisitorConsultation).where(
            VisitorConsultation.creation_key == request_id
        )
    )
    if previous:
        return descriptor(owned(session, previous.id, owner))
    row = VisitorConsultation(
        **as_owner(owner).columns(),
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
        return descriptor(owned(session, previous.id, owner))
    return descriptor(row)


def begin_turn(session, conversation_id, owner, request_id, question):
    row = owned(session, conversation_id, owner, lock=True)
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
    session, conversation_id, owner, request_id, question, response, claim_id=None
):
    row = owned(session, conversation_id, owner, lock=True)
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


def abandon_turn(session, conversation_id, owner, request_id, claim_id=None):
    # Preserve completed answers; failed requests can safely retry with the same key.
    try:
        # Internal cleanup can only remove this request's pending claim, never
        # save an answer. Keep ownership/TTL checks even if upstream is now down.
        cleanup_owner = replace(as_owner(owner), revalidate=None)
        row = owned(session, conversation_id, cleanup_owner, lock=True)
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


def listing(session, owner, offset, limit):
    return list(session.scalars(
        select(VisitorConsultation)
        .where(active_filter(owner), VisitorConsultation.widget_session.is_(True))
        .order_by(VisitorConsultation.last_activity_at.desc(), VisitorConsultation.id.desc())
        .offset(offset).limit(limit + 1)
    ))


def rename(session, conversation_id, owner, title):
    row = owned(session, conversation_id, owner, lock=True)
    row.last_activity_at = row.last_activity_at or row.updated_at or row.created_at
    row.title, row.custom_title = title, True
    session.commit()
    return descriptor(row)


def remove(session, conversation_id, owner):
    # Missing, expired, deleted and foreign IDs have the same idempotent outcome.
    row = load_owned(session, conversation_id, owner, lock=True)
    if row is not None and row.widget_session:
        row.deleted_at = now()
        session.commit()


def associate_current(session, identity, visitor_id, conversation_id=None):
    """Called only after real identity verification and signed guest-cookie reading.

    This service owns the transaction. Commit once here, including customer creation;
    all denial paths roll back. Never scan or merge other guest consultations.
    """
    try:
        owner = customer_owner(session, identity)
        if conversation_id is None:
            owner.check_current()
            session.commit()
            return owner, None
        if not visitor_id:
            raise HTTPException(404, "会话不存在或已过期")
        row = session.scalar(select(VisitorConsultation).where(
            VisitorConsultation.id == conversation_id,
        ).with_for_update().execution_options(populate_existing=True))
        owner.check_current()
        if row is None:
            raise HTTPException(404, "会话不存在或已过期")
        if row.customer_id == owner.customer_id and row.source_visitor_id == visitor_id:
            # Replays still require the original signed cookie and active ownership.
            if load_owned(session, row.id, owner) is None:
                raise HTTPException(404, "会话不存在或已过期")
            session.commit()
            return owner, descriptor(row)
        if load_owned(session, row.id, visitor_id) is None:
            raise HTTPException(404, "会话不存在或已过期")
        pending = list(session.scalars(select(VisitorTurn).where(
            VisitorTurn.conversation_id == row.id, VisitorTurn.response_json.is_(None),
        )))
        for turn in pending:
            created = turn.created_at
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            if created >= now() - timedelta(minutes=15):
                raise HTTPException(409, "当前提问仍在处理中，请完成后重试关联")
        for turn in pending:
            session.delete(turn)
        row.source_visitor_id = visitor_id
        row.visitor_id, row.customer_id = None, owner.customer_id
        # Ownership changes must not extend retention, including legacy fallback.
        row.last_activity_at = row.last_activity_at or row.updated_at or row.created_at
        flag_modified(row, "updated_at")
        session.commit()
        return owner, descriptor(row)
    except Exception:
        session.rollback()
        raise
