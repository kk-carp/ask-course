"""One owner predicate and locked, refreshed authorization for every write."""

from datetime import timezone

from sqlalchemy import func, select

from backend.domain.website_owner import as_owner, utcnow
from backend.models import VisitorConsultation


def owner_filter(owner):
    owner = as_owner(owner)
    if owner.customer_id:
        return (VisitorConsultation.customer_id == owner.customer_id) & VisitorConsultation.visitor_id.is_(None)
    return (VisitorConsultation.visitor_id == owner.visitor_id) & VisitorConsultation.customer_id.is_(None)


def active_filter(owner):
    owner = as_owner(owner)
    return (
        owner_filter(owner)
        & VisitorConsultation.deleted_at.is_(None)
        & (func.coalesce(VisitorConsultation.last_activity_at, VisitorConsultation.updated_at,
                         VisitorConsultation.created_at) >= utcnow() - owner.retention)
    )


def load_owned(session, consultation_id, owner, *, lock=False):
    if owner is None or owner == "":
        return None
    owner = as_owner(owner)
    query = select(VisitorConsultation).where(
        VisitorConsultation.id == consultation_id, active_filter(owner)
    ).execution_options(populate_existing=True)
    if lock:
        query = query.with_for_update()
    row = session.scalar(query)
    # PostgreSQL can wait on a concurrent transfer; recheck validity after waiting.
    owner.validate()
    if row is not None:
        activity = row.last_activity_at or row.updated_at or row.created_at
        if activity.tzinfo is None:
            activity = activity.replace(tzinfo=timezone.utc)
        if activity < utcnow() - owner.retention:
            return None
    return row
