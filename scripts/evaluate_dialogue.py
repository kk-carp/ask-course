"""运行多轮售前对话案例；逐轮复用匿名 Cookie 与 conversation_id。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import httpx


def evaluate_case(client: httpx.Client, case: dict) -> list[str]:
    errors: list[str] = []
    conversation_id = None
    for index, turn in enumerate(case["turns"], start=1):
        response = client.post("/ask", json={
            "question": turn["question"],
            "course_id": case.get("course_id"),
            "channel": "internal_tool",
            "conversation_id": conversation_id,
        })
        if response.status_code != 200:
            errors.append(f"第 {index} 轮 HTTP {response.status_code}")
            break
        result = response.json()
        if result.get("intent") != turn["intent"]:
            errors.append(f"第 {index} 轮意图：期望 {turn['intent']}，实际 {result.get('intent')}")
        if turn.get("contains") and turn["contains"] not in result.get("answer", ""):
            errors.append(f"第 {index} 轮回答缺少：{turn['contains']}")
        if turn.get("no_handoff") and result.get("owner"):
            errors.append(f"第 {index} 轮不应转人工")
        next_id = result.get("conversation_id")
        if not next_id or (conversation_id and next_id != conversation_id):
            errors.append(f"第 {index} 轮会话未延续")
        conversation_id = next_id
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="验证售前多轮对话")
    parser.add_argument("--dataset", type=Path, default=Path("data/eval/dialogue_smoke.jsonl"))
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    cases = [json.loads(line) for line in args.dataset.read_text(encoding="utf-8").splitlines() if line.strip()]
    failed = 0
    for case in cases:
        with httpx.Client(base_url=args.base_url, timeout=45) as client:
            problems = evaluate_case(client, case)
        if problems:
            failed += 1
        print(f"{'FAIL' if problems else 'PASS'} {case['id']}")
        for problem in problems:
            print(f"  {problem}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
