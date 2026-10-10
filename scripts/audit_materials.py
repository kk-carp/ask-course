"""只读检查课程资料；输出规则编号，不输出敏感原文。规则通过不等于业务审核通过。"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from backend import db
from backend.models import Chunk, Document, DocumentReview
from backend.services.material_safety import inspect_material


def audit_files(paths: list[Path]) -> list[dict]:
    reports = []
    for path in paths:
        if not path.exists():
            reports.append({"file": str(path), "passed": False, "error": "missing"})
            continue
        files = sorted(path.rglob("*")) if path.is_dir() else [path]
        for file in files:
            if file.is_file() and file.suffix.lower() in {".md", ".txt", ".json", ".jsonl"}:
                try:
                    result = inspect_material([file.read_text(encoding="utf-8")])
                except (OSError, UnicodeError):
                    result = {"passed": False, "error": "unreadable"}
                reports.append({"file": str(file), **result})
    return reports


def audit_database() -> list[dict]:
    db.init_engine()
    with db.SessionLocal() as session:
        docs = session.execute(select(Document.id, Document.title, Document.status)
                               .where(Document.status.in_(["ready", "pending"]))).all()
        reports = []
        for document_id, title, status in docs:
            parts = session.scalars(select(Chunk.content).where(Chunk.document_id == document_id).order_by(Chunk.chunk_index))
            reports.append({"document_id": document_id, "status": status, **inspect_material([title, *parts])})
        try:
            reviewed = set(session.scalars(select(DocumentReview.document_id).where(
                DocumentReview.action == "publish",
                DocumentReview.note.contains("安全规则2026-10-10通过；人工四项检查全部确认"))))
        except SQLAlchemyError:
            session.rollback()
            reviewed = set()
        for row in reports:
            row["has_publication_record"] = row["document_id"] in reviewed
            if row["status"] == "ready" and not row["has_publication_record"]:
                row["passed"] = False
                row["requires_human_review"] = True
        return reports


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", action="store_true", help="只读检查当前配置数据库的已发布和待审核资料")
    parser.add_argument("--files", nargs="*", default=["data/course_facts.json", "data/approved_courses.json", "data/course_content"])
    parser.add_argument("--output", default="data/operations/material-audit.json")
    args = parser.parse_args()
    rows = audit_files([Path(value) for value in args.files])
    database_error = False
    if args.database:
        try:
            rows.extend(audit_database())
        except (SQLAlchemyError, ValueError, OSError):
            # Connection failures can contain passwords; never echo the exception.
            database_error = True
    report = {"rule_version": "2026-10-10", "automatic_check_only": True,
              "database_checked": args.database and not database_error, "database_error": database_error,
              "checked": len(rows), "flagged": sum(not row["passed"] for row in rows), "items": rows}
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "items"}, ensure_ascii=False))
    return int(database_error or report["flagged"] > 0 or not rows)


if __name__ == "__main__":
    raise SystemExit(main())
