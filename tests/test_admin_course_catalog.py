import json
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routes import documents
from backend.services import admin_course_catalog
from backend.services.auth_service import AuthContext, AuthUser


def test_catalog_merges_registered_courses_and_legacy_materials(tmp_path, monkeypatch):
    path = tmp_path / "courses.json"
    path.write_text(json.dumps({"courses": [
        {"id": "101", "title": "新课程", "status": "draft"},
        {"id": "43", "title": "课程名称来自登记"},
        {"id": "bad", "title": "无效编号"},
        {"id": "0", "title": "无效课程"},
        {"id": "42", "title": ""},
        None,
    ]}), encoding="utf-8")
    monkeypatch.setattr(admin_course_catalog.settings, "approved_course_catalog_path", str(path))
    monkeypatch.setattr(admin_course_catalog, "list_documents", lambda: [
        SimpleNamespace(course_id="43"), SimpleNamespace(course_id="43"),
        SimpleNamespace(course_id="777"), SimpleNamespace(course_id=None),
    ])
    result = {item["id"]: item for item in admin_course_catalog.list_admin_courses()}
    assert set(result) == {"43", "101", "777"}
    assert result["43"]["title"] == "课程名称来自登记"
    assert result["43"]["document_count"] == 2
    assert result["101"]["document_count"] == 0
    assert "未登记名称" in result["777"]["title"]


def test_missing_catalog_still_lists_courses_with_materials(tmp_path, monkeypatch):
    monkeypatch.setattr(admin_course_catalog.settings, "approved_course_catalog_path", str(tmp_path / "missing.json"))
    monkeypatch.setattr(admin_course_catalog, "list_documents", lambda: [SimpleNamespace(course_id="99")])
    assert admin_course_catalog.list_admin_courses()[0]["id"] == "99"


def test_admin_catalog_endpoint_is_not_cacheable(monkeypatch):
    context = AuthContext(AuthUser(id="admin", username="admin", role="admin"), ["courses"])
    monkeypatch.setattr(documents, "load_auth_context", lambda _request: context)
    monkeypatch.setattr(documents, "list_admin_courses", lambda: [{"id": "101", "title": "课程", "document_count": 0}])
    app = FastAPI()
    app.include_router(documents.router)
    response = TestClient(app).get("/admin/courses")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()[0]["id"] == "101"
