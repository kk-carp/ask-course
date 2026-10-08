"""检查内部页面内联脚本的语法；需要 Node.js。"""

import subprocess
from pathlib import Path

source = (Path(__file__).resolve().parents[1] / "frontend/admin.html").read_text(encoding="utf-8")
script = source.split("<script>")[1].split("</script>")[0]
raise SystemExit(subprocess.run(["node", "--check"], input=script, text=True, encoding="utf-8", check=False).returncode)
