"""课程问答：仅基于召回正文生成；未命中不调用模型，来源只来自召回记录。"""

import logging
import time
from dataclasses import dataclass
from uuid import UUID

from backend import db
from backend.domain.followup import expand_followup_query, last_user_question
from backend.errors import ServiceUnavailableError, UpstreamServiceError
from backend.infra.embed import encode_query, is_loaded
from backend.infra.generate import generate_answer
from backend.infra.metrics import record_ask_outcome, record_latency
from backend.infra.request_context import get_request_id
from backend.infra.retrieve import RetrievedChunk, run_retrieval
from backend.schemas import OwnerInfo, SourceItem
from backend.services.conversation_service import (
    append_turn,
    get_or_create_conversation,
    load_context_for_generate,
)
from backend.services.knowledge_guard import ensure_published, published_evidence

MISS_ANSWER = "知识库中没有足够依据回答这个问题。"
SOURCE_SNIPPET_CHARS = 160
_audit_logger = logging.getLogger("backend.audit")


@dataclass(frozen=True)
class AskResult:
    answer: str
    hit: bool
    sources: list[SourceItem]
    conversation_id: UUID | None = None
    owner: OwnerInfo | None = None
    error_type: str | None = None
    llm_called: bool = False
    prompt_tokens: int = 0
    completion_tokens: int = 0
    knowledge_document_ids: tuple[UUID, ...] = ()


