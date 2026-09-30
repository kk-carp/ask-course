"""BGE reranker：对检索候选重打分；启动时加载一次。关 rerank 时检索仍用 dense 分门控。"""

from __future__ import annotations

import logging
from dataclasses import replace
from threading import Lock
from typing import Any

from backend.config import settings
from backend.errors import ServiceUnavailableError
from backend.infra.retrieve import RetrievedChunk

_log = logging.getLogger("uvicorn.error")
_reranker_lock = Lock()
_reranker: Any | None = None


def load_reranker() -> None:
    """启动时加载一次 cross-encoder；关闭重排时跳过。"""
    global _reranker

    if not settings.retrieve_use_rerank:
        _log.info("rerank disabled (retrieve_use_rerank=false)")
        return
    if _reranker is not None:
        return

    with _reranker_lock:
        if _reranker is not None:
            return
        try:
            from sentence_transformers import CrossEncoder

            _log.info(
                "loading CrossEncoder(%s) — first run may download weights; this can take several minutes",
                settings.rerank_model,
            )
            _reranker = CrossEncoder(settings.rerank_model)
            _log.info("reranker ready")
        except Exception as exc:  # pragma: no cover - 依赖真实模型环境
            raise ServiceUnavailableError("重排模型加载失败") from exc


def is_loaded() -> bool:
    return _reranker is not None


def _ensure_reranker() -> Any:
    if _reranker is None:
        raise ServiceUnavailableError("重排模型未加载")
    return _reranker


def rerank(query: str, chunks: list[RetrievedChunk], top_k: int) -> list[RetrievedChunk]:
    """按 query-chunk 相关性重排，返回至多 top_k 条；score 为重排分。"""
    if top_k <= 0 or not chunks:
        return []
    text = (query or "").strip()
    if not text:
        return []

    model = _ensure_reranker()
    pairs = [(text, item.content) for item in chunks]
    try:
        scores = model.predict(pairs)
    except Exception as exc:  # pragma: no cover
        raise ServiceUnavailableError("重排打分失败") from exc

    scored = [
        replace(item, score=float(score))
        for item, score in zip(chunks, scores, strict=True)
    ]
    scored.sort(key=lambda item: item.score, reverse=True)
    return scored[:top_k]
