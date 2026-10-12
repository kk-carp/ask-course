"""管理课程目录：合并运营登记与已有资料，不改变公开推荐范围。"""

import json
import re
from pathlib import Path

from backend.config import settings
from backend.services.document_admin_service import list_documents

_ROOT = Path(__file__).resolve().parents[2]


def list_admin_courses() -> list[dict]:
    path = Path(settings.approved_course_catalog_path)
    if not path.is_absolute():
        path = _ROOT / path
    courses = {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload.get("courses", []) if isinstance(payload, dict) else []
    except (OSError, ValueError):
        rows = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        course_id = str(row.get("id", ""))
        title = row.get("title")
        if re.fullmatch(r"[0-9]{1,12}", course_id) and int(course_id) > 0 and isinstance(title, str) and title.strip():
            courses[course_id] = {"id": course_id, "title": title.strip(), "document_count": 0}
    for document in list_documents():
        course_id = document.course_id
        if not course_id:
            continue
        course = courses.setdefault(course_id, {
            "id": course_id, "title": f"课程 {course_id}（未登记名称）", "document_count": 0,
        })
        course["document_count"] += 1
    return sorted(courses.values(), key=lambda item: item["title"])
