"""官网在售课程列表。只读取 id、标题和一句简介，不入库课程正文。"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass

import httpx

from backend.config import settings

_log = logging.getLogger("backend.course_catalog")
_CACHE_SECONDS = 300.0
_cache: tuple[float, tuple[OfficialCourse, ...]] | None = None

_NON_TEXT = re.compile(r"[^\w\u4e00-\u9fff]+", re.UNICODE)
_LATIN = re.compile(r"[A-Za-z][A-Za-z0-9]{1,}")
_CJK_RUN = re.compile(r"[\u4e00-\u9fff]+")
_STOP_GRAMS = frozenset(
    {
        "课程",
        "实战",
        "基础",
        "入门",
        "实训",
        "训练",
        "工作",
        "作坊",
        "教程",
        "指南",
        "实践",
        "理论",
        "开发",
        "系统",
        "体验",
        "高校",
        "大学",
        "学生",
    }
)


@dataclass(frozen=True)
class OfficialCourse:
    course_id: str
    title: str
    description: str
    cover_url: str | None = None


def _optional_cover(raw: object) -> str | None:
    for key in ("cover_url", "cover", "image", "coverImage"):
        value = raw.get(key) if isinstance(raw, dict) else None
        if isinstance(value, str) and value.strip().startswith("https://"):
            return value.strip()
    return None


def parse_course_list(payload: object) -> tuple[OfficialCourse, ...]:
    """从课程列表 JSON 取出在售课。缺 id 或标题的条目丢掉。"""
    if not isinstance(payload, dict):
        return ()
    data = payload.get("data")
    raw_courses = data.get("courses") if isinstance(data, dict) else None
    if not isinstance(raw_courses, list):
        return ()

    courses: list[OfficialCourse] = []
    for item in raw_courses:
        if not isinstance(item, dict):
            continue
        course_id = str(item.get("id") or "").strip()
        title = item.get("title")
        if not course_id.isdigit() or course_id == "0":
            continue
        if not isinstance(title, str) or not title.strip():
            continue
        description = item.get("description")
        courses.append(
            OfficialCourse(
                course_id=course_id,
                title=title.strip(),
                description=description.strip() if isinstance(description, str) else "",
                cover_url=_optional_cover(item),
            )
        )
    return tuple(courses)


def load_official_courses(*, force_refresh: bool = False) -> tuple[OfficialCourse, ...]:
    """拉取官网课程列表。失败时沿用未过期缓存，否则返回空列表。"""
    global _cache
    base = (settings.course_list_url or "").strip()
    now = time.monotonic()
    if not force_refresh and _cache is not None and _cache[0] > now:
        return _cache[1]
    if not base:
        return ()

    courses: tuple[OfficialCourse, ...]
    try:
        with httpx.Client(
            timeout=settings.course_list_timeout_seconds,
            follow_redirects=False,
        ) as client:
            found: list[OfficialCourse] = []
            for page in range(1, 21):
                response = client.get(base, params={"page": page, "limit": 100})
                response.raise_for_status()
                batch = parse_course_list(response.json())
                found.extend(batch)
                if len(batch) < 100:
                    break
            courses = tuple({item.course_id: item for item in found}.values())
    except Exception:
        _log.warning("official course list lookup failed")
        return _cache[1] if not force_refresh and _cache is not None and _cache[0] > now else ()

    _cache = (now + _CACHE_SECONDS, courses)
    return courses


def clear_course_list_cache() -> None:
    global _cache
    _cache = None


def get_course_by_id(course_id: str) -> OfficialCourse | None:
    key = (course_id or "").strip()
    if not key:
        return None
    for item in load_official_courses():
        if item.course_id == key:
            return item
    return None


def expand_course_query(query: str) -> str:
    """宽泛领域映射到官网使用的具体方向，不改变原始目标。"""
    return query + " 机器人 四足 机械臂 巡检 机器狗" if "具身" in query else query


def search_related_courses(
    question: str,
    *,
    courses: tuple[OfficialCourse, ...] | list[OfficialCourse] | None = None,
    limit: int = 3,
) -> list[OfficialCourse]:
    """用问题里的词对标题做匹配。没有足够特征时返回空，不拿常见词硬配一门课。"""
    catalog = tuple(courses) if courses is not None else load_official_courses()
    query = (question or "").strip()
    if not query or not catalog or limit <= 0:
        return []

    # 官网标题常用具体机器人方向，所有推荐入口共用同一扩展。
    query = expand_course_query(query)

    features = [_title_features(item.title) for item in catalog]
    document_frequency: dict[str, int] = {}
    for grams in features:
        for gram in grams:
            document_frequency[gram] = document_frequency.get(gram, 0) + 1

    rare_limit = 3
    query_text = _normalize(query)
    ranked: list[tuple[float, int, OfficialCourse]] = []
    for index, item in enumerate(catalog):
        score = 0.0
        for gram in features[index]:
            if document_frequency[gram] > rare_limit:
                continue
            if gram.casefold() not in query_text:
                continue
            score += 1.0 + (len(gram) - 2) * 0.5
        if score <= 0:
            continue
        ranked.append((score, index, item))

    ranked.sort(key=lambda row: (-row[0], row[1]))
    return [item for _, _, item in ranked[:limit]]


def _normalize(text: str) -> str:
    return _NON_TEXT.sub("", text).casefold()


def _title_features(title: str) -> set[str]:
    features: set[str] = set()
    for token in _LATIN.findall(title):
        features.add(token.casefold())
    for run in _CJK_RUN.findall(title):
        for size in (2, 3):
            if len(run) < size:
                continue
            for start in range(len(run) - size + 1):
                gram = run[start : start + size]
                if gram in _STOP_GRAMS:
                    continue
                features.add(gram)
    return features
