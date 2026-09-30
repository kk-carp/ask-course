"""中文词法检索用的分词：jieba 切词后以空格连接，供 simple tsvector 使用。"""

from __future__ import annotations

import re

_TOKEN_RE = re.compile(r"\S+")


def to_search_text(text: str) -> str:
    """将原文切成空格分隔的检索文本；空输入返回空串。"""
    raw = (text or "").strip()
    if not raw:
        return ""
    try:
        import jieba
    except ImportError:
        # 无 jieba 时降级为空白分词，避免混合检索直接 500
        return " ".join(_TOKEN_RE.findall(raw))

    parts = [token.strip() for token in jieba.cut_for_search(raw) if token and token.strip()]
    if not parts:
        parts = _TOKEN_RE.findall(raw)
    return " ".join(parts)
