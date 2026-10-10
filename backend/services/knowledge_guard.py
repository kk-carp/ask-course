"""Fresh database checks; shared locks order output against committed withdrawal."""

from contextlib import contextmanager

from fastapi import HTTPException
from sqlalchemy import select

from backend import db
from backend.errors import ServiceUnavailableError
from backend.models import Document

WITHDRAWN_MESSAGE = "本次回答使用的资料已撤回，回答已停止，请重新提问或联系课程顾问。"


def evidence_ids(value):
    if isinstance(value, dict):
        return value.get("knowledge_document_ids") or [source["document_id"] for source in value.get("sources", [])]
    return getattr(value, "knowledge_document_ids", None) or [source.document_id for source in value.sources]


@contextmanager
def published_evidence(document_ids):
    ids = sorted({str(value) for value in document_ids})
    if not ids:
        yield
        return
    db.init_engine()
    if db.SessionLocal is None:
        raise ServiceUnavailableError("数据库会话未初始化")
    with db.SessionLocal() as session:
        rows = session.execute(select(Document.id, Document.status).where(Document.id.in_(ids))
                               .order_by(Document.id).with_for_update(read=True)).all()
        if len(rows) != len(ids) or any(status != "ready" for _, status in rows):
            raise HTTPException(409, WITHDRAWN_MESSAGE)
        # Hold only around output/persistence, never around model inference.
        yield


def ensure_published(document_ids):
    with published_evidence(document_ids):
        pass
