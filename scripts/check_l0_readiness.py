"""离线检查 L0 上线资料是否齐全；无需数据库、模型或 API Key。"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.domain.course_content import inspect_course_content  # noqa: E402 — script entry point adds project root above
from scripts.import_course_owners import load_rows  # noqa: E402 — script entry point adds project root above

CATALOG_FIELDS = {
    "course_id",
    "course_name",
    "content_file",
    "content_owner",
    "effective_date",
    "status",
}


def _load_catalog(path: Path) -> list[dict[str, str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not payload:
        raise ValueError("课程目录必须是非空 JSON 数组")
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, raw in enumerate(payload, start=1):
        if not isinstance(raw, dict):
            raise TypeError(f"课程目录第 {index} 条必须是对象")
        missing = CATALOG_FIELDS - raw.keys()
        if missing:
            raise ValueError(f"课程目录第 {index} 条缺少字段：{', '.join(sorted(missing))}")
        row = {field: str(raw[field]).strip() for field in CATALOG_FIELDS}
        if row["course_id"] in seen:
            raise ValueError(f"课程 ID 重复：{row['course_id']}")
        if row["status"] not in {"active", "offline"}:
            raise ValueError(f"{row['course_id']} status 只能是 active 或 offline")
        date.fromisoformat(row["effective_date"])
        if not row["content_owner"]:
            raise ValueError(f"{row['course_id']} 缺少内容负责人")
        seen.add(row["course_id"])
        rows.append(row)
    return rows


def _resolve_content_path(raw_path: str) -> Path:
    path = (ROOT / raw_path).resolve()
    try:
        path.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise ValueError(f"内容文件不能位于仓库外：{raw_path}") from exc
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="检查 L0 课程内容与售前映射")
    parser.add_argument("--catalog", type=Path, required=True, help="课程目录 JSON")
    parser.add_argument("--owners", type=Path, required=True, help="课程—售前映射 JSON")
    args = parser.parse_args()

    failures: list[str] = []
    try:
        catalog = _load_catalog(args.catalog)
        owners = load_rows(args.owners)
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1

    owner_ids = {row["course_id"] for row in owners}
    active_ids = {row["course_id"] for row in catalog if row["status"] == "active"}

    for row in catalog:
        if row["status"] != "active":
            continue
        course_id = row["course_id"]
        try:
            content_path = _resolve_content_path(row["content_file"])
        except ValueError as exc:
            failures.append(str(exc))
            continue
        if not content_path.is_file():
            failures.append(f"{course_id} 内容文件不存在：{row['content_file']}")
            continue
        report = inspect_course_content(content_path.read_text(encoding="utf-8"))
        if report.complete:
            print(
                f"[PASS] {course_id} 内容完整，"
                f"{report.text_chars} 字，4/4 最低板块"
            )
        else:
            failures.append(f"{course_id}：{'；'.join(report.problems)}")

    for course_id in sorted(active_ids - owner_ids):
        failures.append(f"{course_id} 缺少真实售前映射")
    for course_id in sorted(owner_ids - active_ids):
        print(f"[WARN] {course_id} 有售前映射，但不在 active 课程目录中")

    if failures:
        print("\nL0 准出检查失败：")
        for item in failures:
            print(f"  - {item}")
        return 1

    print(f"\nL0 资料检查通过：{len(active_ids)} 门在售课程")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
