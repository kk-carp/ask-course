"""试运行推荐池可以先展示官网课程，同时继续阻断未审核购买。"""

import json
from pathlib import Path

from backend.services.approved_courses import (
    load_recommendable_courses,
    parse_approved_courses,
)
from backend.services.course_catalog_service import OfficialCourse


def test_three_courses_are_recommendable_but_not_purchase_approved(monkeypatch):
    path = Path(__file__).resolve().parents[1] / "data" / "approved_courses.json"
    catalog = json.loads(path.read_text(encoding="utf-8"))
    assert {row["id"] for row in catalog["courses"] if row["status"] == "recommendable"} == {
        "42", "43", "99"
    }
    assert parse_approved_courses(catalog) == ()
    monkeypatch.setattr(
        "backend.services.approved_courses.load_official_courses",
        lambda: tuple(
            OfficialCourse(row["id"], row["title"], "官网简介")
            for row in catalog["courses"]
        ),
    )
    assert {item.course_id for item in load_recommendable_courses()} == {
        "42", "43", "99"
    }
