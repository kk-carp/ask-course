from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import spa


def frontend_app(tmp_path, monkeypatch, built=True):
    frontend = tmp_path / "frontend"
    dist = frontend / "dist"
    dist.mkdir(parents=True)
    (frontend / "admin.html").write_text("内部管理", encoding="utf-8")
    (frontend / "answer-format.js").write_text("/* helper */", encoding="utf-8")
    if built:
        (dist / "index.html").write_text('<script src="./widget.js" data-preview="true"></script>', encoding="utf-8")
        (dist / "widget.js").write_text("/* Vue widget */", encoding="utf-8")
        (dist / "consult.html").write_text('<script src="./widget.js" data-mode="site"></script>', encoding="utf-8")
    monkeypatch.setattr(spa, "APP_DIR", tmp_path / "backend")
    monkeypatch.setattr(spa, "DEMO_INDEX", dist / "index.html")
    monkeypatch.setattr(spa, "WIDGET_SCRIPT", dist / "widget.js")
    app = FastAPI()
    spa.register_frontend(app)
    return TestClient(app)


def test_public_widget_and_internal_management_have_separate_entries(tmp_path, monkeypatch):
    client = frontend_app(tmp_path, monkeypatch)
    for route in ("/", "/qa", "/login"):
        response = client.get(route)
        assert response.status_code == 200
        assert "data-preview" in response.text
        assert "内部管理" not in response.text
    assert "Vue widget" in client.get("/widget.js").text
    assert "内部管理" in client.get("/admin").text
    assert client.get("/src/main.js").status_code == 404
    standalone = client.get("/consult")
    assert standalone.status_code == 200
    assert 'data-mode="site"' in standalone.text
    assert "data-preview" not in standalone.text
    assert "内部管理" not in standalone.text
    assert standalone.headers["cache-control"] == "no-store"


def test_missing_build_returns_actionable_error_and_keeps_admin_available(tmp_path, monkeypatch):
    client = frontend_app(tmp_path, monkeypatch, built=False)
    response = client.get("/")
    assert response.status_code == 503
    assert "npm run build" in response.json()["detail"]
    assert client.get("/admin").status_code == 200
    standalone = client.get("/consult")
    assert standalone.status_code == 503
    assert "npm run build" in standalone.json()["detail"]
