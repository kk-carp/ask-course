from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.spa import register_frontend


def test_internal_presales_demo_has_a_separate_entry() -> None:
    app = FastAPI()
    register_frontend(app)
    client = TestClient(app)

    for path in ("/admin",):
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 200, path
        assert "售前助手" in response.text
        assert "统一知识助手" not in response.text
        assert response.headers["cache-control"] == "no-store"


def test_markdown_assets_are_served_locally():
    app = FastAPI()
    register_frontend(app)
    client = TestClient(app)
    for path in ("/vendor/answer-libs.js", "/answer-format.js"):
        response = client.get(path)
        assert response.status_code == 200
        assert "javascript" in response.headers["content-type"]
