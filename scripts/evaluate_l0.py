"""运行 L0 金标集，验证命中、来源、拒答与真实转人工出口。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx


def load_cases(path: Path) -> list[dict]:
    cases: list[dict] = []
    ids: set[str] = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        case = json.loads(line)
        required = {"id", "question", "expected_hit", "require_sources"}
        missing = required - case.keys()
        if missing:
            raise ValueError(f"第 {line_number} 行缺少字段：{', '.join(sorted(missing))}")
        if case["id"] in ids:
            raise ValueError(f"用例 ID 重复：{case['id']}")
        course_id = case.get("course_id")
        if course_id is not None and (not str(course_id).isdigit() or str(course_id) == "0"):
            raise ValueError(f"第 {line_number} 行课程 ID 必须为已核实的官网数字 ID")
        ids.add(case["id"])
        cases.append(case)
    if not cases:
        raise ValueError("评测集不能为空")
    return cases


def evaluate_case(client: httpx.Client, case: dict) -> list[str]:
    response = client.post(
        "/ask",
        json={
            "question": case["question"],
            "course_id": case.get("course_id"),
            "channel": case.get("channel", "internal_tool"),
        },
    )
    if response.status_code != 200:
        return [f"HTTP {response.status_code}: {response.text[:200]}"]

    payload = response.json()
    problems: list[str] = []
    expected_hit = bool(case["expected_hit"])
    if payload.get("hit") is not expected_hit:
        problems.append(f"hit 期望 {expected_hit}，实际 {payload.get('hit')}")

    sources = (payload.get("sources") or []) + (payload.get("fact_sources") or [])
    if case["require_sources"] and not sources:
        problems.append("命中回答没有来源")
    if not expected_hit:
        if payload.get("sources"):
            problems.append("未命中回答不应携带来源")
        if payload.get("generation_called"):
            problems.append("未命中仍调用了答案生成模型")

    expected_owner = case.get("expected_owner_topic_key")
    if expected_owner:
        owner = payload.get("owner") or {}
        if not owner.get("configured"):
            problems.append("转人工出口未配置")
        elif owner.get("topic_key") != expected_owner:
            problems.append(
                f"售前路由期望 {expected_owner}，实际 {owner.get('topic_key')}"
            )

    answer = str(payload.get("answer") or "").casefold()
    for phrase in case.get("forbidden_phrases", []):
        if phrase.casefold() in answer:
            problems.append(f"回答包含禁用承诺：{phrase}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description="执行 L0 问答金标评测")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("data/eval/pilot_gold.jsonl"),
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=float, default=90.0)
    args = parser.parse_args()

    try:
        cases = load_cases(args.dataset)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"[FAIL] 无法读取评测集：{exc}", file=sys.stderr)
        return 1

    failed = 0
    with httpx.Client(base_url=args.base_url, timeout=args.timeout) as client:
        for case in cases:
            try:
                problems = evaluate_case(client, case)
            except httpx.HTTPError as exc:
                problems = [f"请求失败：{exc}"]
            if problems:
                failed += 1
                print(f"[FAIL] {case['id']}")
                for problem in problems:
                    print(f"  - {problem}")
            else:
                print(f"[PASS] {case['id']}")

    passed = len(cases) - failed
    print(f"\n结果：通过 {passed}/{len(cases)}，失败 {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
