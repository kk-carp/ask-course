"""Website APIs never inherit internal staff login privileges."""

import json
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db import get_session
from backend.domain.guest import issue_visitor_id, read_visitor_id
from backend.domain.website_owner import VerifiedCustomerIdentity
from backend.models import VisitorTurn
from backend.routes.consultations import _limit
from backend.services.pilot_service import site_eligible
from backend.services import widget_history as history
from backend.services.website_identity import resolve_owner, verified_website_identity
from backend.services.widget_history import create, descriptor, owned

router = APIRouter(prefix="/widget/conversations", tags=["widget history"])
Database = Annotated[Session, Depends(get_session)]
Identity = Annotated[VerifiedCustomerIdentity | None, Depends(verified_website_identity)]


class CreateRequest(BaseModel):
    request_id: UUID


class RenameRequest(BaseModel):
    title: str = Field(min_length=1, max_length=40)

    @field_validator("title")
    @classmethod
    def clean(cls, value):
        if not value.strip():
            raise ValueError("请输入对话名称")
        return value.strip()


def request_owner(request: Request, session: Session, identity=None):
    owner = resolve_owner(session, read_visitor_id(request), identity)
    if not site_eligible(owner.key, session):
        raise HTTPException(404, "当前尚未开放咨询")
    _limit(owner.key)
    return owner


@router.post("")
def new(
    payload: CreateRequest, request: Request, response: Response, session: Database,
    identity: Identity,
):
    owner = resolve_owner(session, issue_visitor_id(request, response), identity)
    if not site_eligible(owner.key, session):
        raise HTTPException(404, "当前尚未开放咨询")
    _limit(owner.key)
    return create(session, owner, str(payload.request_id))


@router.get("")
def listing(
    request: Request,
    session: Database,
    identity: Identity,
    offset: int = Query(0, ge=0),
    limit: int = Query(30, ge=1, le=100),
):
    key = request_owner(request, session, identity)
    rows = history.listing(session, key, offset, limit)
    return {
        "items": [descriptor(row) for row in rows[:limit]],
        "next_offset": offset + limit if len(rows) > limit else None,
    }


@router.get("/{conversation_id}/messages")
def messages(
    conversation_id: UUID,
    request: Request,
    session: Database,
    identity: Identity,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
):
    key = request_owner(request, session, identity)
    row = owned(session, str(conversation_id), key)
    records = list(
        session.scalars(
            select(VisitorTurn)
            .where(
                VisitorTurn.conversation_id == row.id,
                VisitorTurn.response_json.is_not(None),
            )
            .order_by(VisitorTurn.created_at, VisitorTurn.id)
            .offset(offset)
            .limit(limit + 1)
        )
    )
    return {
        "conversation": descriptor(row),
        "items": [
            {
                "request_id": turn.request_id,
                "question": turn.question,
                "result": json.loads(turn.response_json),
            }
            for turn in records[:limit]
        ],
        "next_offset": offset + limit if len(records) > limit else None,
    }


@router.patch("/{conversation_id}")
def rename(
    conversation_id: UUID, payload: RenameRequest, request: Request, session: Database,
    identity: Identity,
):
    return history.rename(session, str(conversation_id), request_owner(request, session, identity), payload.title)


@router.delete("/{conversation_id}", status_code=204)
def remove(conversation_id: UUID, request: Request, session: Database, identity: Identity):
    key = request_owner(request, session, identity)
    history.remove(session, str(conversation_id), key)
    return Response(status_code=204)


@router.post("/{conversation_id}/associate")
def associate(conversation_id: UUID, request: Request, session: Database, identity: Identity):
    if identity is None:
        raise HTTPException(401, "需要经官网验证的登录身份")
    guest = read_visitor_id(request)
    if not guest or not site_eligible(guest, session):
        raise HTTPException(404, "当前尚未开放咨询")
    _limit(guest)
    _, result = history.associate_current(session, identity, guest, str(conversation_id))
    return result
