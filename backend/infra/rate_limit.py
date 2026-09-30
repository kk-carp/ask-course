"""进程内限流：登录按用户名+IP，问答按用户。超限返回 429，不是知识库未命中。"""

from collections import defaultdict, deque
import threading
import time

from fastapi import Request

from backend.config import settings

RATE_LIMIT_DETAIL = "请求过于频繁，请稍后再试。这不是知识库未命中。"

_lock = threading.Lock()
_hits: dict[str, deque[float]] = defaultdict(deque)


def reset() -> None:
    """测试用：清空计数。"""
    with _lock:
        _hits.clear()


def client_ip(request: Request) -> str:
    if request.client is None:
        return "unknown"
    return request.client.host or "unknown"


def allow(key: str, *, max_requests: int, window_seconds: float) -> bool:
    if max_requests <= 0:
        return True
    now = time.monotonic()
    cutoff = now - window_seconds
    with _lock:
        hits = _hits[key]
        while hits and hits[0] <= cutoff:
            hits.popleft()
        if len(hits) >= max_requests:
            return False
        hits.append(now)
        return True


def allow_login(username: str, ip: str) -> bool:
    key = f"login:{username.strip()}:{ip}"
    return allow(
        key,
        max_requests=settings.login_rate_max,
        window_seconds=float(settings.login_rate_window_seconds),
    )


def allow_ask(user_id: str) -> bool:
    key = f"ask:{user_id}"
    return allow(
        key,
        max_requests=settings.ask_rate_max,
        window_seconds=float(settings.ask_rate_window_seconds),
    )
