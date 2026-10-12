"""Check delivered Vue entry points and JavaScript syntax after the Vite build."""
import subprocess
from pathlib import Path

frontend = Path(__file__).resolve().parents[1] / "frontend"
dist = frontend / "dist"
page = (dist / "admin.html").read_text(encoding="utf-8")
for asset in ("admin.js", "admin.css", "answer-format.js", "vendor/answer-libs.js"):
    if not (dist / asset).is_file() or f'/{asset}"' not in page:
        raise SystemExit(f"Missing admin asset or page reference: {asset}")
for asset in ("admin.js", "widget.js"):
    subprocess.run(["node", "--check", str(dist / asset)], check=True)
print("Vue admin and widget build entries verified.")
