"""按保留天数清理过期会话。不引入定时框架。"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from backend.models import Conversation, FunnelEvent, VisitorConsultation
from backend.config import settings


@dataclass(frozen=True)
class PurgeResult:
    conversations: int
    consultations: int = 0
    funnel_events: int = 0


def purge_expired(
    session: Session,
    *,
    now: datetime | None = None,
    retention_days: int,
) -> PurgeResult:
    """删除超过保留期的会话（消息级联删除）。"""
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    cutoff = moment - timedelta(days=retention_days)

    conversations = list(session.scalars(select(Conversation).where(Conversation.updated_at < cutoff)).all()) if retention_days > 0 else []
    for conversation in conversations:
        session.delete(conversation)

    consultation_cutoff = moment - timedelta(hours=settings.visitor_consultation_hours)
    consultations = session.execute(delete(VisitorConsultation).where(VisitorConsultation.updated_at < consultation_cutoff)).rowcount or 0
    event_cutoff = moment - timedelta(days=30)
    funnel_events = session.execute(delete(FunnelEvent).where(FunnelEvent.created_at < event_cutoff)).rowcount or 0
    return PurgeResult(conversations=len(conversations), consultations=consultations, funnel_events=funnel_events)
