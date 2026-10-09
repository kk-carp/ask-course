"""Fail-closed verification seam and transactional website customer creation."""

from uuid import uuid4

from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from backend.domain.website_owner import VerifiedCustomerIdentity, WebsiteOwner
from backend.models import WebsiteCustomer


def verified_website_identity(request: Request) -> VerifiedCustomerIdentity | None:
    """Replace with the real server verifier once its contract is available.

    No request header, staff cookie or client-declared ID can produce a customer.
    A supplied credential must never silently fall back to a guest.
    """
    if request.headers.get("authorization") is not None:
        raise HTTPException(503, "官网身份验证尚未接通，请稍后重试")
    return None


def customer_owner(session, identity: VerifiedCustomerIdentity) -> WebsiteOwner:
    identity.validate()
    query = select(WebsiteCustomer).where(
        WebsiteCustomer.provider == identity.provider,
        WebsiteCustomer.external_user_id == identity.external_user_id,
    )
    row = session.scalar(query)
    if row is None:
        insert = postgres_insert if session.get_bind().dialect.name == "postgresql" else sqlite_insert
        session.execute(insert(WebsiteCustomer).values(
            id=str(uuid4()), provider=identity.provider, external_user_id=identity.external_user_id,
        ).on_conflict_do_nothing(index_elements=["provider", "external_user_id"]))
        row = session.scalar(query)
    owner = WebsiteOwner(customer_id=row.id, valid_until=identity.valid_until)
    owner.validate()
    return owner


def resolve_owner(session, visitor_id, identity: VerifiedCustomerIdentity | None = None):
    """Resolve at request entry, before loading or modifying consultation rows."""
    if identity is not None:
        owner = customer_owner(session, identity)
        session.commit()
        return owner
    if not visitor_id:
        raise HTTPException(404, "会话不存在或已过期")
    return WebsiteOwner(visitor_id=visitor_id)
