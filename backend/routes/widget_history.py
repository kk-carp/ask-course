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
from backend.models import VisitorConsultation, VisitorTurn
from backend.routes.consultations import _limit
from backend.services.pilot_service import site_eligible
from backend.services.widget_history import create, cutoff, descriptor, now, owned

router = APIRouter(prefix="/widget/conversations", tags=["widget history"])
Database = Annotated[Session, Depends(get_session)]


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


def visitor(request: Request, session: Session):
    key = read_visitor_id(request)
    if not key or not site_eligible(key, session):
        raise HTTPException(404, "当前尚未开放咨询")
    _limit(key)
    return key


@router.post("")
def new(
    payload: CreateRequest, request: Request, response: Response, session: Database
):
    key = issue_visitor_id(request, response)
    if not site_eligible(key, session):
        raise HTTPException(404, "当前尚未开放咨询")
    _limit(key)
    return create(session, key, str(payload.request_id))


@router.get("")
def listing(
    request: Request,
    session: Database,
    offset: int = Query(0, ge=0),
    limit: int = Query(30, ge=1, le=100),
):
    key = visitor(request, session)
    rows = list(
        session.scalars(
            select(VisitorConsultation)
            .where(
                VisitorConsultation.visitor_id == key,
                VisitorConsultation.widget_session.is_(True),
                VisitorConsultation.deleted_at.is_(None),
                VisitorConsultation.last_activity_at >= cutoff(),
            )
            .order_by(
                VisitorConsultation.last_activity_at.desc(),
                VisitorConsultation.id.desc(),
            )
            .offset(offset)
            .limit(limit + 1)
        )
    )
    return {
        "items": [descriptor(row) for row in rows[:limit]],
        "next_offset": offset + limit if len(rows) > limit else None,
    }


@router.get("/{conversation_id}/messages")
def messages(
    conversation_id: UUID,
    request: Request,
    session: Database,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
):
    key = visitor(request, session)
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
    conversation_id: UUID, payload: RenameRequest, request: Request, session: Database
):
    row = owned(session, str(conversation_id), visitor(request, session), lock=True)
    row.title, row.custom_title = payload.title, True
    session.commit()
    return descriptor(row)


@router.delete("/{conversation_id}", status_code=204)
def remove(conversation_id: UUID, request: Request, session: Database):
    key = visitor(request, session)
    row = session.scalar(
        select(VisitorConsultation)
        .where(
            VisitorConsultation.id == str(conversation_id),
            VisitorConsultation.visitor_id == key,
            VisitorConsultation.widget_session.is_(True),
        )
        .with_for_update()
    )
    if row is not None and row.deleted_at is None:
        row.deleted_at = now()
        session.commit()
    return Response(status_code=204)
