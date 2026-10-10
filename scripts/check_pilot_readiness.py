"""预发布准出检查。缺少真实运营数据时明确失败，不自动开放灰度。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend import db  # noqa: E402
from backend.config import settings  # noqa: E402
from backend.domain.course_content import inspect_course_content  # noqa: E402
from backend.models import Document, DocumentStatus, TopicOwner  # noqa: E402
from backend.services.approved_courses import get_approved_course  # noqa: E402
from backend.services.course_qr_service import lookup_official_presale  # noqa: E402
from backend.services.topic_owner_service import is_usable_contact  # noqa: E402
from scripts.audit_materials import audit_database, audit_files


def _content_complete(course_id: str, catalog_path: Path) -> bool:
    try:
        rows = json.loads(catalog_path.read_text(encoding="utf-8"))
        row = next(
            x
            for x in rows
            if str(x.get("course_id")) == course_id and x.get("status") == "active"
        )
        path = (ROOT / row["content_file"]).resolve()
        path.relative_to(ROOT)
        return inspect_course_content(path.read_text(encoding="utf-8")).complete
    except (OSError, ValueError, TypeError, KeyError, StopIteration):
        return False


def _contact_reachable(client: httpx.Client, contact: str) -> bool:
    image = Path(httpx.URL(contact).path).suffix.lower() in {
        ".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg",
    }
    try:
        with client.stream("GET", contact) as response:
            if image:
                return response.status_code == 200 and response.headers.get("content-type", "").startswith("image/")
            return 200 <= response.status_code < 400
    except httpx.HTTPError:
        return False


def check(*, verify_http: bool = True) -> list[str]:
    failures: list[str] = []
    if not settings.privacy_reviewed or not all(value.strip() for value in (
        settings.privacy_operator, settings.privacy_contact, settings.privacy_model_provider,
    )):
        failures.append("隐私运营主体、联系渠道及模型服务商尚未完成确认")
    if len(settings.monitoring_token) < 32:
        failures.append("缺少独立监控凭证")
    if min(settings.monitoring_daily_budget, settings.monitoring_input_price_per_million,
           settings.monitoring_output_price_per_million) <= 0:
        failures.append("模型计费单价或每日预算尚未配置")
    try:
        inspected = audit_files([ROOT / "data/course_facts.json", ROOT / "data/approved_courses.json", ROOT / "data/course_content"])
        inspected.extend(audit_database())
        if any(not row["passed"] for row in inspected):
            failures.append("资料安全扫描或历史资料人工复核尚未通过；运行 scripts/audit_materials.py --database 查看")
    except (SQLAlchemyError, ValueError, OSError, RuntimeError):
        failures.append("无法完成资料安全检查（需先迁移数据库并检查连接）")
    ids = [x.strip() for x in settings.pilot_course_ids.split(",") if x.strip()]
    if not ids:
        failures.append("PILOT_COURSE_IDS 未配置")
    if not 0 <= settings.pilot_percent <= 100:
        failures.append("PILOT_PERCENT 必须为 0–100")
    if settings.course_content_validation_mode != "strict":
        failures.append("课程资料校验必须为 strict")
    if not is_usable_contact(settings.handoff_fallback_contact):
        failures.append("备用售前联系方式未配置")
    gold_path = ROOT / "data" / "eval" / "pilot_gold.jsonl"
    try:
        gold = [
            json.loads(line)
            for line in gold_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        required_topics = {"audience", "outline", "schedule", "certificate"}
        for course_id in ids:
            topics = {
                row.get("topic")
                for row in gold
                if str(row.get("course_id")) == course_id
                and row.get("require_sources") is True
            }
            if not required_topics <= topics:
                failures.append(
                    f"{course_id} 金标集缺少适合人群、目录、安排或证书的有来源案例"
                )
    except (OSError, ValueError):
        failures.append("缺少真实课程金标集 data/eval/pilot_gold.jsonl")

    try:
        db.init_engine()
    except Exception:
        return failures + ["数据库连接配置不可用"]
    if db.SessionLocal is None:
        return failures + ["数据库未配置"]
    content_catalog = ROOT / "data" / "course_catalog.json"
    try:
        with db.SessionLocal() as session:
            for course_id in ids:
                course = get_approved_course(course_id, verify_live=True)
                if course is None:
                    failures.append(f"{course_id} 不在运营审核且官网在售的课程交集中")
                    continue
                if not _content_complete(course_id, content_catalog):
                    failures.append(f"{course_id} 课程正文未通过四板块校验")
                indexed = session.scalars(
                    select(Document).where(
                        Document.course_id == course_id,
                        Document.status == DocumentStatus.ready.value,
                    )
                ).first()
                if indexed is None:
                    failures.append(f"{course_id} 未找到带 course_id 的可检索课程正文")
                owner = session.get(TopicOwner, course_id)
                qr = lookup_official_presale(course_id)
                contacts = [
                    x
                    for x in (
                        qr.contact if qr else None,
                        owner.contact if owner else None,
                    )
                    if is_usable_contact(x)
                ]
                if not contacts:
                    failures.append(f"{course_id} 缺少课程专属售前联系方式")
                if verify_http:
                    with httpx.Client(timeout=5, follow_redirects=False) as client:
                        try:
                            response = client.get(course.purchase_url)
                            if response.status_code != 200:
                                failures.append(
                                    f"{course_id} 官网购买页 HTTP {response.status_code}"
                                )
                        except httpx.HTTPError as exc:
                            failures.append(
                                f"{course_id} 官网购买页请求失败：{type(exc).__name__}"
                            )
                        for contact in contacts:
                            if not _contact_reachable(client, contact):
                                failures.append(f"{course_id} 售前联系方式不可读取")
                        if is_usable_contact(settings.handoff_fallback_contact) and not _contact_reachable(client, settings.handoff_fallback_contact):
                            failures.append("备用售前联系方式不可读取")
    except Exception:
        failures.append("数据库查询或官网资料核验失败")
    return list(dict.fromkeys(failures))


def main() -> int:
    parser = argparse.ArgumentParser(description="检查官网售前 Agent 灰度准出条件")
    parser.add_argument(
        "--skip-http",
        action="store_true",
        help="仅做本地静态检查；不能作为最终上线准出",
    )
    args = parser.parse_args()
    failures = check(verify_http=not args.skip_http)
    for message in failures:
        print(f"[FAIL] {message}")
    if failures:
        return 1
    print("[PASS] 自动检查通过；还需人工验收购买按钮、售前二维码和桌面/移动端流程。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
