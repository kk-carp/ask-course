"""本地上传存储：校验扩展名与大小、净化文件名，写入 data/uploads/{space_id}/。不解析文件内容。"""

from dataclasses import dataclass
from pathlib import Path, PurePath
import re
import shutil
from uuid import uuid4

from fastapi import UploadFile

from backend.config import settings

ALLOWED_EXTENSIONS = {"md", "txt", "pdf", "docx", "pptx"}
ALLOWED_SPACES = {settings.course_space_id}


@dataclass(frozen=True)
class StoredFile:
    path: Path
    original_name: str
    size: int


def _sanitize_filename(filename: str) -> str:
    """只净化文件名中的非法字符，必须保留扩展名。

    旧实现整串 strip('._')，中文名（如「课程简介.md」）会被洗成纯下划线再把
    `.md` 一起剥掉，入库解析就变成空扩展名。
    """
    base_name = PurePath(filename).name
    suffix = Path(base_name).suffix.lower()
    stem = base_name[: len(base_name) - len(suffix)] if suffix else base_name
    cleaned_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._") or "upload"
    cleaned_suffix = re.sub(r"[^A-Za-z0-9.]+", "", suffix)
    return f"{cleaned_stem}{cleaned_suffix}"


def _get_extension(filename: str) -> str:
    return Path(filename).suffix.lower().lstrip(".")


def save_upload(
    file: UploadFile,
    space_id: str,
) -> StoredFile:
    """校验、净化并保存上传文件到 data/uploads/{space_id}/。"""
    if space_id not in ALLOWED_SPACES:
        raise ValueError(f"Unsupported space_id: {space_id!r}")

    filename = file.filename or ""
    if not filename:
        raise ValueError("Missing upload filename")

    extension = _get_extension(filename)
    if extension not in ALLOWED_EXTENSIONS:
        raise ValueError(f"Unsupported file extension: {extension!r}")

    raw_file = file.file
    current_offset = raw_file.tell()
    raw_file.seek(0, 2)
    size = raw_file.tell()
    raw_file.seek(0)
    if size > settings.max_upload_bytes:
        limit_mb = settings.max_upload_bytes / (1024 * 1024)
        raise ValueError(f"File exceeds max size ({limit_mb:g} MB)")

    upload_root = Path(settings.upload_dir)
    target_dir = upload_root / space_id
    target_dir.mkdir(parents=True, exist_ok=True)

    safe_name = _sanitize_filename(filename)
    stored_name = f"{uuid4()}_{safe_name}"
    target_path = target_dir / stored_name

    with target_path.open("wb") as output:
        shutil.copyfileobj(raw_file, output)
    raw_file.seek(current_offset)

    return StoredFile(path=target_path, original_name=filename, size=size)

