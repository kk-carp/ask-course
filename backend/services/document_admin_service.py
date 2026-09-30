"""文档管理：列表、下线与删除已下线文档。不改动入库主链路。"""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select

from backend import db
from backend.errors import ServiceUnavailableError
from backend.models import Chunk, Document, DocumentStatus
from backend.services.document_file_service import resolve_stored_path


class DocumentDeleteError(Exception):
    """删除失败：不存在或尚未下线。"""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True)
class DocumentView:
    id: UUID
    title: str
    space_id: str
    course_id: str | None
    status: str
    chunk_count: int
    error: str | None


def _ensure_session():
    db.init_engine()
    if db.SessionLocal is None:
        raise ServiceUnavailableError("数据库会话未初始化")
    return db.SessionLocal


def _to_view(document: Document, chunk_count: int) -> DocumentView:
    return DocumentView(
        id=UUID(str(document.id)),
        title=document.title,
        space_id=document.space_id,
        course_id=document.course_id,
        status=document.status,
        chunk_count=chunk_count,
        error=document.error,
    )


def list_documents() -> list[DocumentView]:
    """返回全部文档及切片数，供管理页查看状态与失败原因。"""
    SessionLocal = _ensure_session()
    with SessionLocal() as session:
        chunk_counts = dict(
            session.execute(
                select(Chunk.document_id, func.count(Chunk.id)).group_by(Chunk.document_id)
            ).all()
        )
        documents = list(
            session.scalars(select(Document).order_by(Document.created_at.desc())).all()
        )
        return [_to_view(doc, int(chunk_counts.get(doc.id, 0))) for doc in documents]


def set_document_offline(document_id: str) -> DocumentView:
    """将文档置为 offline；检索只取 ready，因此下线后立即不可检。"""
    normalized = document_id.strip()
    if not normalized:
        raise ValueError("文档 ID 不能为空")

    SessionLocal = _ensure_session()
    with SessionLocal() as session:
        document = session.get(Document, normalized)
        if document is None:
            raise ValueError("文档不存在")

        document.status = DocumentStatus.offline.value
        # 下线是主动运维动作，清掉上次入库失败信息，避免与 offline 语义混淆
        document.error = None
        session.commit()
        session.refresh(document)
        chunk_count = int(
            session.scalar(
                select(func.count(Chunk.id)).where(Chunk.document_id == document.id)
            )
            or 0
        )
        return _to_view(document, chunk_count)


def delete_offline_document(document_id: str) -> None:
    """仅删除已下线文档：去掉库记录（切片级联）和上传目录内的文件。"""
    normalized = document_id.strip()
    if not normalized:
        raise DocumentDeleteError(400, "文档 ID 不能为空")

    SessionLocal = _ensure_session()
    with SessionLocal() as session:
        document = session.get(Document, normalized)
        if document is None:
            raise DocumentDeleteError(404, "文档不存在")
        if document.status != DocumentStatus.offline.value:
            raise DocumentDeleteError(400, "只能删除已下线的文档")

        stored = resolve_stored_path(document.file_path)
        session.delete(document)
        session.commit()

    if stored is not None:
        stored.unlink(missing_ok=True)


MAX_BATCH_IDS = 100


@dataclass(frozen=True)
class BatchOpResult:
    done: int
    skipped: int


def _normalize_ids(document_ids: list[str]) -> list[str]:
    seen: list[str] = []
    for raw in document_ids:
        value = (raw or "").strip()
        if not value or value in seen:
            continue
        seen.append(value)
    if not seen:
        raise ValueError("文档 ID 不能为空")
    if len(seen) > MAX_BATCH_IDS:
        raise ValueError(f"一次最多处理 {MAX_BATCH_IDS} 条")
    return seen


def set_documents_offline(document_ids: list[str]) -> BatchOpResult:
    """批量下线；已下线或不存在的计入 skipped。"""
    ids = _normalize_ids(document_ids)
    SessionLocal = _ensure_session()
    done = 0
    skipped = 0
    with SessionLocal() as session:
        for document_id in ids:
            document = session.get(Document, document_id)
            if document is None or document.status == DocumentStatus.offline.value:
                skipped += 1
                continue
            document.status = DocumentStatus.offline.value
            document.error = None
            done += 1
        session.commit()
    return BatchOpResult(done=done, skipped=skipped)


def delete_offline_documents(document_ids: list[str]) -> BatchOpResult:
    """批量删除已下线文档；未下线或不存在的计入 skipped。"""
    ids = _normalize_ids(document_ids)
    SessionLocal = _ensure_session()
    done = 0
    skipped = 0
    files_to_unlink: list = []
    with SessionLocal() as session:
        for document_id in ids:
            document = session.get(Document, document_id)
            if document is None or document.status != DocumentStatus.offline.value:
                skipped += 1
                continue
            stored = resolve_stored_path(document.file_path)
            session.delete(document)
            files_to_unlink.append(stored)
            done += 1
        session.commit()
    for stored in files_to_unlink:
        if stored is not None:
            stored.unlink(missing_ok=True)
    return BatchOpResult(done=done, skipped=skipped)
