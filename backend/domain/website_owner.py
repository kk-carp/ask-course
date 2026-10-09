"""Trusted website principals; external account IDs are never consultation keys."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

from backend.config import settings


def utcnow():
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class VerifiedCustomerIdentity:
    """Output of a server-side website verifier, never parsed from a request body."""

    provider: str
    external_user_id: str
    valid_until: datetime

    def validate(self):
        if (not self.provider.strip() or len(self.provider) > 64
                or not self.external_user_id.strip() or len(self.external_user_id) > 128):
            raise ValueError("Invalid verified website identity")
        if self.valid_until.tzinfo is None or self.valid_until <= utcnow():
            raise HTTPException(401, "官网身份已失效，请重新登录")


@dataclass(frozen=True)
class WebsiteOwner:
    visitor_id: str | None = None
    customer_id: str | None = None
    valid_until: datetime | None = None

    def __post_init__(self):
        if bool(self.visitor_id) == bool(self.customer_id):
            raise ValueError("A website principal must have exactly one owner")
        if self.customer_id and self.valid_until is None:
            raise ValueError("Customer principals require verified validity")

    def validate(self):
        if self.customer_id and (
            self.valid_until.tzinfo is None or self.valid_until <= utcnow()
        ):
            raise HTTPException(401, "官网身份已失效，请重新登录")

    @property
    def key(self):
        return f"customer:{self.customer_id}" if self.customer_id else self.visitor_id

    @property
    def retention(self):
        return (timedelta(days=settings.customer_consultation_days) if self.customer_id
                else timedelta(hours=settings.visitor_consultation_hours))

    def columns(self):
        self.validate()
        return {"visitor_id": self.visitor_id, "customer_id": self.customer_id,
                "source_visitor_id": self.visitor_id}


def as_owner(value: WebsiteOwner | str) -> WebsiteOwner:
    # Legacy service callers can supply a signed-cookie-derived guest ID only.
    owner = value if isinstance(value, WebsiteOwner) else WebsiteOwner(visitor_id=value)
    owner.validate()
    return owner
