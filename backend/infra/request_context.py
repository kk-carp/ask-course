"""请求编号：生成或透传 X-Request-ID，写入访问日志；不含请求正文与密钥。"""

import logging
import re
from contextvars import ContextVar, Token
from uuid import uuid4

from starlette.types import ASGIApp, Message, Receive, Scope, Send

_REQUEST_ID_HEADER = b"x-request-id"
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_request_id: ContextVar[str] = ContextVar("request_id", default="")
_access_log = logging.getLogger("backend.access")


def get_request_id() -> str:
    return _request_id.get()


def normalize_request_id(incoming: str) -> str:
    value = (incoming or "").strip()
    if _REQUEST_ID_RE.fullmatch(value):
        return value
    return str(uuid4())


def bind_request_id(value: str) -> Token[str]:
    return _request_id.set(value)


def reset_request_id(token: Token[str]) -> None:
    _request_id.reset(token)


class RequestIdMiddleware:
    """最外层贴编号：响应带回 X-Request-ID，访问日志只记方法、路径与状态。"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = ""
        for name, value in scope.get("headers") or []:
            if name == _REQUEST_ID_HEADER:
                incoming = value.decode("latin-1")
                break
        request_id = normalize_request_id(incoming)
        token = bind_request_id(request_id)
        status_code = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message.get("status") or 500)
                headers = list(message.get("headers") or [])
                headers.append((_REQUEST_ID_HEADER, request_id.encode("ascii")))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            method = scope.get("method", "")
            path = scope.get("path", "")
            _access_log.info(
                "request_id=%s method=%s path=%s status=%s",
                request_id,
                method,
                path,
                status_code,
            )
            reset_request_id(token)
