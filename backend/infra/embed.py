"""BGE-M3 Embedding：进程启动时加载一次，请求内只做 encode，不重复加载模型。"""

from __future__ import annotations

import logging
from threading import Lock
from typing import Any

from backend.config import settings
from backend.errors import ServiceUnavailableError

_log = logging.getLogger("uvicorn.error")
_model_lock = Lock()
_model: Any | None = None


def load_model() -> None:
    """在应用启动时加载一次 BAAI/bge-m3 模型。"""
    global _model

    if _model is not None:
        return

    with _model_lock:
        if _model is not None:
            return
        try:
            import torch
            from sentence_transformers import SentenceTransformer

            if not torch.cuda.is_available():
                torch.set_num_threads(settings.embed_cpu_threads)
            _log.info("loading SentenceTransformer(%s) — first run may download weights", settings.embed_model)
            options = {"device": settings.embed_device}
            if settings.embed_revision:
                options["revision"] = settings.embed_revision
            candidate = SentenceTransformer(settings.embed_model, **options)
            dimension = (candidate.get_embedding_dimension() if hasattr(candidate, "get_embedding_dimension")
                         else candidate.get_sentence_embedding_dimension())
            if dimension != settings.embedding_dim:
                raise ServiceUnavailableError("模型输出维度与配置不一致")
            _model = candidate
            _log.info("embed model ready")
        except ServiceUnavailableError:
            raise
        except Exception as exc:  # pragma: no cover - 依赖真实模型环境
            raise ServiceUnavailableError("向量模型加载失败") from exc


def is_loaded() -> bool:
    return _model is not None


def _ensure_model() -> Any:
    if _model is None:
        raise ServiceUnavailableError("向量模型未加载")
    return _model


def _normalize_vectors(vectors: list[list[float]]) -> list[list[float]]:
    normalized: list[list[float]] = []
    for vector in vectors:
        norm = sum(item * item for item in vector) ** 0.5
        if norm == 0:
            normalized.append(vector)
            continue
        normalized.append([item / norm for item in vector])
    return normalized


def encode_documents(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []

    model = _ensure_model()
    if settings.embed_token_limit:
        if any(len(model.tokenizer.encode(t, add_special_tokens=True)) > settings.embed_token_limit for t in texts):
            raise ValueError("文档切片超过模型 token 上限")
    try:
        embeddings = model.encode(
            texts,
            batch_size=settings.embed_batch_size,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
    except TypeError:
        embeddings = model.encode(
            texts,
            batch_size=settings.embed_batch_size,
            convert_to_numpy=True,
        )
        return _normalize_vectors(embeddings.tolist())
    except Exception as exc:  # pragma: no cover
        raise ServiceUnavailableError("文档向量编码失败") from exc

    vectors = embeddings.tolist()
    if settings.embedding_dim and vectors and len(vectors[0]) != settings.embedding_dim:
        raise ServiceUnavailableError("向量维度与配置不一致")
    return vectors


def encode_query(question: str) -> list[float]:
    text = question.strip()
    if not text:
        raise ValueError("问题不能为空")

    text = settings.embed_query_instruction + text
    model = _ensure_model()
    if settings.embed_token_limit and len(model.tokenizer.encode(text, add_special_tokens=True)) > settings.embed_token_limit:
        raise ValueError("问题超过检索模型长度限制，请缩短问题")
    vectors = encode_documents([text])
    if not vectors:
        raise ServiceUnavailableError("问题向量编码失败")
    return vectors[0]
