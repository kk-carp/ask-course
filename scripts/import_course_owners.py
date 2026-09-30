"""校验并批量导入真实课程—售前映射。

用法：
    python scripts/import_course_owners.py data/course_owners.example.json --check
    python scripts/import_course_owners.py path/to/course_owners.json --apply
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.services.topic_owner_service import (  # noqa: E402 — script entry point adds project root above
    TopicOwnerError,
    upsert_topic_owner,
    validate_topic_owner_fields,
)

REQUIRED_FIELDS = {"course_id", "course_name", "keywords", "owner_name", "contact"}


def load_rows(path: Path) -> list[dict[str, str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not payload:
        raise ValueError("映射文件必须是非空 JSON 数组")

    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, raw in enumerate(payload, start=1):
        if not isinstance(raw, dict):
            raise TypeError(f"第 {index} 条必须是对象")
        missing = REQUIRED_FIELDS - raw.keys()
        if missing:
            raise ValueError(f"第 {index} 条缺少字段：{', '.join(sorted(missing))}")
        row = {field: str(raw[field]).strip() for field in REQUIRED_FIELDS}
        validate_topic_owner_fields(
            topic_key=row["course_id"],
            topic_name=row["course_name"],
            name=row["owner_name"],
            contact=row["contact"],
        )
        key = row["course_id"]
        if key in seen:
            raise ValueError(f"课程 ID 重复：{key}")
        seen.add(key)
        rows.append(row)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="校验或导入课程—售前映射")
    parser.add_argument("file", type=Path, help="JSON 映射文件")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="只校验，不写数据库")
    mode.add_argument("--apply", action="store_true", help="校验通过后写数据库")
    args = parser.parse_args()

    try:
        rows = load_rows(args.file)
    except (OSError, json.JSONDecodeError, TypeError, ValueError, TopicOwnerError) as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1

    print(f"[PASS] 映射文件有效：{len(rows)} 门课程")
    if args.check:
        return 0

    for row in rows:
        upsert_topic_owner(
            topic_key=row["course_id"],
            topic_name=row["course_name"],
            keywords=row["keywords"],
            name=row["owner_name"],
            contact=row["contact"],
        )
        print(f"[UPSERT] {row['course_id']} -> {row['owner_name']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
