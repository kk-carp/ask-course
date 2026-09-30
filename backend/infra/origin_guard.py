"""prod 下校验带登录或游客 Cookie 的写请求来源，减轻 CSRF。local 不启用。"""

from __future__ import annotations

from urllib.parse import urlparse

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from backend.config import is_prod_env, settings

WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
REJECT_DETAIL = "请求来源不被允许"


def header_value(scope: Scope, name: bytes) -> str:
    for key, value in scope.get("headers") or []:
        if key == name:
            return value.decode("latin-1")
    return ""


def has_session_cookie(cookie_header: str, cookie_name: str) -> bool:
    prefix = cookie_name + "="
    for part in cookie_header.split(";"):
        if part.strip().startswith(prefix):
            return True
    return False


def origin_from_referer(referer: str) -> str:
    parsed = urlparse((referer or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


def request_origin(origin_header: str, referer_header: str) -> str:
    origin = (origin_header or "").strip()
    if origin and origin.lower() != "null":
        return origin
    return origin_from_referer(referer_header)


def host_of_origin(origin: str) -> str:
    parsed = urlparse((origin or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return ""
    return parsed.netloc.lower()


def hosts_match(origin: str, host_header: str) -> bool:
    origin_host = host_of_origin(origin)
    request_host = (host_header or "").strip().lower()
    return bool(origin_host) and bool(request_host) and origin_host == request_host


def should_check_origin(method: str, cookie_header: str) -> bool:
    if not is_prod_env():
        return False
    if method.upper() not in WRITE_METHODS:
        return False
    return has_session_cookie(cookie_header, settings.session_cookie_name) or has_session_cookie(cookie_header, settings.visitor_cookie_name)


def origin_allowed(origin_header: str, referer_header: str, host_header: str) -> bool:
    origin = request_origin(origin_header, referer_header)
    return hosts_match(origin, host_header)


class OriginGuardMiddleware:
    """只在 prod 拦截：带身份 Cookie 的写请求，Origin/Referer 必须与 Host 一致。"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = str(scope.get("method") or "")
        cookie = header_value(scope, b"cookie")
        if not should_check_origin(method, cookie):
            await self.app(scope, receive, send)
            return

        origin = header_value(scope, b"origin")
        referer = header_value(scope, b"referer")
        host = header_value(scope, b"host")
        if origin_allowed(origin, referer, host):
            await self.app(scope, receive, send)
            return

        response = JSONResponse({"detail": REJECT_DETAIL}, status_code=403)
        await response(scope, receive, send)
