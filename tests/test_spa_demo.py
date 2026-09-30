from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.spa import register_frontend


def test_home_and_legacy_paths_serve_presales_demo() -> None:
    app = FastAPI()
    register_frontend(app)
    client = TestClient(app)

    for path in ("/", "/login?redirect=/qa", "/qa"):
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 200, path
        assert "售前助手" in response.text
        assert "统一知识助手" not in response.text
        assert response.headers["cache-control"] == "no-store"
