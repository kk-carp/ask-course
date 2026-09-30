"""未命中转人工：接到现有售前承接点（企微二维码），不落工单。

复用：
1. `topic_owners` —— 「课程 → 售前人员/企微活码」
2. 官网课程详情 `pre_sale_service_qrcode`

路由优先级：
1. 数字课程 ID 读官网详情；
2. 本地 `topic_owners` 精确映射；
3. 未指定课程时才按问题文本关键词匹配；
4. 兜底码（未配置则 `configured=false`）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from backend import db
from backend.config import settings
from backend.errors import ServiceUnavailableError
from backend.models import TopicOwner
from backend.schemas import OwnerInfo
from backend.services.course_qr_service import lookup_official_presale
from backend.services.topic_owner_service import (
    UNCONFIGURED_OWNER,
    is_usable_contact,
    match_owner_for_question,
)

_log = logging.getLogger("backend.handoff")

CHANNEL_SITE_WIDGET = "site_widget"
CHANNEL_COURSE_PAGE = "course_page"
CHANNEL_INTERNAL_TOOL = "internal_tool"


@dataclass(frozen=True)
class HandoffResult:
    """转人工结果；`owner` 复用 OwnerInfo，前端契约不变。"""

    owner: OwnerInfo
    route: str  # course_api | course_id | keyword | fallback | none


def _ensure_session_factory():
    db.init_engine()
    if db.SessionLocal is None:
        raise ServiceUnavailableError("数据库会话未初始化")
    return db.SessionLocal


def _match_by_course_id(session: Session, course_id: str) -> OwnerInfo:
    key = (course_id or "").strip()
    if not key:
        return UNCONFIGURED_OWNER
    row = session.get(TopicOwner, key)
    if row is None or not is_usable_contact(row.contact):
        return UNCONFIGURED_OWNER
    return OwnerInfo(
        configured=True,
        topic_key=row.topic_key,
        topic_name=row.topic_name,
        name=row.owner_name,
        contact=row.contact,
    )


def _match_by_keyword(session: Session, question: str) -> OwnerInfo:
    return match_owner_for_question(session, question)


def _fallback_owner() -> OwnerInfo:
    contact = (settings.handoff_fallback_contact or "").strip()
    if not is_usable_contact(contact):
        return UNCONFIGURED_OWNER
    return OwnerInfo(
        configured=True,
        topic_key=None,
        topic_name=None,
        name=(settings.handoff_fallback_name or "").strip() or None,
        contact=contact,
    )


def resolve_handoff(
    *,
    question: str,
    course_id: str | None = None,
    session: Session | None = None,
) -> HandoffResult:
    """解析该把用户交给哪位售前；任何异常都不应让问答整体失败。"""
    if not settings.handoff_enabled:
        return HandoffResult(owner=UNCONFIGURED_OWNER, route="none")

    owns_session = session is None
    local_session = None
    try:
        if owns_session:
            SessionLocal = _ensure_session_factory()
            local_session = SessionLocal()
            session = local_session

        official = lookup_official_presale(course_id or "")
        if official is not None and official.configured:
            return HandoffResult(owner=official, route="course_api")

        owner = _match_by_course_id(session, course_id or "")
        if owner.configured:
            return HandoffResult(owner=owner, route="course_id")

        if not course_id:
            owner = _match_by_keyword(session, question)
            if owner.configured:
                return HandoffResult(owner=owner, route="keyword")

        return HandoffResult(owner=_fallback_owner(), route="fallback")
    except Exception:
        _log.exception("resolve_handoff failed")
        return HandoffResult(owner=UNCONFIGURED_OWNER, route="none")
    finally:
        if local_session is not None:
            local_session.close()
