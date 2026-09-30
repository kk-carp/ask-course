"""官网游客身份：匿名 Cookie 用于限流，检索权限固定为服务端课程空间。

游客不具备资料或售前映射管理权限；登录用户按课程空间成员记录授权。
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from fastapi import Request, Response
from itsdangerous import BadSignature, URLSafeTimedSerializer

from backend.config import settings

# 游客身份用于课程问答与限流；课程售前由 handoff_service 统一解析。
GUEST_ROLE = "guest"


@dataclass(frozen=True)
class GuestContext:
    """游客上下文；字段命名对齐 FDE 的 AuthContext，便于上层统一处理。"""

    visitor_id: str
    allowed_spaces: tuple[str, ...]
    user_role: str
    user_id: None = None

    @property
    def is_guest(self) -> bool:
        return True


def read_visitor_id(request: Request) -> str | None:
    """读取匿名 id；仅从 Cookie 取，不接受请求体传入。"""
    value = request.cookies.get(settings.visitor_cookie_name)
    if not value:
        return None
    try:
        visitor_id = URLSafeTimedSerializer(settings.secret_key, salt="visitor-v1").loads(
            value, max_age=settings.visitor_cookie_max_age
        )
    except BadSignature:
        return None
    return visitor_id if isinstance(visitor_id, str) and len(visitor_id) == 32 else None


def issue_visitor_id(request: Request, response: Response) -> str:
    """复用已有匿名 id，否则签发一个新的并写回 Cookie。"""
    existing = read_visitor_id(request)
    if existing:
        return existing

    visitor_id = uuid4().hex
    response.set_cookie(
        key=settings.visitor_cookie_name,
        value=URLSafeTimedSerializer(settings.secret_key, salt="visitor-v1").dumps(visitor_id),
        max_age=settings.visitor_cookie_max_age,
        httponly=True,
        samesite="lax",
        secure=settings.app_env == "prod",
        path="/",
    )
    return visitor_id


def guest_context(visitor_id: str) -> GuestContext:
    """游客允许空间**写死在服务端**，不接受任何客户端输入。"""
    return GuestContext(
        visitor_id=visitor_id,
        allowed_spaces=(settings.course_space_id,),
        user_role=GUEST_ROLE,
    )
