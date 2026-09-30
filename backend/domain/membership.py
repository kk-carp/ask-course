"""按登录用户的成员记录授权，仅允许课程空间。检索必须使用该列表，客户端不得指定 space_ids。"""

from sqlalchemy import select

from backend import db
from backend.config import settings
from backend.errors import ServiceUnavailableError
from backend.models import SpaceMember


def get_allowed_spaces_for_user(user_id: str) -> list[str]:
    """问答授权唯一入口：从 space_members 读取可检索空间。"""
    db.init_engine()
    if db.SessionLocal is None:
        raise ServiceUnavailableError("数据库会话未初始化")

    with db.SessionLocal() as session:
        spaces = list(
            session.scalars(
                select(SpaceMember.space_id).where(
                    SpaceMember.user_id == user_id,
                    SpaceMember.space_id == settings.course_space_id,
                )
            ).all()
        )
    return spaces
