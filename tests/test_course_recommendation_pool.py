"""试运行课程通过完整审核后进入推荐池并生成购买入口；其余课程保持草稿。"""

import json
from pathlib import Path

from backend.services.approved_courses import (
    load_recommendable_courses,
    parse_approved_courses,
)
from backend.services.course_catalog_service import OfficialCourse

PILOT_IDS = {"42", "43", "99"}


def test_pilot_courses_are_approved_with_purchase_pages(monkeypatch):
    path = Path(__file__).resolve().parents[1] / "data" / "approved_courses.json"
    catalog = json.loads(path.read_text(encoding="utf-8"))
    statuses = {row["id"]: row["status"] for row in catalog["courses"]}
    assert {key for key, value in statuses.items() if value == "approved"} == PILOT_IDS
    assert {key for key, value in statuses.items() if value not in {"approved", "draft"}} == set()

    approved = {item.id: item for item in parse_approved_courses(catalog)}
    assert set(approved) == PILOT_IDS
    for course_id, item in approved.items():
        assert item.purchase_url == f"https://www.arborseek.com/course/{course_id}"

    monkeypatch.setattr(
        "backend.services.approved_courses.load_official_courses",
        lambda: tuple(
            OfficialCourse(row["id"], row["title"], "官网简介")
            for row in catalog["courses"]
        ),
    )
    assert {item.course_id for item in load_recommendable_courses()} == PILOT_IDS
