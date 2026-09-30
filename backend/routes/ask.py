"""问答 HTTP：POST /ask 返回完整 JSON；POST /ask/stream 为 SSE。

编排在 ask_orchestrator；本文件只做限流、身份、pilot 与 SSE 打包。
"""

import json
import logging
from collections.abc import Iterator

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import StreamingResponse

from backend import db
from backend.config import settings
from backend.domain.guest import guest_context, issue_visitor_id, read_visitor_id
from backend.infra.metrics import record_429
from backend.infra.rate_limit import RATE_LIMIT_DETAIL, allow, allow_ask
from backend.schemas import AskRequest, AskResponse
from backend.services.ask_orchestrator import (
    AskIdentity,
    apply_handoff,
    course_context_for_content,
    run_ask_turn,
)
from backend.services.auth_service import load_auth_context
from backend.services.conversation_service import ConversationNotFoundError
from backend.errors import ServiceUnavailableError, UpstreamServiceError
from backend.services.intent_router import Intent, handle_routed_turn
from backend.services.pilot_service import eligible
from backend.services.qa_service import AskResult, iter_answer_events
from backend.services.question_decomposition import split_questions

router = APIRouter(tags=["ask"])
_log = logging.getLogger("backend.ask")


def _sse_pack(event: str, data: dict) -> str:
    return (
        f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"
    )


def _allow_guest_ask(visitor_id: str) -> bool:
    """游客限流按匿名 id 计数；与登录用户限流分开，避免互相挤占配额。"""
    return allow(
        f"ask:guest:{visitor_id}",
        max_requests=settings.guest_ask_rate_max,
        window_seconds=float(settings.guest_ask_rate_window_seconds),
    )


def _resolve_identity(request: Request, response: Response) -> AskIdentity:
    context = load_auth_context(request)
    if context is not None:
        return AskIdentity(
            allowed_spaces=list(context.allowed_spaces),
            user_id=context.user.id,
            user_role=context.user.role,
            visitor_id=None,
        )

    visitor_id = issue_visitor_id(request, response)
    guest = guest_context(visitor_id)
    return AskIdentity(
        allowed_spaces=list(guest.allowed_spaces),
        user_id=None,
        user_role=guest.user_role,
        visitor_id=visitor_id,
    )


def _require_site_pilot(payload: AskRequest, request: Request) -> None:
    if payload.channel not in {"course_page", "site_widget"}:
        return
    visitor_id = read_visitor_id(request)
    if not visitor_id or not payload.course_id or db.SessionLocal is None:
        raise HTTPException(status_code=404, detail="当前页面尚未开放咨询")
    with db.SessionLocal() as session:
        if not eligible(payload.course_id, visitor_id, session):
            raise HTTPException(status_code=404, detail="当前页面尚未开放咨询")


def _routed_payload(routed) -> dict:
    related = list(routed.related_courses)
    return {
        "answer": routed.result.answer,
        "hit": routed.result.hit,
        "sources": [],
        "conversation_id": None,
        "owner": (
            routed.result.owner.model_dump(mode="json")
            if routed.result.owner is not None
            else None
        ),
        "related_courses": [item.model_dump(mode="json") for item in related],
        "intent": routed.intent.value,
        "llm_called": False,
        "prompt_tokens": 0,
        "completion_tokens": 0,
    }


def _enforce_rate_limit(identity: AskIdentity) -> None:
    if identity.user_id is None:
        if not _allow_guest_ask(identity.visitor_id or "unknown"):
            record_429()
            raise HTTPException(status_code=429, detail=RATE_LIMIT_DETAIL)
    elif not allow_ask(identity.user_id):
        record_429()
        raise HTTPException(status_code=429, detail=RATE_LIMIT_DETAIL)


@router.post("/ask", response_model=AskResponse)
async def ask(payload: AskRequest, request: Request, response: Response) -> AskResponse:
    """登录或游客均可提问；编排见 ask_orchestrator。"""
    _require_site_pilot(payload, request)
    identity = _resolve_identity(request, response)
    _enforce_rate_limit(identity)
    return run_ask_turn(payload, identity)


@router.post("/ask/stream")
async def ask_stream(
    payload: AskRequest, request: Request, response: Response
) -> StreamingResponse:
    """游客或多问题使用统一编排；登录用户的单问题保留逐字输出。"""
    if load_auth_context(request) is None or len(split_questions(payload.question)) > 1:
        result = await ask(payload, request, response)
        data = result.model_dump(mode="json")

        def completed_events() -> Iterator[str]:
            yield _sse_pack(
                "meta",
                {
                    "hit": data["hit"],
                    "sources": data["sources"],
                    "conversation_id": data["conversation_id"],
                    "related_courses": data["related_courses"],
                    "intent": data["intent"],
                },
            )
            yield _sse_pack("final", data)
            yield _sse_pack("done", {})

        stream = StreamingResponse(completed_events(), media_type="text/event-stream")
        for name, value in response.raw_headers:
            if name.lower() == b"set-cookie":
                stream.raw_headers.append((name, value))
        return stream

    _require_site_pilot(payload, request)
    identity = _resolve_identity(request, response)
    _enforce_rate_limit(identity)

    question = payload.question
    conversation_id = payload.conversation_id
    routed = handle_routed_turn(question, course_id=payload.course_id)

    def event_gen() -> Iterator[str]:
        try:
            if routed.handled:
                _log.info("ask/stream short-circuit intent=%s", routed.intent.value)
                payload_data = _routed_payload(routed)
                yield _sse_pack(
                    "meta",
                    {
                        "hit": False,
                        "sources": [],
                        "conversation_id": None,
                        "related_courses": payload_data["related_courses"],
                        "intent": routed.intent.value,
                    },
                )
                yield _sse_pack("final", payload_data)
                yield _sse_pack("done", {})
                return

            course_id, related = course_context_for_content(
                question, payload.course_id
            )
            related_payload = [item.model_dump(mode="json") for item in related]
            for name, data in iter_answer_events(
                allowed_spaces=identity.allowed_spaces,
                question=question,
                user_id=identity.user_id,
                user_role=identity.user_role,
                conversation_id=conversation_id,
                course_id=course_id,
            ):
                if isinstance(data, dict):
                    data = {
                        **data,
                        "related_courses": related_payload,
                        "intent": Intent.content.value,
                    }
                if (
                    name == "final"
                    and isinstance(data, dict)
                    and data.get("hit") is False
                ):
                    handed = apply_handoff(
                        AskResult(
                            answer=data.get("answer", ""),
                            hit=False,
                            sources=[],
                        ),
                        question=question,
                        course_id=course_id,
                        related_courses=related,
                    )
                    data = {
                        **data,
                        "answer": handed.answer,
                        "owner": (
                            handed.owner.model_dump(mode="json")
                            if handed.owner is not None
                            else None
                        ),
                    }
                yield _sse_pack(name, data)
        except ConversationNotFoundError as exc:
            yield _sse_pack("error", {"status": 404, "detail": str(exc)})
        except ValueError as exc:
            yield _sse_pack("error", {"status": 400, "detail": str(exc)})
        except ServiceUnavailableError as exc:
            yield _sse_pack("error", {"status": 503, "detail": str(exc)})
        except UpstreamServiceError as exc:
            yield _sse_pack("error", {"status": 502, "detail": str(exc)})
        except Exception:
            yield _sse_pack("error", {"status": 500, "detail": "问答处理失败"})
        yield _sse_pack("done", {})

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
