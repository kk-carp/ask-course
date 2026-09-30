"""按段装窗：空行分段后拼到 chunk_size；超长段再按句或窗口切。overlap 必须小于 chunk_size。"""

from __future__ import annotations

import re

_PARAGRAPH_RE = re.compile(r"\n\s*\n")
_SENTENCE_RE = re.compile(r"(?<=[。！？!?])")


def split_text(text: str, chunk_size: int = 800, overlap: int = 100) -> list[str]:
    """按段装窗切片；超长段先按句切，仍超长再用重叠窗口。丢弃空片段。"""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if overlap < 0:
        raise ValueError("overlap must be non-negative")
    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk_size")

    units: list[str] = []
    for paragraph in _paragraphs(text):
        units.extend(_split_overlong(paragraph, chunk_size, overlap))
    return _pack(units, chunk_size, overlap)


def _paragraphs(text: str) -> list[str]:
    normalized = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    parts: list[str] = []
    for part in _PARAGRAPH_RE.split(normalized):
        trimmed = part.strip("\n")
        if trimmed.strip():
            parts.append(trimmed)
    return parts


def _split_overlong(text: str, chunk_size: int, overlap: int) -> list[str]:
    if len(text) <= chunk_size:
        return [text]
    sentences = [item.strip() for item in _SENTENCE_RE.split(text) if item.strip()]
    if len(sentences) <= 1:
        return _window(text, chunk_size, overlap)
    units: list[str] = []
    for sentence in sentences:
        if len(sentence) <= chunk_size:
            units.append(sentence)
        else:
            units.extend(_window(sentence, chunk_size, overlap))
    return units


def _window(text: str, chunk_size: int, overlap: int) -> list[str]:
    if len(text) <= chunk_size:
        return [text]
    chunks: list[str] = []
    start = 0
    step = chunk_size - overlap
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        if chunk.strip():
            chunks.append(chunk)
        if end >= len(text):
            break
        start += step
    return chunks


def _pack(units: list[str], chunk_size: int, overlap: int) -> list[str]:
    if not units:
        return []

    chunks: list[str] = []
    start = 0
    total = len(units)
    while start < total:
        end = start
        length = 0
        while end < total:
            extra = len(units[end]) if end == start else 2 + len(units[end])
            if end > start and length + extra > chunk_size:
                break
            length += extra
            end += 1
        chunks.append("\n\n".join(units[start:end]))
        if end >= total:
            break
        next_start = end
        tail_len = 0
        index = end - 1
        while index > start:
            piece = len(units[index]) if tail_len == 0 else len(units[index]) + 2 + tail_len
            if piece > overlap:
                break
            tail_len = piece
            next_start = index
            index -= 1
        if next_start <= start:
            next_start = start + 1
        start = next_start
    return chunks
