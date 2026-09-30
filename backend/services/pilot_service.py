"""官网课程页灰度：稳定分桶与运行时资料门禁。"""

from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.config import settings
from backend.models import Document, DocumentStatus, PilotControl, TopicOwner
from backend.services.approved_courses import get_approved_course
from backend.services.course_qr_service import lookup_official_presale
from backend.services.topic_owner_service import is_usable_contact


def pilot_percent(session: Session) -> int:
    control = session.get(PilotControl, 1)
    return control.percent if control else settings.pilot_percent


def course_ready(session: Session, course_id: str) -> bool:
    if not is_usable_contact(settings.handoff_fallback_contact):
        return False
    document = session.scalar(
        select(Document.id)
        .where(
            Document.course_id == course_id,
            Document.status == DocumentStatus.ready.value,
        )
        .limit(1)
    )
    if document is None:
        return False
    owner = session.get(TopicOwner, course_id)
    if owner is not None and is_usable_contact(owner.contact):
        return True
    official = lookup_official_presale(course_id)
    return official is not None and official.configured


def eligible(course_id: str, visitor_id: str, session: Session) -> bool:
    allowed = {x.strip() for x in settings.pilot_course_ids.split(",") if x.strip()}
    if course_id not in allowed:
        return False
    percent = max(0, min(100, pilot_percent(session)))
    if percent == 0:
        return False
    bucket = (
        int.from_bytes(sha256(f"{visitor_id}:{course_id}".encode()).digest()[:4], "big")
        % 100
    )
    return (
        bucket < percent
        and get_approved_course(course_id) is not None
        and course_ready(session, course_id)
    )
