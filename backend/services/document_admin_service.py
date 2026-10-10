"""文档管理：列表、下线与删除已下线文档。不改动入库主链路。"""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select

from backend import db
from backend.errors import ServiceUnavailableError
from backend.models import Chunk, Document, DocumentReview, DocumentStatus, Space
from backend.services.document_file_service import resolve_stored_path
from backend.services.material_safety import REVIEW_CHECKS, inspect_material


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
    supersedes_id: str | None = None
    reviews: tuple[dict[str, str], ...] = ()


def _ensure_session():
    db.init_engine()
    if db.SessionLocal is None:
        raise ServiceUnavailableError("数据库会话未初始化")
    return db.SessionLocal


def _to_view(document: Document, chunk_count: int, reviews=()) -> DocumentView:
    return DocumentView(
        id=UUID(str(document.id)),
        title=document.title,
        space_id=document.space_id,
        course_id=document.course_id,
        status=document.status,
        chunk_count=chunk_count,
        error=document.error,
        supersedes_id=document.supersedes_id,
        reviews=tuple(reviews),
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
        reviews = {}
        for row in session.scalars(select(DocumentReview).order_by(DocumentReview.created_at)):
            reviews.setdefault(row.document_id, []).append({
                "actor_id": row.actor_id, "action": row.action, "note": row.note,
                "created_at": row.created_at.isoformat(),
            })
        return [_to_view(doc, int(chunk_counts.get(doc.id, 0)), reviews.get(doc.id, ())) for doc in documents]


def set_document_offline(document_id: str, *, actor_id: str = "system") -> DocumentView:
    """将文档置为 offline；检索只取 ready，因此下线后立即不可检。"""
    normalized = document_id.strip()
    if not normalized:
        raise ValueError("文档 ID 不能为空")

    SessionLocal = _ensure_session()
    with SessionLocal() as session:
        document = session.scalar(select(Document).where(Document.id == normalized).with_for_update())
        if document is None:
            raise ValueError("文档不存在")

        if document.status != DocumentStatus.offline.value:
            session.add(DocumentReview(document_id=normalized, actor_id=actor_id, action="withdraw", note="主动撤回"))
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


def set_documents_offline(document_ids: list[str], *, actor_id: str = "system") -> BatchOpResult:
    """批量下线；已下线或不存在的计入 skipped。"""
    ids = _normalize_ids(document_ids)
    SessionLocal = _ensure_session()
    done = 0
    skipped = 0
    with SessionLocal() as session:
        for document_id in sorted(ids):
            document = session.scalar(select(Document).where(Document.id == document_id).with_for_update())
            if document is None or document.status == DocumentStatus.offline.value:
                skipped += 1
                continue
            document.status = DocumentStatus.offline.value
            session.add(DocumentReview(document_id=document_id, actor_id=actor_id, action="withdraw", note="批量撤回"))
            document.error = None
            done += 1
        session.commit()
    return BatchOpResult(done=done, skipped=skipped)


def publish_document(document_id: str, *, actor_id: str, note: str, safety_checks: dict | None = None,
                     review_existing: bool = False) -> DocumentView:
    """Publish one reviewed candidate; replace its declared predecessor atomically."""
    if not note.strip():
        raise DocumentDeleteError(400, "请填写审核依据")
    if not safety_checks or any(safety_checks.get(key) is not True for key in REVIEW_CHECKS):
        raise DocumentDeleteError(400, "必须确认公开来源、无敏感资料、商业信息准确及无嵌入指令四项检查")
    factory = _ensure_session()
    with factory() as session:
        candidate = session.get(Document, document_id)
        if candidate is None:
            raise DocumentDeleteError(404, "文档不存在")
        session.scalar(select(Space).where(Space.id == candidate.space_id).with_for_update())
        ids = sorted({document_id, candidate.supersedes_id} - {None})
        records = {row.id: row for row in session.scalars(select(Document).where(Document.id.in_(ids))
                   .order_by(Document.id).with_for_update().execution_options(populate_existing=True))}
        candidate = records.get(document_id)
        if candidate is None:
            raise DocumentDeleteError(404, "文档已删除，请刷新列表")
        if candidate.status != ("ready" if review_existing else "pending"):
            raise DocumentDeleteError(409, "资料状态不支持此审核操作，请刷新列表")
        count = int(session.scalar(select(func.count(Chunk.id)).where(Chunk.document_id == document_id)) or 0)
        if not count:
            raise DocumentDeleteError(409, "资料无可用片段，不能发布")
        report = inspect_material([candidate.title, *session.scalars(select(Chunk.content)
                                  .where(Chunk.document_id == document_id).order_by(Chunk.chunk_index))])
        if not report["passed"]:
            codes = ", ".join(item["code"] for item in report["findings"])
            raise DocumentDeleteError(409, f"资料安全检查未通过（{codes}），请脱敏或移除敏感内容后重新上传")
        previous = records.get(candidate.supersedes_id)
        if candidate.supersedes_id and not review_existing:
            if (previous is None or previous.status != "ready" or previous.space_id != candidate.space_id
                    or previous.course_id != candidate.course_id):
                raise DocumentDeleteError(409, "原资料已变化或撤回，请重新核对，不能自动发布")
            previous.status = "offline"
            session.add(DocumentReview(document_id=previous.id, actor_id=actor_id, action="superseded",
                                       note=f"由 {document_id} 替代：{note.strip()}"))
            session.flush()
        duplicate = session.scalar(select(Document.id).where(Document.space_id == candidate.space_id,
                                   Document.content_hash == candidate.content_hash, Document.status == "ready",
                                   Document.id != document_id)) if candidate.content_hash is not None else None
        if duplicate:
            raise DocumentDeleteError(409, "相同内容已发布，请刷新列表")
        candidate.status = "ready"
        session.add(DocumentReview(document_id=document_id, actor_id=actor_id, action="publish",
                                   note=note.strip() + "\n安全规则2026-10-10通过；人工四项检查全部确认"))
        session.commit()
        return _to_view(candidate, count)


def inspect_document(document_id: str) -> dict:
    factory = _ensure_session()
    with factory() as session:
        document = session.get(Document, document_id)
        if document is None:
            raise DocumentDeleteError(404, "文档不存在")
        parts = session.scalars(select(Chunk.content).where(Chunk.document_id == document_id).order_by(Chunk.chunk_index))
        return inspect_material([document.title, *parts])


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
