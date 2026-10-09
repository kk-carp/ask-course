"""测试配置必须支持没有本地缓存的全新检出。"""

from pathlib import Path
import os
import subprocess
import sys


def test_tmp_path_works_without_existing_cache(tmp_path):
    sandbox = tmp_path / "clean-checkout"
    sandbox.mkdir()
    config = Path(__file__).resolve().parents[1] / "pytest.ini"
    (sandbox / "pytest.ini").write_text(config.read_text(encoding="utf-8"), encoding="utf-8")
    (sandbox / "test_temp.py").write_text(
        "def test_temp(tmp_path):\n    assert tmp_path.is_dir()\n", encoding="utf-8"
    )
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--confcutdir=."],
        cwd=sandbox,
        env={**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"},
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
