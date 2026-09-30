"""追问检索：仅当本轮像省略问句时，把上一轮用户原问拼进 query。不改空间过滤。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

FOLLOWUP_STARTS: tuple[str, ...] = (
    "那么",
    "那些",
    "这些",
    "这个",
    "那个",
    "还有",
    "另外",
    "还要",
    "那",
)

# 这类词通常表示本轮已是完整问题，即使很短也不拼接（避免换题时带上旧问）。
INDEPENDENT_MARKERS: tuple[str, ...] = (
    "是什么",
    "什么是",
    "怎么",
    "如何",
    "哪些",
    "是否",
)

SHORT_FOLLOWUP_MAX = 16
PREVIOUS_QUERY_MAX = 80


def last_user_question(history: Sequence[Any] | None) -> str | None:
    """取历史里最近一条非空用户问句；没有则返回 None。"""
    if not history:
        return None
    for item in reversed(list(history)):
        role, content = _role_and_content(item)
        if role != "user":
            continue
        text = (content or "").strip()
        if text:
            return text
    return None


def is_followup_question(question: str, previous_user_question: str | None) -> bool:
    current = (question or "").strip()
    previous = (previous_user_question or "").strip()
    if not current or not previous:
        return False
    if previous in current:
        return False
    if current.startswith(FOLLOWUP_STARTS):
        return True
    stripped = current.rstrip("？?！!。.")
    if stripped.endswith("呢"):
        return True
    if any(marker in current for marker in INDEPENDENT_MARKERS):
        return False
    return len(current) <= SHORT_FOLLOWUP_MAX


def expand_followup_query(question: str, previous_user_question: str | None) -> str:
    """追问则「上一问 + 本轮」；否则原样返回。"""
    current = (question or "").strip()
    previous = (previous_user_question or "").strip()
    if not current:
        return current
    if not is_followup_question(current, previous):
        return current
    prefix = previous[:PREVIOUS_QUERY_MAX].rstrip()
    if not prefix or current.startswith(prefix):
        return current
    return f"{prefix} {current}"


def _role_and_content(item: Any) -> tuple[str, str]:
    if isinstance(item, (tuple, list)) and len(item) >= 2:
        return str(item[0] or ""), str(item[1] or "")
    return str(getattr(item, "role", "") or ""), str(getattr(item, "content", "") or "")
