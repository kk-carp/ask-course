"""只初始化课程知识空间和内部管理员；售前映射必须由运营维护。"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.config import settings
from backend.models import Space, SpaceMember, TopicOwner, User
from backend.services.auth_service import hash_password

P0_ADMIN_USERNAME = "p0_admin"


def _seed_course_space(session: Session) -> None:
    if session.get(Space, settings.course_space_id) is None:
        session.add(Space(id=settings.course_space_id, name=settings.course_space_name))


def _seed_admin_user(session: Session) -> None:
    existing = session.scalars(select(User).where(User.username == P0_ADMIN_USERNAME)).first()
    if existing is None:
        existing = User(
            username=P0_ADMIN_USERNAME,
            password_hash=hash_password(settings.demo_password),
            role="admin",
        )
        session.add(existing)
        session.flush()
    if existing.role == "teaching":
        existing.role = "admin"
    if session.get(SpaceMember, (existing.id, settings.course_space_id)) is None:
        session.add(SpaceMember(user_id=existing.id, space_id=settings.course_space_id))


def _remove_placeholder_owners(session: Session) -> None:
    """清掉旧演示种子，绝不删除运营后来填入的真实联系方式。"""
    for row in session.scalars(select(TopicOwner)).all():
        folded = row.contact.casefold()
        if folded.startswith("placeholder://") or "replace-with" in folded or "example." in folded:
            session.delete(row)


def seed_course_owners(session: Session) -> None:
    _seed_course_space(session)
    _seed_admin_user(session)
    _remove_placeholder_owners(session)
