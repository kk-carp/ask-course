"""课程售前联系人：关键词匹配库中记录；无匹配则明确未配置，不编造。"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend import db
from backend.errors import ServiceUnavailableError
from backend.models import TopicOwner
from backend.schemas import OwnerInfo, TopicOwnerResponse


class TopicOwnerError(ValueError):
    """主题负责人配置错误（映射 400）。"""


UNCONFIGURED_OWNER = OwnerInfo(configured=False)
TOPIC_KEY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")


def is_usable_contact(contact: str | None) -> bool:
    """官网 HTTPS 页面只使用 HTTPS 联系方式；占位协议不得进入用户响应。"""
    normalized = (contact or "").strip()
    folded = normalized.casefold()
    if not normalized or any(marker in folded for marker in ("placeholder", "replace-with", "example.")):
        return False
    try:
        parsed = urlparse(normalized)
        return parsed.scheme == "https" and bool(parsed.hostname) and not parsed.username and not parsed.password
    except ValueError:
        return False


def validate_topic_owner_fields(
    *,
    topic_key: str,
    topic_name: str,
    name: str,
    contact: str,
) -> None:
    key = topic_key.strip()
    if not TOPIC_KEY_PATTERN.fullmatch(key):
        raise TopicOwnerError("课程 ID 只能包含小写字母、数字、点、下划线和连字符")
    if not topic_name.strip() or not name.strip():
        raise TopicOwnerError("课程名称和负责人姓名不能为空")
    if not is_usable_contact(contact):
        raise TopicOwnerError("联系方式必须是可访问的 HTTPS 地址，不能使用占位值")


def _ensure_session_factory():
    db.init_engine()
    if db.SessionLocal is None:
        raise ServiceUnavailableError("数据库会话未初始化")
    return db.SessionLocal


def _split_keywords(keywords: str) -> list[str]:
    return [part.strip() for part in keywords.split(",") if part.strip()]


def _candidate_terms(owner: TopicOwner) -> list[str]:
    terms = [owner.topic_key, owner.topic_name, *_split_keywords(owner.keywords)]
    unique: list[str] = []
    seen: set[str] = set()
    for term in terms:
        normalized = term.strip()
        key = normalized.casefold()
        if not normalized or key in seen:
            continue
        seen.add(key)
        unique.append(normalized)
    return unique


def _to_response(owner: TopicOwner) -> TopicOwnerResponse:
    return TopicOwnerResponse(
        topic_key=owner.topic_key,
        topic_name=owner.topic_name,
        keywords=owner.keywords,
        name=owner.owner_name,
        contact=owner.contact,
    )


def _to_owner_info(owner: TopicOwner) -> OwnerInfo:
    if not is_usable_contact(owner.contact):
        return UNCONFIGURED_OWNER
    return OwnerInfo(
        configured=True,
        topic_key=owner.topic_key,
        topic_name=owner.topic_name,
        name=owner.owner_name,
        contact=owner.contact,
    )


def match_owner_for_question(session: Session, question: str) -> OwnerInfo:
    """按问题文本匹配主题；取命中关键词最长的一条。无匹配则 configured=false。"""
    normalized = question.strip()
    if not normalized:
        return UNCONFIGURED_OWNER

    haystack = normalized.casefold()
    best: TopicOwner | None = None
    best_len = 0
    for owner in session.scalars(select(TopicOwner)).all():
        if not is_usable_contact(owner.contact):
            continue
        for term in _candidate_terms(owner):
            needle = term.casefold()
            if len(needle) < 2:
                continue
            if needle in haystack and len(needle) > best_len:
                best = owner
                best_len = len(needle)

    if best is None:
        return UNCONFIGURED_OWNER
    return _to_owner_info(best)


def list_topic_owners() -> list[TopicOwnerResponse]:
    SessionLocal = _ensure_session_factory()
    with SessionLocal() as session:
        rows = session.scalars(select(TopicOwner).order_by(TopicOwner.topic_key)).all()
        return [_to_response(row) for row in rows]


def upsert_topic_owner(
    *,
    topic_key: str,
    topic_name: str,
    keywords: str,
    name: str,
    contact: str,
) -> TopicOwnerResponse:
    key = topic_key.strip()
    title = topic_name.strip()
    owner_name = name.strip()
    owner_contact = contact.strip()
    validate_topic_owner_fields(
        topic_key=key,
        topic_name=title,
        name=owner_name,
        contact=owner_contact,
    )

    SessionLocal = _ensure_session_factory()
    with SessionLocal() as session:
        row = session.get(TopicOwner, key)
        if row is None:
            row = TopicOwner(
                topic_key=key,
                topic_name=title,
                keywords=keywords.strip(),
                owner_name=owner_name,
                contact=owner_contact,
            )
            session.add(row)
        else:
            row.topic_name = title
            row.keywords = keywords.strip()
            row.owner_name = owner_name
            row.contact = owner_contact
        session.commit()
        session.refresh(row)
        return _to_response(row)
