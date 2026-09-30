"""按允许空间在 SQL WHERE 中过滤后召回切片；支持 dense / 混合检索，可选重排。禁止全量检索后再在 Python 中过滤。"""

from __future__ import annotations

from dataclasses import dataclass, replace
from uuid import UUID

from sqlalchemy import text

from backend import db
from backend.config import settings
from backend.errors import ServiceUnavailableError
from backend.infra.lexical import to_search_text


@dataclass(frozen=True)
class RetrievedChunk:
    content: str
    score: float
    document_id: UUID
    title: str
    space_id: str
    path: str | None = None
    chunk_id: UUID | None = None
    dense_score: float | None = None


def _chunk_key(item: RetrievedChunk) -> str:
    if item.chunk_id is not None:
        return str(item.chunk_id)
    return f"{item.document_id}:{item.content[:64]}"


def _row_to_chunk(row: dict, *, score: float, dense_score: float | None = None) -> RetrievedChunk:
    return RetrievedChunk(
        content=row["content"],
        score=float(score),
        document_id=UUID(str(row["document_id"])),
        title=row["title"],
        space_id=row["space_id"],
        path=row["path"],
        chunk_id=UUID(str(row["chunk_id"])) if row.get("chunk_id") is not None else None,
        dense_score=None if dense_score is None else float(dense_score),
    )


def search_dense(
    query_vector: list[float],
    allowed_spaces: list[str],
    top_k: int,
    course_id: str | None = None,
) -> list[RetrievedChunk]:
    """SQL 中先按空间过滤，再做向量排序。"""
    if not allowed_spaces:
        return []
    if top_k <= 0:
        return []
    if not query_vector:
        raise ValueError("query_vector 不能为空")

    db.init_engine()
    if db.SessionLocal is None:
        raise ServiceUnavailableError("数据库会话未初始化")

    vector_literal = "[" + ",".join(f"{value:.10f}" for value in query_vector) + "]"
    spaces_literal = "{" + ",".join(allowed_spaces) + "}"

    sql = text(
        """
        SELECT
            chunks.id AS chunk_id,
            chunks.content AS content,
            1 - (chunks.embedding <=> CAST(:query_vector AS vector)) AS score,
            documents.id AS document_id,
            documents.title AS title,
            chunks.space_id AS space_id,
            chunks.path AS path
        FROM chunks
        JOIN documents ON documents.id = chunks.document_id
        WHERE chunks.space_id = ANY(CAST(:allowed_spaces AS text[]))
          AND documents.status = 'ready'
          AND (:course_id = '' OR documents.course_id = :course_id)
        ORDER BY chunks.embedding <=> CAST(:query_vector AS vector)
        LIMIT :top_k
        """
    )
    # 仅 ready 可检索：failed/offline/processing 均被排除，勿在 Python 层再过滤全量结果

    with db.SessionLocal() as session:
        rows = session.execute(
            sql,
            {
                "query_vector": vector_literal,
                "allowed_spaces": spaces_literal,
                "top_k": top_k,
                "course_id": course_id or "",
            },
        ).mappings()
        return [
            _row_to_chunk(row, score=float(row["score"]), dense_score=float(row["score"]))
            for row in rows
        ]


def search_lexical(
    query_text: str,
    allowed_spaces: list[str],
    top_k: int,
    course_id: str | None = None,
) -> list[RetrievedChunk]:
    """词法召回：jieba 分词 + content_tsv @@ plainto_tsquery('simple', ...)。"""
    if not allowed_spaces:
        return []
    if top_k <= 0:
        return []

    search_text = to_search_text(query_text)
    if not search_text:
        return []

    db.init_engine()
    if db.SessionLocal is None:
        raise ServiceUnavailableError("数据库会话未初始化")

    spaces_literal = "{" + ",".join(allowed_spaces) + "}"
    sql = text(
        """
        SELECT
            chunks.id AS chunk_id,
            chunks.content AS content,
            ts_rank_cd(chunks.content_tsv, query) AS score,
            documents.id AS document_id,
            documents.title AS title,
            chunks.space_id AS space_id,
            chunks.path AS path
        FROM chunks
        JOIN documents ON documents.id = chunks.document_id
        CROSS JOIN plainto_tsquery('simple', :search_text) AS query
        WHERE chunks.space_id = ANY(CAST(:allowed_spaces AS text[]))
          AND documents.status = 'ready'
          AND (:course_id = '' OR documents.course_id = :course_id)
          AND chunks.content_tsv IS NOT NULL
          AND chunks.content_tsv @@ query
        ORDER BY score DESC
        LIMIT :top_k
        """
    )

    with db.SessionLocal() as session:
        rows = session.execute(
            sql,
            {
                "search_text": search_text,
                "allowed_spaces": spaces_literal,
                "top_k": top_k,
                "course_id": course_id or "",
            },
        ).mappings()
        return [_row_to_chunk(row, score=float(row["score"]), dense_score=None) for row in rows]


