"""按登录用户允许空间打开原文；不做对象存储。"""

from pathlib import Path

from backend import db
from backend.config import settings
from backend.errors import ServiceUnavailableError
from backend.models import Document, DocumentStatus


class DocumentFileError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def resolve_stored_path(file_path: str) -> Path | None:
    """确认路径落在上传目录内且文件存在。"""
    try:
        path = Path(file_path).resolve()
        root = Path(settings.upload_dir).resolve()
    except OSError:
        return None
    if path != root and root not in path.parents:
        return None
    if not path.is_file():
        return None
    return path


def open_document_file(document_id: str, allowed_spaces: list[str]) -> tuple[Path, str]:
    """返回本地文件路径与下载名；无权限 403，不存在或不可用 404。"""
    db.init_engine()
    if db.SessionLocal is None:
        raise ServiceUnavailableError("数据库会话未初始化")

    with db.SessionLocal() as session:
        document = session.get(Document, document_id)
        if document is None:
            raise DocumentFileError(404, "文档不存在")
        if document.space_id not in allowed_spaces:
            raise DocumentFileError(403, "没有权限查看该文档")
        if document.status != DocumentStatus.ready.value:
            raise DocumentFileError(404, "文档不可下载")
        stored = resolve_stored_path(document.file_path)
        if stored is None:
            raise DocumentFileError(404, "文档文件不存在")
        download_name = document.title or stored.name
        return stored, download_name
