"""SQLAlchemy 引擎与会话；启动时建表并初始化课程知识空间。

P0 改动（相对 FDE 源）：
1. 空间与种子由 `student`/`company` 改为单一 `courses` 课程空间；
2. 不再写入 FDE 的 student/employee/teaching 演示账号，改由 `seed_course_owners` 建立内部账号；
"""

from collections.abc import Generator
import logging

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from backend.config import settings
from backend.models import Base

_log = logging.getLogger("uvicorn.error")

engine: Engine | None = None
SessionLocal: sessionmaker[Session] | None = None


def init_engine() -> Engine:
    """根据配置创建 SQLAlchemy 引擎与会话工厂。"""
    global engine, SessionLocal

    if engine is None:
        engine = create_engine(settings.database_url, pool_pre_ping=True)
        SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    return engine


def _ensure_chunk_source_columns(current_engine: Engine) -> None:
    """已有库补齐 path；create_all 不会给旧表加列。"""
    if current_engine.dialect.name != "postgresql":
        return
    with current_engine.begin() as connection:
        connection.execute(
            text("ALTER TABLE chunks ADD COLUMN IF NOT EXISTS path VARCHAR(512)")
        )


def _ensure_document_content_hash(current_engine: Engine) -> None:
    """已有库补齐 documents.content_hash；同空间 ready/processing 不得重复哈希。"""
    if current_engine.dialect.name != "postgresql":
        return
    with current_engine.begin() as connection:
        connection.execute(
            text(
                "ALTER TABLE documents ADD COLUMN IF NOT EXISTS content_hash VARCHAR(64)"
            )
        )
        connection.execute(text("ALTER TABLE documents ADD COLUMN IF NOT EXISTS course_id VARCHAR(32)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_documents_course_id ON documents (course_id)"))
        connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ux_documents_space_hash_active "
                "ON documents (space_id, content_hash) "
                "WHERE status IN ('ready', 'processing') AND content_hash IS NOT NULL"
            )
        )


def _ensure_chunk_content_tsv(current_engine: Engine) -> None:
    """词法检索列 + GIN；对 content_tsv 为空的行按 jieba 分词回填。"""
    if current_engine.dialect.name != "postgresql":
        return
    with current_engine.begin() as connection:
        connection.execute(
            text("ALTER TABLE chunks ADD COLUMN IF NOT EXISTS content_tsv tsvector")
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_chunks_content_tsv ON chunks USING GIN (content_tsv)"
            )
        )

    from backend.infra.lexical import to_search_text

    if SessionLocal is None:
        return
    with SessionLocal() as session:
        rows = (
            session.execute(
                text("SELECT id, content FROM chunks WHERE content_tsv IS NULL")
            )
            .mappings()
            .all()
        )
        total = len(rows)
        if total:
            _log.info("backfill content_tsv for %s chunks", total)
        for index, row in enumerate(rows, start=1):
            search_text = to_search_text(row["content"] or "")
            if not search_text:
                continue
            session.execute(
                text(
                    """
                    UPDATE chunks
                    SET content_tsv = to_tsvector('simple', :search_text)
                    WHERE id = :id
                    """
                ),
                {"search_text": search_text, "id": row["id"]},
            )
            if index == 1 or index == total or index % 50 == 0:
                _log.info("content_tsv backfill %s/%s", index, total)
        session.commit()
        if total:
            _log.info("content_tsv backfill finished")


def _ensure_conversation_summary_columns(current_engine: Engine) -> None:
    """已有库补齐会话滚动摘要列（CE §3.1）。"""
    if current_engine.dialect.name != "postgresql":
        return
    with current_engine.begin() as connection:
        connection.execute(
            text(
                "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS context_summary TEXT"
            )
        )
        connection.execute(
            text(
                "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS "
                "summary_message_count INTEGER NOT NULL DEFAULT 0"
            )
        )


def _ensure_visitor_history_column(current_engine: Engine) -> None:
    if current_engine.dialect.name != "postgresql":
        return
    with current_engine.begin() as connection:
        connection.execute(
            text("ALTER TABLE visitor_consultations ADD COLUMN IF NOT EXISTS history_json TEXT NOT NULL DEFAULT '[]'")
        )


def init_db() -> None:
    """启用 pgvector、创建表结构，并初始化课程知识空间与课程—售前映射。"""
    current_engine = init_engine()

    # 仅在 PostgreSQL 下启用 pgvector 扩展。
    if current_engine.dialect.name == "postgresql":
        with current_engine.begin() as connection:
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

    Base.metadata.create_all(bind=current_engine)
    _ensure_chunk_source_columns(current_engine)
    _ensure_document_content_hash(current_engine)
    _ensure_chunk_content_tsv(current_engine)
    _ensure_conversation_summary_columns(current_engine)
    _ensure_visitor_history_column(current_engine)

    if SessionLocal is None:
        raise RuntimeError("Session factory is not initialized")

    with SessionLocal() as session:
        # 幂等：课程空间、内部账号、课程—售前映射；已有记录不覆盖。
        from backend.seed.course_owners import seed_course_owners

        seed_course_owners(session)
        session.commit()

    purge_expired_on_startup()


def purge_expired_on_startup() -> None:
    """启动时按配置清理一次过期会话；失败只记日志，不阻断启动。"""
    if SessionLocal is None:
        return
    try:
        from datetime import datetime, timezone

        from backend.services.retention_service import purge_expired

        with SessionLocal() as session:
            result = purge_expired(
                session,
                now=datetime.now(timezone.utc),
                retention_days=settings.data_retention_days,
            )
            session.commit()
        if result.conversations:
            _log.info(
                "purged expired data conversations=%s retention_days=%s",
                result.conversations,
                settings.data_retention_days,
            )
    except Exception:
        _log.exception("expired data purge failed")


def get_session() -> Generator[Session, None, None]:
    """为请求或服务调用提供数据库会话。"""
    if SessionLocal is None:
        raise RuntimeError("Database engine is not initialized")

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
