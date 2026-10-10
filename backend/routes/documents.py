"""文档管理 HTTP：仅管理员。同步入库和数据库操作由 FastAPI 工作线程执行。"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from backend.config import settings
from backend.errors import ServiceUnavailableError
from backend.schemas import (
    DocumentBatchResult,
    DocumentIdListRequest,
    DocumentPublishRequest,
    DocumentResponse,
)
from backend.services.auth_service import can_manage_documents, load_auth_context
from backend.services.document_admin_service import (
    DocumentDeleteError,
    delete_offline_document,
    delete_offline_documents,
    list_documents,
    inspect_document,
    publish_document,
    set_document_offline,
    set_documents_offline,
)
from backend.services.document_file_service import DocumentFileError, open_document_file
from backend.services.ingest_service import DuplicateDocumentError, ingest_document

router = APIRouter(tags=["documents"])


def _require_document_manager(request: Request):
    """上传/列表/下线必须登录且具备文档管理权限。"""
    context = load_auth_context(request)
    if context is None:
        raise HTTPException(status_code=401, detail="未登录")
    if not can_manage_documents(context.user):
        raise HTTPException(status_code=403, detail="无文档管理权限")
    return context.user


def _to_response(
    *,
    document_id: UUID,
    title: str,
    space_id: str,
    course_id: str | None,
    status: str,
    chunk_count: int,
    error: str | None = None,
    supersedes_id: str | None = None,
    reviews=(),
) -> DocumentResponse:
    return DocumentResponse(
        id=document_id,
        title=title,
        space_id=space_id,
        course_id=course_id,
        status=status,
        chunk_count=chunk_count,
        error=error,
        supersedes_id=supersedes_id,
        reviews=list(reviews),
    )


@router.get("/documents", response_model=list[DocumentResponse])
def get_documents(request: Request) -> list[DocumentResponse]:
    """列出文档状态与失败原因；仅管理员。"""
    _require_document_manager(request)
    try:
        items = list_documents()
    except ServiceUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return [
        _to_response(
            document_id=item.id,
            title=item.title,
            space_id=item.space_id,
            course_id=item.course_id,
            status=item.status,
            chunk_count=item.chunk_count,
            error=item.error,
            supersedes_id=item.supersedes_id,
            reviews=item.reviews,
        )
        for item in items
    ]


@router.post("/documents", response_model=DocumentResponse, status_code=201)
def upload_document(
    request: Request,
    space: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
    replace: Annotated[str, Form()] = "",
    course_id: Annotated[str, Form()] = "",
    supersedes_id: Annotated[str, Form()] = "",
) -> DocumentResponse:
    """接收 multipart 文件与空间参数并入库；需登录且有管理权限。"""
    _require_document_manager(request)
    replace_existing = replace.strip().lower() in {"1", "true", "yes"}
    try:
        extra = {"supersedes_id": supersedes_id.strip()} if supersedes_id.strip() else {}
        result = ingest_document(file=file, space_id=space, replace=replace_existing, course_id=course_id.strip() or None, **extra)
    except DuplicateDocumentError as exc:
        raise HTTPException(status_code=409, detail=exc.to_detail()) from exc
    except ValueError as exc:
        detail = str(exc)
        if "exceeds max size" in detail:
            limit_mb = settings.max_upload_bytes / (1024 * 1024)
            raise HTTPException(
                status_code=413,
                detail=f"文件超过大小上限（{limit_mb:g} MB）",
            ) from exc
        if detail.startswith("Unsupported file extension"):
            raise HTTPException(
                status_code=400,
                detail="不支持该文件格式，请上传 Markdown / TXT / PDF / DOCX / PPTX",
            ) from exc
        raise HTTPException(status_code=400, detail=detail) from exc
    except ServiceUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="文档入库失败") from exc

    return _to_response(
        document_id=result.id,
        title=result.title,
        space_id=result.space_id,
        course_id=result.course_id,
        status=result.status,
        chunk_count=result.chunk_count,
        supersedes_id=supersedes_id.strip() or None,
    )


@router.post("/documents/batch-offline", response_model=DocumentBatchResult)
def batch_offline_documents(
    payload: DocumentIdListRequest, request: Request
) -> DocumentBatchResult:
    """批量下线；已下线或不存在的计入 skipped。"""
    user = _require_document_manager(request)
    try:
        result = set_documents_offline(payload.ids, actor_id=user.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ServiceUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return DocumentBatchResult(done=result.done, skipped=result.skipped)


@router.post("/documents/batch-delete", response_model=DocumentBatchResult)
def batch_delete_documents(
    payload: DocumentIdListRequest, request: Request
) -> DocumentBatchResult:
    """批量删除已下线文档；未下线或不存在的计入 skipped。"""
    _require_document_manager(request)
    try:
        result = delete_offline_documents(payload.ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ServiceUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return DocumentBatchResult(done=result.done, skipped=result.skipped)


@router.post("/documents/{document_id}/offline", response_model=DocumentResponse)
def offline_document(document_id: str, request: Request) -> DocumentResponse:
    """主动下线文档；下线后不得参与检索。"""
    user = _require_document_manager(request)
    try:
        result = set_document_offline(document_id, actor_id=user.id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ServiceUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return _to_response(
        document_id=result.id,
        title=result.title,
        space_id=result.space_id,
        course_id=result.course_id,
        status=result.status,
        chunk_count=result.chunk_count,
        error=result.error,
    )


@router.delete("/documents/{document_id}")
def delete_document(document_id: str, request: Request) -> dict[str, bool]:
    """删除已下线文档；ready 文档须先下线。"""
    _require_document_manager(request)
    try:
        delete_offline_document(document_id)
    except DocumentDeleteError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except ServiceUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"ok": True}


@router.post("/documents/{document_id}/publish", response_model=DocumentResponse)
def approve_document(document_id: str, payload: DocumentPublishRequest, request: Request) -> DocumentResponse:
    user = _require_document_manager(request)
    try:
        item = publish_document(document_id, actor_id=user.id, note=payload.note, safety_checks=payload.safety_checks)
    except DocumentDeleteError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc
    except ServiceUnavailableError as exc:
        raise HTTPException(503, str(exc)) from exc
    return _to_response(document_id=item.id, title=item.title, space_id=item.space_id,
                        course_id=item.course_id, status=item.status, chunk_count=item.chunk_count,
                        error=item.error, supersedes_id=item.supersedes_id)


@router.get("/documents/{document_id}/inspection")
def inspect_document_content(document_id: str, request: Request) -> dict:
    _require_document_manager(request)
    try:
        return inspect_document(document_id)
    except DocumentDeleteError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc
    except ServiceUnavailableError as exc:
        raise HTTPException(503, str(exc)) from exc


@router.post("/documents/{document_id}/review", response_model=DocumentResponse)
def review_existing_document(document_id: str, payload: DocumentPublishRequest, request: Request) -> DocumentResponse:
    user = _require_document_manager(request)
    try:
        item = publish_document(document_id, actor_id=user.id, note=payload.note,
                                safety_checks=payload.safety_checks, review_existing=True)
    except DocumentDeleteError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc
    except ServiceUnavailableError as exc:
        raise HTTPException(503, str(exc)) from exc
    return _to_response(document_id=item.id, title=item.title, space_id=item.space_id,
                        course_id=item.course_id, status=item.status, chunk_count=item.chunk_count)


@router.get("/documents/{document_id}/file")
def download_document_file(document_id: str, request: Request) -> FileResponse:
    """按空间权限打开原文；学员/员工只能下载自己能检索的空间。"""
    context = load_auth_context(request)
    if context is None:
        raise HTTPException(status_code=401, detail="未登录")
    try:
        path, download_name = open_document_file(document_id, context.allowed_spaces,
                                                 allow_unpublished=can_manage_documents(context.user))
    except DocumentFileError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except ServiceUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return FileResponse(path, filename=download_name)
