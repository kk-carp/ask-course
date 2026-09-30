"""会话与消息读写；消息不进入 documents/chunks。"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend import db
from backend.config import settings
from backend.errors import ServiceUnavailableError
from backend.models import Conversation, Message

_log = logging.getLogger("backend.audit")

_SUMMARY_SYSTEM = (
    "你是会话摘要助手。根据已有摘要与新增对话，输出更新后的纯文本摘要。"
    "只保留对后续追问有用的事实、偏好与未决问题；不要编造课程规定或公司制度；"
    "不要输出 Markdown 标题或列表符号以外的装饰。"
)


@dataclass(frozen=True)
class HistoryMessage:
    role: str
    content: str


@dataclass(frozen=True)
class ContextForGenerate:
    """生成用上下文：可选滚动摘要 + 最近 N 轮原文。摘要不进检索。"""

    history: list[HistoryMessage]
    summary: str | None


@dataclass(frozen=True)
class ConversationSummary:
    id: UUID
    created_at: datetime
    updated_at: datetime
    message_count: int
    preview: str


@dataclass(frozen=True)
class MessageView:
    id: UUID
    role: str
    content: str
    created_at: datetime


class ConversationNotFoundError(LookupError):
    """会话不存在或不属于当前用户。"""


def _ensure_session_factory():
    db.init_engine()
    if db.SessionLocal is None:
        raise ServiceUnavailableError("数据库会话未初始化")
    return db.SessionLocal


def get_or_create_conversation(
    session: Session,
    *,
    user_id: str,
    conversation_id: str | None,
) -> Conversation:
    """解析会话：无 id 则新建；有 id 则校验归属。"""
    if conversation_id is None or not str(conversation_id).strip():
        conversation = Conversation(id=str(uuid4()), user_id=user_id)
        session.add(conversation)
        session.flush()
        return conversation

    conversation = session.get(Conversation, str(conversation_id).strip())
    if conversation is None or conversation.user_id != user_id:
        raise ConversationNotFoundError("会话不存在")
    return conversation


def load_recent_history(
    session: Session,
    *,
    conversation_id: str,
    turns: int | None = None,
) -> list[HistoryMessage]:
    """加载最近 N 轮（用户+助手）已落库消息，按时间正序。"""
    max_turns = turns if turns is not None else settings.conversation_history_turns
    if max_turns <= 0:
        return []

    limit = max_turns * 2
    rows = session.scalars(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc())
        .limit(limit)
    ).all()
    rows_asc = list(reversed(rows))
    return [HistoryMessage(role=row.role, content=row.content) for row in rows_asc]


def _format_messages_for_summary(rows: list[Message]) -> str:
    lines: list[str] = []
    for row in rows:
        role = "用户" if row.role == "user" else "助手"
        text = (row.content or "").strip()
        if not text:
            continue
        lines.append(f"{role}：{text}")
    return "\n".join(lines)


def _clip_summary(text: str) -> str:
    max_chars = max(0, int(settings.conversation_summary_max_chars))
    cleaned = " ".join((text or "").split()).strip()
    if max_chars <= 0 or len(cleaned) <= max_chars:
        return cleaned
    return cleaned[:max_chars].rstrip()


def _summarize_overflow(
    *,
    previous_summary: str | None,
    overflow: list[Message],
) -> str:
    from backend.infra.generate import complete_chat

    overflow_text = _format_messages_for_summary(overflow)
    prior = (previous_summary or "").strip()
    user_prompt = (
        f"已有摘要：\n{(prior or '（无）')}\n\n"
        f"新增对话：\n{overflow_text}\n\n"
        "请输出合并后的摘要（纯文本，尽量短）。"
    )
    result = complete_chat(
        [
            {"role": "system", "content": _SUMMARY_SYSTEM},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.1,
    )
    return _clip_summary(result.text)


def _maybe_roll_summary(session: Session, conversation: Conversation, rows: list[Message]) -> None:
    if not settings.conversation_compress_enabled:
        return
    max_turns = settings.conversation_history_turns
    if max_turns <= 0:
        return
    keep = max_turns * 2
    total = len(rows)
    if total <= keep:
        return
    overflow_end = total - keep
    covered = int(conversation.summary_message_count or 0)
    if covered < 0:
        covered = 0
    if covered >= overflow_end:
        return
    overflow = rows[covered:overflow_end]
    if not overflow:
        return
    try:
        new_summary = _summarize_overflow(
            previous_summary=conversation.context_summary,
            overflow=overflow,
        )
    except Exception:
        _log.warning(
            "conversation compress failed conversation_id=%s",
            conversation.id,
            exc_info=True,
        )
        return
    if not new_summary:
        return
    conversation.context_summary = new_summary
    conversation.summary_message_count = overflow_end
    session.flush()


def load_context_for_generate(
    session: Session,
    *,
    conversation_id: str,
    turns: int | None = None,
) -> ContextForGenerate:
    """加载生成用上下文：必要时滚动压缩旧轮次，返回摘要 + 最近 N 轮。

    压缩失败时保留旧摘要与计数，仅返回最近 N 轮（纯截断），不向上抛成 502。
    """
    conversation = session.get(Conversation, conversation_id)
    if conversation is None:
        return ContextForGenerate(history=[], summary=None)

    rows = list(
        session.scalars(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc())
        ).all()
    )
    _maybe_roll_summary(session, conversation, rows)

    max_turns = turns if turns is not None else settings.conversation_history_turns
    if max_turns <= 0:
        history: list[HistoryMessage] = []
    else:
        keep = max_turns * 2
        recent = rows[-keep:] if keep < len(rows) else rows
        history = [HistoryMessage(role=row.role, content=row.content) for row in recent]

    summary = (conversation.context_summary or "").strip() or None
    return ContextForGenerate(history=history, summary=summary)


def append_turn(
    session: Session,
    *,
    conversation: Conversation,
    user_content: str,
    assistant_content: str,
) -> None:
    """写入一轮用户+助手消息。"""
    session.add(
        Message(
            id=str(uuid4()),
            conversation_id=conversation.id,
            role="user",
            content=user_content,
        )
    )
    session.add(
        Message(
            id=str(uuid4()),
            conversation_id=conversation.id,
            role="assistant",
            content=assistant_content,
        )
    )
    conversation.updated_at = datetime.now(timezone.utc)


def list_conversations_for_user(user_id: str) -> list[ConversationSummary]:
    SessionLocal = _ensure_session_factory()
    with SessionLocal() as session:
        conversations = session.scalars(
            select(Conversation)
            .where(Conversation.user_id == user_id)
            .order_by(Conversation.updated_at.desc())
        ).all()
        result: list[ConversationSummary] = []
        for item in conversations:
            count = session.scalar(
                select(func.count())
                .select_from(Message)
                .where(Message.conversation_id == item.id)
            )
            first_question = session.scalar(
                select(Message.content)
                .where(Message.conversation_id == item.id, Message.role == "user")
                .order_by(Message.created_at.asc())
                .limit(1)
            )
            result.append(
                ConversationSummary(
                    id=UUID(item.id),
                    created_at=item.created_at,
                    updated_at=item.updated_at,
                    message_count=int(count or 0),
                    preview=(first_question or "").strip(),
                )
            )
        return result


def list_messages_for_user(user_id: str, conversation_id: str) -> list[MessageView]:
    SessionLocal = _ensure_session_factory()
    with SessionLocal() as session:
        conversation = session.get(Conversation, conversation_id)
        if conversation is None or conversation.user_id != user_id:
            raise ConversationNotFoundError("会话不存在")
        rows = session.scalars(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc())
        ).all()
        return [
            MessageView(
                id=UUID(row.id),
                role=row.role,
                content=row.content,
                created_at=row.created_at,
            )
            for row in rows
        ]


def delete_conversation_for_user(user_id: str, conversation_id: str) -> None:
    """删除当前用户自己的会话；消息级联删除。他人会话视为不存在。"""
    normalized = (conversation_id or "").strip()
    if not normalized:
        raise ConversationNotFoundError("会话不存在")
    SessionLocal = _ensure_session_factory()
    with SessionLocal() as session:
        conversation = session.get(Conversation, normalized)
        if conversation is None or conversation.user_id != user_id:
            raise ConversationNotFoundError("会话不存在")
        session.delete(conversation)
        session.commit()
