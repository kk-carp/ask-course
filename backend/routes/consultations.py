"""官网灰度入口、匿名问诊及转化事件。"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.config import settings
from backend.db import get_session
from backend.domain.guest import issue_visitor_id, read_visitor_id
from backend.infra.rate_limit import allow
from backend.models import FunnelEvent, PilotControl
from backend.services.approved_courses import get_approved_course
from backend.services.consultation_service import answer, load_owned, present, start
from backend.services.topic_owner_service import is_usable_contact
from backend.services.auth_service import can_manage_documents, load_auth_context
from backend.services.pilot_service import eligible, pilot_percent
from backend.services.purchase_service import validate_purchase_destination
from backend.errors import ServiceUnavailableError

router = APIRouter(tags=["consultations"])
_EVENTS = frozenset({"widget_impression", "widget_open", "question", "recommendation", "handoff", "error"})


class StartRequest(BaseModel):
    course_id: str = Field(pattern=r"^[1-9]\d{0,11}$")
    known_profile: dict[str, str | int] = Field(default_factory=dict)


class AnswerRequest(BaseModel):
    field: str
    value: str | int


class EventRequest(BaseModel):
    course_id: str = Field(pattern=r"^[1-9]\d{0,11}$")
    event_name: str


class PilotUpdate(BaseModel):
    percent: int


def _visitor(request: Request, response: Response) -> str:
    return issue_visitor_id(request, response)


def _require_eligible(course_id: str, visitor_id: str, session: Session) -> None:
    if not eligible(course_id, visitor_id, session):
        raise HTTPException(status_code=404, detail="当前页面尚未开放咨询")


def _limit(visitor_id: str) -> None:
    if not allow(f"consultation:{visitor_id}", max_requests=30, window_seconds=60):
        raise HTTPException(status_code=429, detail="操作过于频繁，请稍后重试")


@router.get("/widget/config")
def widget_config(
    course_id: str,
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
) -> dict:
    visitor_id = _visitor(request, response)
    enabled = eligible(course_id, visitor_id, session)
    course = get_approved_course(course_id) if enabled else None
    return {
        "enabled": enabled,
        "course_id": course_id,
        "course_title": course.title if course else None,
        "default_prompts": [
            "推荐一门适合我的课程",
            "按我的基础帮我选课",
            "我想找课程顾问",
        ],
        "fallback_contact": settings.handoff_fallback_contact
        if enabled and is_usable_contact(settings.handoff_fallback_contact)
        else None,
    }


@router.post("/consultations")
def create_consultation(
    payload: StartRequest,
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
) -> dict:
    visitor_id = _visitor(request, response)
    _require_eligible(payload.course_id, visitor_id, session)
    _limit(visitor_id)
    try:
        return start(session, visitor_id, payload.course_id, payload.known_profile)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/consultations/{consultation_id}")
def get_consultation(
    consultation_id: UUID, request: Request, session: Session = Depends(get_session)
) -> dict:
    visitor_id = read_visitor_id(request)
    row = load_owned(session, str(consultation_id), visitor_id or "")
    if row is None:
        raise HTTPException(status_code=404, detail="问诊不存在或已过期")
    _require_eligible(row.course_id or "", visitor_id or "", session)
    return present(session, row)


@router.post("/consultations/{consultation_id}/answers")
def answer_consultation(
    consultation_id: UUID,
    payload: AnswerRequest,
    request: Request,
    session: Session = Depends(get_session),
) -> dict:
    visitor_id = read_visitor_id(request)
    row = load_owned(session, str(consultation_id), visitor_id or "")
    if row is None:
        raise HTTPException(status_code=404, detail="问诊不存在或已过期")
    _require_eligible(row.course_id or "", visitor_id or "", session)
    _limit(visitor_id or "")
    try:
        return answer(session, row, payload.field, payload.value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/widget/events", status_code=204)
def record_widget_event(
    payload: EventRequest, request: Request, session: Session = Depends(get_session)
) -> Response:
    visitor_id = read_visitor_id(request)
    _require_eligible(payload.course_id, visitor_id or "", session)
    if payload.event_name not in _EVENTS:
        raise HTTPException(status_code=422, detail="未知事件")
    _limit(visitor_id or "")
    session.add(
        FunnelEvent(
            visitor_id=visitor_id,
            course_id=payload.course_id,
            event_name=payload.event_name,
        )
    )
    session.commit()
    return Response(status_code=204)


@router.post("/purchase/{course_id}")
def purchase_destination(
    course_id: str, request: Request, session: Session = Depends(get_session)
) -> dict:
    visitor_id = read_visitor_id(request)
    _require_eligible(course_id, visitor_id or "", session)
    _limit(visitor_id or "")
    course = get_approved_course(course_id, verify_live=True)
    if course is None:
        raise HTTPException(status_code=404, detail="课程暂不可购买")
    try:
        destination = validate_purchase_destination(course)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ServiceUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    session.add(
        FunnelEvent(
            visitor_id=visitor_id, course_id=course_id, event_name="purchase_click"
        )
    )
    session.commit()
    return {"url": destination}


@router.get("/courses/{course_id}/purchase")
def verified_purchase_destination(course_id: str) -> dict:
    """内部演示页使用：点击时再次核实审核清单与官网在售列表。"""
    course = get_approved_course(course_id, verify_live=True)
    if course is None:
        raise HTTPException(status_code=404, detail="课程暂不可购买")
    try:
        return {"url": validate_purchase_destination(course)}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ServiceUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _require_admin(request: Request) -> None:
    context = load_auth_context(request)
    if context is None:
        raise HTTPException(status_code=401, detail="未登录")
    if not can_manage_documents(context.user):
        raise HTTPException(status_code=403, detail="仅管理员可调整灰度")


@router.get("/pilot/control")
def get_pilot_control(
    request: Request, session: Session = Depends(get_session)
) -> dict:
    _require_admin(request)
    return {
        "percent": pilot_percent(session),
        "course_ids": [
            x.strip() for x in settings.pilot_course_ids.split(",") if x.strip()
        ],
    }


@router.put("/pilot/control")
def update_pilot_control(
    payload: PilotUpdate, request: Request, session: Session = Depends(get_session)
) -> dict:
    _require_admin(request)
    if payload.percent not in {0, 5, 25, 100}:
        raise HTTPException(status_code=422, detail="灰度比例只能是 0、5、25 或 100")
    row = session.get(PilotControl, 1)
    if row is None:
        row = PilotControl(id=1, percent=payload.percent)
        session.add(row)
    else:
        row.percent = payload.percent
    session.commit()
    return {"percent": payload.percent}
