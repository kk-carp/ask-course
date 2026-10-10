"""回退兼容的不可变镜像；先关入口，保持数据库结构和业务数据，不自动重新开放。"""

import argparse
import json
import os
import re
import subprocess
import time
from urllib.request import urlopen


def run(args: list[str], env: dict) -> str:
    result = subprocess.run(["docker", *args], env=env, capture_output=True, text=True,
                            timeout=120, check=False)
    if result.returncode:
        raise RuntimeError("Docker command failed; inspect controlled deployment logs")
    return result.stdout


def rollback(*, env_file: str, previous_image: str, base_url: str, timeout: int = 600) -> None:
    if not re.fullmatch(r"(?:sha256:|[a-zA-Z0-9._:/-]+@sha256:)[a-f0-9]{64}", previous_image):
        raise ValueError("Previous image must be a local immutable SHA256 ID or repository digest")
    env = dict(os.environ)
    details = json.loads(run(["image", "inspect", previous_image], env))[0]
    labels = details.get("Config", {}).get("Labels") or {}
    if labels.get("agent.schema") != "0004" or labels.get("agent.safety-contract") != "2026-10-10":
        raise ValueError("Previous image lacks current schema/safety contract; refuse unsafe rollback")
    compose = ["compose", "--env-file", env_file]
    run([*compose, "config", "--quiet"], env)
    run([*compose, "run", "--rm", "--no-deps", "api", "python", "-m", "backend.scripts.emergency_stop"], env)
    run([*compose, "stop", "api"], env)
    env["AGENT_IMAGE"] = previous_image
    try:
        run([*compose, "up", "-d", "--no-build", "--no-deps", "api", "monitor"], env)
        deadline = time.monotonic() + timeout
        while True:
            try:
                with urlopen(base_url.rstrip('/') + '/ready', timeout=5) as response:
                    if response.status == 200:
                        break
            except OSError:
                pass
            if time.monotonic() >= deadline:
                raise RuntimeError("Rollback readiness deadline exceeded")
            time.sleep(2)
        run([*compose, "exec", "-T", "api", "python", "-m", "backend.scripts.emergency_stop", "--check"], env)
    except (RuntimeError, OSError, subprocess.SubprocessError):
        run([*compose, "stop", "api"], env)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--previous-image", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    rollback(env_file=args.env_file, previous_image=args.previous_image, base_url=args.base_url)
    print("Compatible image ready; pilot remains 0. Run core acceptance cases before reopening.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
