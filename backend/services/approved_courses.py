"""运营审核的可推荐课程。

状态边界（见 data/approved_courses.json）：
- approved：五项审核通过，可按适配筛选并生成购买入口
- recommendable：可进入推荐池展示课名/简介，购买仍须完整审核
- draft：仅登记与公开快照，不进入推荐；公开事实见 official_course_drafts
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from backend.config import settings
from backend.services.course_catalog_service import OfficialCourse, load_official_courses

_log = logging.getLogger("backend.approved_courses")
_ROOT = Path(__file__).resolve().parents[2]
_BASIS = {"none": 0, "basic": 1, "experienced": 2}
_PLACEHOLDERS = ("待填写", "待运营", "placeholder", "replace-with", "example.")
_REVIEW_CHECKS = (
    "sale_status_confirmed",
    "purchase_page_checked",
    "course_facts_checked",
    "course_content_checked",
    "presale_contact_checked",
)


@dataclass(frozen=True)
class ApprovedCourse:
    id: str
    title: str
    audience: str
    prerequisites: str
    goals: tuple[str, ...]
    goal_keywords: tuple[str, ...]
    requires_hardware: bool
    min_basis: str
    min_weekly_hours: int
    purchase_url: str
    source_url: str


def valid_purchase_url(url: str, course_id: str) -> bool:
    try:
        parsed = urlparse(url)
        return (
            parsed.scheme == "https"
            and parsed.hostname == "www.arborseek.com"
            and parsed.port in {None, 443}
            and parsed.path.rstrip("/") == f"/course/{course_id}"
            and not parsed.username
            and not parsed.password
            and not parsed.query
            and not parsed.fragment
        )
    except ValueError:
        return False


def parse_approved_courses(payload: object) -> tuple[ApprovedCourse, ...]:
    if not isinstance(payload, dict) or not isinstance(payload.get("courses"), list):
        return ()
    result: list[ApprovedCourse] = []
    seen: set[str] = set()
    for raw in payload["courses"]:
        if not isinstance(raw, dict) or raw.get("status") != "approved":
            continue
        checks = raw.get("review_checks")
        if not isinstance(checks, dict) or any(
            checks.get(key) is not True for key in _REVIEW_CHECKS
        ):
            continue
        course_id = str(raw.get("id", "")).strip()
        goals = raw.get("goals")
        keywords = raw.get("goal_keywords")
        if (
            not course_id.isdigit()
            or course_id == "0"
            or course_id in seen
            or raw.get("min_basis") not in _BASIS
            or type(raw.get("requires_hardware")) is not bool
            or type(raw.get("min_weekly_hours")) is not int
            or raw["min_weekly_hours"] <= 0
            or not isinstance(goals, list)
            or not goals
            or not isinstance(keywords, list)
            or not keywords
            or not all(isinstance(x, str) and x.strip() for x in goals + keywords)
        ):
            continue
        fields = (
            "title",
            "audience",
            "prerequisites",
            "purchase_url",
            "reviewer",
            "reviewed_at",
        )
        if not all(
            isinstance(raw.get(key), str) and raw[key].strip() for key in fields
        ):
            continue
        if any(
            marker in str(value).casefold()
            for value in [*(raw[key] for key in fields), *goals, *keywords]
            for marker in _PLACEHOLDERS
        ):
            continue
        try:
            date.fromisoformat(raw["reviewed_at"])
        except ValueError:
            continue
        url = raw["purchase_url"].strip()
        if not valid_purchase_url(url, course_id):
            continue
        result.append(
            ApprovedCourse(
                id=course_id,
                title=raw["title"].strip(),
                audience=raw["audience"].strip(),
                prerequisites=raw["prerequisites"].strip(),
                goals=tuple(x.strip() for x in goals),
                goal_keywords=tuple(x.strip() for x in keywords),
                requires_hardware=raw["requires_hardware"],
                min_basis=raw["min_basis"],
                min_weekly_hours=raw["min_weekly_hours"],
                purchase_url=url,
                source_url=f"https://www.arborseek.com/course/{course_id}",
            )
        )
        seen.add(course_id)
    return tuple(result)


def load_approved_courses(*, verify_live: bool = False) -> tuple[ApprovedCourse, ...]:
    path = Path(settings.approved_course_catalog_path)
    if not path.is_absolute():
        path = _ROOT / path
    try:
        parsed = parse_approved_courses(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        _log.warning("approved course catalog unavailable")
        return ()
    official = {
        item.course_id for item in load_official_courses(force_refresh=verify_live)
    }
    return tuple(item for item in parsed if item.id in official)


def load_recommendable_courses() -> tuple[OfficialCourse, ...]:
    """官网已公开且明确进入推荐池的课程；购买仍须单独通过完整审核。"""
    path = Path(settings.approved_course_catalog_path)
    if not path.is_absolute():
        path = _ROOT / path
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        allowed = {item.id for item in parse_approved_courses(payload)}
        allowed.update(
            str(row["id"])
            for row in payload["courses"]
            if isinstance(row, dict) and row.get("status") == "recommendable"
        )
    except (OSError, ValueError, KeyError, TypeError):
        return ()
    return tuple(
        item for item in load_official_courses() if item.course_id in allowed
    )


def get_approved_course(
    course_id: str, *, verify_live: bool = False
) -> ApprovedCourse | None:
    return next(
        (
            item
            for item in load_approved_courses(verify_live=verify_live)
            if item.id == course_id
        ),
        None,
    )


def basis_level(value: str) -> int:
    return _BASIS[value]