def fuse_rrf(
    rank_lists: list[list[RetrievedChunk]],
    rrf_k: int,
) -> list[RetrievedChunk]:
    """按 chunk 去重做 RRF；返回的 score 为融合分，保留已有 dense_score。"""
    if rrf_k <= 0:
        raise ValueError("rrf_k 必须为正整数")

    fused: dict[str, RetrievedChunk] = {}
    scores: dict[str, float] = {}

    for rank_list in rank_lists:
        for rank, item in enumerate(rank_list, start=1):
            key = _chunk_key(item)
            scores[key] = scores.get(key, 0.0) + 1.0 / (rrf_k + rank)
            existing = fused.get(key)
            if existing is None:
                fused[key] = item
                continue
            dense = existing.dense_score
            if dense is None and item.dense_score is not None:
                fused[key] = replace(existing, dense_score=item.dense_score)

    ordered = sorted(fused.values(), key=lambda item: scores[_chunk_key(item)], reverse=True)
    return [
        replace(item, score=scores[_chunk_key(item)])
        for item in ordered
    ]


def hybrid_search(
    query_text: str,
    query_vector: list[float],
    allowed_spaces: list[str],
    *,
    candidate_k: int,
    rrf_k: int,
    use_lexical: bool,
    course_id: str | None = None,
) -> list[RetrievedChunk]:
    dense_hits = search_dense(query_vector, allowed_spaces, candidate_k, course_id=course_id)
    if not use_lexical:
        return dense_hits
    lexical_hits = search_lexical(query_text, allowed_spaces, candidate_k, course_id=course_id)
    if not lexical_hits:
        return dense_hits
    if not dense_hits:
        return lexical_hits
    return fuse_rrf([dense_hits, lexical_hits], rrf_k=rrf_k)


def _apply_dense_scores_for_gate(chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    """关 rerank 时：展示/门控分用 dense；纯词法命中 score=0。"""
    return [
        replace(
            item,
            score=0.0 if item.dense_score is None else float(item.dense_score),
        )
        for item in chunks
    ]


def run_retrieval(
    query_text: str,
    query_vector: list[float],
    allowed_spaces: list[str],
    course_id: str | None = None,
) -> list[RetrievedChunk]:
    """混合召回 → 可选重排 → 阈值门控；供问答与进阶资料推荐共用。"""
    if not allowed_spaces:
        return []

    candidate_k = settings.retrieve_candidate_k if settings.retrieve_use_hybrid else settings.retrieve_top_k
    if settings.retrieve_use_rerank:
        candidate_k = max(candidate_k, settings.rerank_candidates)

    candidates = hybrid_search(
        query_text=query_text,
        query_vector=query_vector,
        allowed_spaces=allowed_spaces,
        candidate_k=candidate_k,
        rrf_k=settings.retrieve_rrf_k,
        use_lexical=settings.retrieve_use_hybrid,
        course_id=course_id,
    )
    if not candidates:
        return []

    if settings.retrieve_use_rerank:
        from backend.infra.rerank import rerank

        pool = candidates[: settings.rerank_candidates]
        retrieved = rerank(query_text, pool, settings.retrieve_top_k)
        gate = settings.rerank_min_score
    else:
        retrieved = _apply_dense_scores_for_gate(candidates)[: settings.retrieve_top_k]
        gate = settings.retrieve_min_score

    if not retrieved:
        return []
    top_score = max(item.score for item in retrieved)
    if top_score < gate:
        return []
    return retrieved


def search_chunks(
    query_vector: list[float],
    allowed_spaces: list[str],
    top_k: int,
) -> list[RetrievedChunk]:
    """兼容入口：等价于仅 dense、截断到 top_k（不含词法/重排/门控）。"""
    return search_dense(query_vector, allowed_spaces, top_k)
