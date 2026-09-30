"""使用独立的虚构课程事实，避免测试依赖或发布本地运营资料。"""

import json

import pytest


@pytest.fixture(autouse=True)
def isolated_course_facts(tmp_path, monkeypatch):
    from backend.services import course_facts

    data = tmp_path / "data"
    data.mkdir()
    rows = {}
    for course_id in ("42", "43", "99"):
        rows[course_id] = {
            "source": f"docs/test-course-{course_id}.md",
            "updated_at": "2026-09-30",
            "facts": {
                "outline": {"text": "测试课程目录：MoveIt2、ROS2、RAG", "status": "provided"},
                "hardware": {"text": "测试资料：允许仿真练习，使用 Ubuntu 22.04。", "status": "provided"},
                "validity": {"text": "测试资料：观看期限资料存在冲突，需要课程顾问确认。", "status": "conflict"},
            },
        }
    (data / "course_facts.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(course_facts, "ROOT", tmp_path)
    monkeypatch.setattr(course_facts, "_cache", {})
