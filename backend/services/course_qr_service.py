"""按官网课程 ID 读取售前二维码。不拉取、不入库课程正文。"""

from __future__ import annotations

import logging
import re
import time

import httpx

from backend.config import settings
from backend.schemas import OwnerInfo
from backend.services.topic_owner_service import is_usable_contact

_log = logging.getLogger("backend.course_qr")
_OFFICIAL_COURSE_ID = re.compile(r"^[1-9]\d{0,11}$")
_CACHE_SECONDS = 60.0
_cache: dict[str, tuple[float, OwnerInfo | None]] = {}


def parse_presale_qr(payload: object) -> tuple[str | None, str] | None:
    """从课程详情 JSON 取出标题和 pre_sale_service_qrcode。字段缺失则返回 None。"""
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    course = data.get("course") if isinstance(data, dict) else None
    if not isinstance(course, dict):
        return None
    qr = course.get("pre_sale_service_qrcode")
    if not isinstance(qr, str) or not qr.strip():
        return None
    title = course.get("title")
    topic_name = title.strip() if isinstance(title, str) and title.strip() else None
    return topic_name, qr.strip()


def lookup_official_presale(course_id: str) -> OwnerInfo | None:
    """数字课程 ID 才请求官网。失败、空字段或非图片地址都返回 None，交给后续路由。"""
    key = (course_id or "").strip()
    base = (settings.course_detail_url or "").strip().rstrip("/")
    if not base or not _OFFICIAL_COURSE_ID.fullmatch(key):
        return None

    cached = _cache.get(key)
    now = time.monotonic()
    if cached is not None and cached[0] > now:
        return cached[1]

    owner: OwnerInfo | None = None
    try:
        with httpx.Client(
            timeout=settings.course_detail_timeout_seconds,
            follow_redirects=False,
        ) as client:
            response = client.get(f"{base}/{key}")
        response.raise_for_status()
        parsed = parse_presale_qr(response.json())
    except Exception:
        _log.warning("official presale qr lookup failed course_id=%s", key)
        parsed = None

    if parsed is not None:
        topic_name, qr = parsed
        if is_usable_contact(qr):
            owner = OwnerInfo(
                configured=True,
                topic_key=key,
                topic_name=topic_name,
                name="课程顾问",
                contact=qr,
            )
    _cache[key] = (now + _CACHE_SECONDS, owner)
    return owner
