"""Check delivered Vue entry points and JavaScript syntax after the Vite build."""
import subprocess
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.spa import register_frontend  # noqa: E402

frontend = Path(__file__).resolve().parents[1] / "frontend"
dist = frontend / "dist"
page = (dist / "admin.html").read_text(encoding="utf-8")
for asset in ("admin.js", "admin.css", "answer-format.js", "vendor/answer-libs.js"):
    if not (dist / asset).is_file() or f'/{asset}"' not in page:
        raise SystemExit(f"Missing admin asset or page reference: {asset}")
for asset in ("admin.js", "widget.js"):
    subprocess.run(["node", "--check", str(dist / asset)], check=True)
app = FastAPI()
register_frontend(app)
with TestClient(app) as client:
    for route in ("/admin", "/admin.js", "/admin.css", "/", "/consult", "/widget.js",
                  "/answer-format.js", "/vendor/answer-libs.js"):
        response = client.get(route)
        if response.status_code != 200:
            raise SystemExit(f"Built frontend route failed: {route} ({response.status_code})")
    if "课程助手管理后台" not in client.get("/admin").text:
        raise SystemExit("Built admin page has an unexpected title")
print("Vue admin and widget build entries and HTTP routes verified.")
