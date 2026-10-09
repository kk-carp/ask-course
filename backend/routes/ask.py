"""问答与逐项事件共用编排；同步数据库、官网及模型操作在线程池执行。"""

import json
import logging
from dataclasses import replace

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from backend import db
from backend.config import settings
from backend.domain.guest import guest_context, issue_visitor_id, read_visitor_id
from backend.infra.metrics import record_429
from backend.infra.rate_limit import RATE_LIMIT_DETAIL, allow, allow_ask
from backend.schemas import AskRequest, AskResponse
from backend.services.ask_orchestrator import AskIdentity, iter_ask_turn, run_ask_turn
from backend.services.auth_service import load_auth_context
from backend.services.pilot_service import eligible, site_course_ids, site_eligible
from backend.services.widget_history import abandon_turn, begin_turn, finish_turn
from backend.services.website_identity import resolve_owner, verified_website_identity
from backend.domain.website_owner import VerifiedCustomerIdentity, as_owner

router = APIRouter(tags=["ask"])
_log = logging.getLogger(__name__)


def _sse_pack(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def _allow_guest_ask(visitor_id: str) -> bool:
    return allow(f"ask:guest:{visitor_id}", max_requests=settings.guest_ask_rate_max,
                 window_seconds=float(settings.guest_ask_rate_window_seconds))


def _prepare_request(payload: AskRequest, request: Request, response: Response,
                     verified: VerifiedCustomerIdentity | None = None) -> AskIdentity:
    public = payload.channel in {'course_page', 'site_widget'}
    if verified is not None and not public:
        raise HTTPException(400, "官网身份仅支持官网咨询通道")
    scope = None
    if payload.channel in {"course_page", "site_widget"}:
        visitor_id = read_visitor_id(request)
        if db.SessionLocal is None:
            raise HTTPException(status_code=404, detail="当前页面尚未开放咨询")
        with db.SessionLocal() as session:
            owner = resolve_owner(session, visitor_id, verified)
            enabled = site_eligible(owner.key, session) if payload.channel == 'site_widget' else bool(payload.course_id and eligible(payload.course_id, owner.key, session))
            if not enabled:
                raise HTTPException(status_code=404, detail="当前页面尚未开放咨询")
            scope = site_course_ids(session)
            if payload.course_id not in scope:
                payload.course_id = None
    context = None if public else load_auth_context(request)
    if context is not None:
        identity = AskIdentity(list(context.allowed_spaces), context.user.id, context.user.role, None)
        permitted = allow_ask(context.user.id)
    else:
        if not public:
            visitor_id = issue_visitor_id(request, response)
            owner = as_owner(visitor_id)
        visitor_id = owner.visitor_id
        guest = guest_context(visitor_id or owner.key)
        identity = AskIdentity(list(guest.allowed_spaces), None, guest.user_role, visitor_id,
                               scope, website_owner=owner)
        permitted = _allow_guest_ask(owner.key)
    if not permitted:
        record_429()
        raise HTTPException(status_code=429, detail=RATE_LIMIT_DETAIL)
    return identity


def _website_turns(payload, identity):
    if payload.channel != 'site_widget':
        yield from iter_ask_turn(payload, identity)
        return
    if not payload.conversation_id or not payload.request_id:
        raise HTTPException(422, '官网提问需要会话编号与请求编号')
    key, request_key = str(payload.conversation_id), str(payload.request_id)
    with db.SessionLocal() as session:
        cached, first, claim_id = begin_turn(session, key, identity.consultation_owner, request_key, payload.question)
    if cached:
        yield 'final', cached
        return
    try:
        for name, result in iter_ask_turn(payload, replace(identity, first_turn=first)):
            identity.consultation_owner.validate()
            if name == 'final' and result.error_type not in {'upstream_error', 'service_unavailable'}:
                with db.SessionLocal() as session:
                    finish_turn(session, key, identity.consultation_owner, request_key, payload.question, result, claim_id)
            yield name, result
    finally:
        with db.SessionLocal() as session:
            abandon_turn(session, key, identity.consultation_owner, request_key, claim_id)


@router.post("/ask", response_model=AskResponse)
async def ask(payload: AskRequest, request: Request, response: Response,
              verified: VerifiedCustomerIdentity | None = Depends(verified_website_identity)) -> AskResponse:
    identity = await run_in_threadpool(_prepare_request, payload, request, response, verified)
    if payload.channel != 'site_widget':
        return await run_in_threadpool(run_ask_turn, payload, identity)
    def run():
        return next(result for name, result in _website_turns(payload, identity) if name == 'final')
    return await run_in_threadpool(run)


@router.post("/ask/stream")
async def ask_stream(payload: AskRequest, request: Request, response: Response,
                     verified: VerifiedCustomerIdentity | None = Depends(verified_website_identity)) -> StreamingResponse:
    identity = await run_in_threadpool(_prepare_request, payload, request, response, verified)

    def events():
        yield _sse_pack("progress", {"message": "正在理解问题并查询课程资料…"})
        try:
            for name, result in _website_turns(payload, identity):
                if name == "part":
                    yield _sse_pack("part", result)
                else:
                    data = result.model_dump(mode="json")
                    yield _sse_pack("meta", {key: data[key] for key in ("hit", "sources", "conversation_id", "related_courses", "intent")})
                    yield _sse_pack("final", data)
        except HTTPException as exc:
            yield _sse_pack("error", {"status": exc.status_code, "detail": exc.detail})
        except Exception:
            _log.exception("stream turn failed")
            yield _sse_pack("error", {"status": 500, "detail": "问答暂时不可用，请稍后重试"})
        yield _sse_pack("done", {})

    stream = StreamingResponse(events(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache", "X-Accel-Buffering": "no",
    })
    for name, value in response.raw_headers:
        if name.lower() == b"set-cookie":
            stream.raw_headers.append((name, value))
    return stream
