from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import spa


def test_internal_presales_demo_has_a_separate_entry(tmp_path, monkeypatch) -> None:
    # A clean checkout has no dist; never depend on an earlier local build.
    dist = tmp_path / "frontend" / "dist"
    dist.mkdir(parents=True)
    (dist / "admin.html").write_text("<title>课程助手管理后台</title>", encoding="utf-8")
    (dist / "admin.js").write_text("/* admin */", encoding="utf-8")
    (dist / "admin.css").write_text("/* styles */", encoding="utf-8")
    monkeypatch.setattr(spa, "APP_DIR", tmp_path / "backend")
    app = FastAPI()
    spa.register_frontend(app)
    client = TestClient(app)

    for path in ("/admin",):
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 200, path
        assert "课程助手管理后台" in response.text
        assert "统一知识助手" not in response.text
        assert response.headers["cache-control"] == "no-store"


def test_markdown_assets_are_served_locally():
    app = FastAPI()
    spa.register_frontend(app)
    client = TestClient(app)
    for path in ("/vendor/answer-libs.js", "/answer-format.js"):
        response = client.get(path)
        assert response.status_code == 200
        assert "javascript" in response.headers["content-type"]