def _snippet_from_content(content: str, limit: int = SOURCE_SNIPPET_CHARS) -> str:
    """从来源召回正文截一段预览；不经过模型。"""
    collapsed = " ".join((content or "").split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[:limit].rstrip() + "…"


def _build_sources(retrieved) -> list[SourceItem]:
    unique_sources: list[SourceItem] = []
    seen_document_ids: set[str] = set()
    for item in retrieved:
        document_key = str(item.document_id)
        if document_key in seen_document_ids:
            continue
        seen_document_ids.add(document_key)
        unique_sources.append(
            SourceItem(
                document_id=item.document_id,
                title=item.title,
                space_id=item.space_id,
                path=item.path,
                score=round(float(item.score), 4),
                snippet=_snippet_from_content(item.content),
            )
        )
        if len(unique_sources) >= 3:
            break
    return unique_sources


def _write_audit(
    *,
    user_id: str | None,
    user_role: str | None,
    allowed_spaces: list[str],
    hit: bool | None,
    document_ids: list[str],
    error_type: str,
    llm_called: bool = False,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
) -> None:
    """最小审计：请求编号、用户、角色、空间、是否命中、引用文档 ID、错误类型。不含密钥与正文。"""
    record_ask_outcome(
        error_type=error_type,
        llm_called=llm_called,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )
    if user_id is None:
        return
    _audit_logger.info(
        "ask request_id=%s user_id=%s role=%s spaces=%s hit=%s docs=%s error=%s",
        get_request_id() or "-",
        user_id,
        user_role or "",
        ",".join(allowed_spaces),
        "true" if hit is True else "false" if hit is False else "",
        ",".join(document_ids),
        error_type,
    )


def _retrieve(
    allowed_spaces: list[str],
    question: str,
    *,
    previous_user_question: str | None = None,
    course_id: str | None = None,
) -> list[RetrievedChunk]:
    from backend.services.course_scope import permits_retrieval
    if not permits_retrieval(course_id):
        return []
    if not allowed_spaces:
        return []
    query_text = question
    query_text = expand_followup_query(query_text, previous_user_question)
    started = time.perf_counter()
    query_vector = encode_query(query_text)
    record_latency("embedding", (time.perf_counter() - started) * 1000)
    started = time.perf_counter()
    retrieved = run_retrieval(
        query_text=query_text, query_vector=query_vector, allowed_spaces=allowed_spaces,
        course_id=course_id,
    )
    record_latency("retrieval_and_rerank", (time.perf_counter() - started) * 1000)
    return retrieved


def answer_question(
    allowed_spaces: list[str],
    question: str,
    *,
    user_id: str | None = None,
    user_role: str | None = None,
    conversation_id: str | UUID | None = None,
    course_id: str | None = None,
    visitor_history: list[tuple[str, str]] | None = None,
) -> AskResult:
    """在授权课程空间内回答；未命中不调模型，502/503 不落库。"""
    normalized_question = question.strip()
    if not normalized_question:
        raise ValueError("问题不能为空")
    if not is_loaded():
        raise ServiceUnavailableError("向量模型未加载")
    conversation_uuid = str(conversation_id) if conversation_id is not None else None
    use_conversation = user_id is not None
    if not use_conversation:
        return _answer_without_conversation(
            allowed_spaces, normalized_question, user_role=user_role, course_id=course_id,
            history=visitor_history,
        )
    db.init_engine()
    if db.SessionLocal is None:
        raise ServiceUnavailableError("数据库会话未初始化")
    with db.SessionLocal() as session:
        conversation = get_or_create_conversation(
            session, user_id=user_id, conversation_id=conversation_uuid
        )
        ctx = load_context_for_generate(session, conversation_id=conversation.id)
        history_tuples = [(item.role, item.content) for item in ctx.history]
        conversation_summary = ctx.summary

        def _miss_result() -> AskResult:
            append_turn(
                session,
                conversation=conversation,
                user_content=normalized_question,
                assistant_content=MISS_ANSWER,
            )
            session.commit()
            _write_audit(
                user_id=user_id,
                user_role=user_role,
                allowed_spaces=allowed_spaces,
                hit=False,
                document_ids=[],
                error_type="miss",
            )
            return AskResult(
                answer=MISS_ANSWER,
                hit=False,
                sources=[],
                conversation_id=UUID(conversation.id),
                owner=None,
            )

        retrieved = _retrieve(
            allowed_spaces,
            normalized_question,
            previous_user_question=last_user_question(history_tuples),
            course_id=course_id,
        )
        if not retrieved:
            return _miss_result()
        document_ids = tuple({item.document_id for item in retrieved})
        ensure_published(document_ids)
        try:
            generated = generate_answer(
                normalized_question,
                retrieved,
                history=history_tuples,
                conversation_summary=conversation_summary,
            )
        except UpstreamServiceError:
            session.rollback()
            _write_audit(
                user_id=user_id,
                user_role=user_role,
                allowed_spaces=allowed_spaces,
                hit=None,
                document_ids=[str(item.document_id) for item in retrieved],
                error_type="502",
            )
            raise
        except ServiceUnavailableError:
            session.rollback()
            _write_audit(
                user_id=user_id,
                user_role=user_role,
                allowed_spaces=allowed_spaces,
                hit=None,
                document_ids=[str(item.document_id) for item in retrieved],
                error_type="503",
            )
            raise
        answer = generated.text
        with published_evidence(document_ids):
            append_turn(
                session,
                conversation=conversation,
                user_content=normalized_question,
                assistant_content=answer,
            )
            session.commit()
        sources = _build_sources(retrieved)
        _write_audit(
            user_id=user_id,
            user_role=user_role,
            allowed_spaces=allowed_spaces,
            hit=True,
            document_ids=[str(item.document_id) for item in sources],
            error_type="hit",
            llm_called=True,
            prompt_tokens=generated.usage.prompt_tokens,
            completion_tokens=generated.usage.completion_tokens,
        )
        return AskResult(
            answer=answer,
            hit=True,
            sources=sources,
            conversation_id=UUID(conversation.id),
            owner=None,
            llm_called=True,
            prompt_tokens=generated.usage.prompt_tokens,
            completion_tokens=generated.usage.completion_tokens,
            knowledge_document_ids=document_ids,
        )


def _answer_without_conversation(
    allowed_spaces: list[str], normalized_question: str, *, user_role: str | None = None,
    course_id: str | None = None, history: list[tuple[str, str]] | None = None,
) -> AskResult:
    """游客知识问答；历史只用于理解追问，本轮事实仍须来自检索片段。"""
    retrieved = _retrieve(
        allowed_spaces, normalized_question,
        previous_user_question=last_user_question(history), course_id=course_id,
    )
    if not retrieved:
        _write_audit(user_id=None, user_role=user_role, allowed_spaces=allowed_spaces, hit=False, document_ids=[], error_type="miss")
        return AskResult(answer=MISS_ANSWER, hit=False, sources=[])
    document_ids = tuple({item.document_id for item in retrieved})
    ensure_published(document_ids)
    try:
        generated = generate_answer(normalized_question, retrieved)
    except UpstreamServiceError:
        _write_audit(user_id=None, user_role=user_role, allowed_spaces=allowed_spaces, hit=None, document_ids=[str(item.document_id) for item in retrieved], error_type="502")
        raise
    except ServiceUnavailableError:
        _write_audit(user_id=None, user_role=user_role, allowed_spaces=allowed_spaces, hit=None, document_ids=[str(item.document_id) for item in retrieved], error_type="503")
        raise
    ensure_published(document_ids)
    _write_audit(user_id=None, user_role=user_role, allowed_spaces=allowed_spaces, hit=True, document_ids=[str(item.document_id) for item in retrieved], error_type="hit", llm_called=True, prompt_tokens=generated.usage.prompt_tokens, completion_tokens=generated.usage.completion_tokens)
    return AskResult(
        answer=generated.text,
        hit=True,
        sources=_build_sources(retrieved),
        llm_called=True,
        prompt_tokens=generated.usage.prompt_tokens,
        completion_tokens=generated.usage.completion_tokens,
        knowledge_document_ids=document_ids,
    )
