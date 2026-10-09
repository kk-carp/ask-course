"""Fail-closed verification seam and transactional website customer creation."""

from uuid import uuid4
from datetime import timedelta
import re

from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from backend.config import settings
from backend.domain.website_owner import VerifiedCustomerIdentity, WebsiteOwner, utcnow
from backend.infra.website_identity_client import lookup_member
from backend.models import WebsiteCustomer


def verified_website_identity(request: Request) -> VerifiedCustomerIdentity | None:
    """Opt-in Bearer verifier. Only the upstream response establishes an ID.

    The switch stays off until website transport/revocation are confirmed. An
    absent credential is a guest; an invalid/unverifiable one never falls back.
    """
    authorization = request.headers.get("authorization")
    token = request.headers.get("token")
    if authorization is None and token is None:
        return None
    if not settings.website_identity_enabled:
        raise HTTPException(503, "官网身份验证尚未接通，请稍后重试")
    if (authorization is None or len(request.headers.getlist("authorization")) != 1
            or len(authorization) > 8192
            or not re.fullmatch(r"(?i:Bearer) [A-Za-z0-9._~+/-]+=*", authorization)):
        raise HTTPException(401, "官网凭证格式无效，请重新登录")
    if token is not None and (len(request.headers.getlist("token")) != 1
                              or token != authorization.split(" ", 1)[1]):
        raise HTTPException(401, "官网凭证不一致，请重新登录")
    member_id = lookup_member(authorization)

    def revalidate():
        if not settings.website_identity_enabled:
            raise HTTPException(503, "官网身份验证暂不可用，请稍后重试")
        if lookup_member(authorization) != member_id:
            raise HTTPException(401, "官网身份已变化，请重新登录")

    # /me has no documented expiry field. Bound this request locally and verify
    # remotely on later requests/writes/outputs; never decode an unsigned JWT.
    return VerifiedCustomerIdentity(
        settings.website_identity_provider, member_id,
        utcnow() + timedelta(seconds=settings.website_identity_max_request_seconds),
        revalidate=revalidate,
    )


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
    owner = WebsiteOwner(customer_id=row.id, valid_until=identity.valid_until,
                         revalidate=identity.revalidate)
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
