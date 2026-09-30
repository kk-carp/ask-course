"""并发执行真实模型单轮/多轮验收，分别记录事实错误和流程失败。"""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

import httpx


def check_result(result: dict, expected: dict) -> list[str]:
    errors = []
    if "expected_hit" in expected and result.get("hit") is not expected["expected_hit"]:
        errors.append("hit 不符合期望")
    if expected.get("intent") and result.get("intent") != expected["intent"]:
        errors.append(f"意图期望 {expected['intent']}，实际 {result.get('intent')}")
    sources = result.get("sources", []) + result.get("fact_sources", [])
    if expected.get("require_sources") and not sources:
        errors.append("缺少可追溯依据")
    if expected.get("expected_source") and sources and not any(expected["expected_source"] in x.get("source", "") for x in sources):
        errors.append("严重：事实依据未对应目标课程")
    if expected.get("expected_fact_status") and not any(x.get("status") == expected["expected_fact_status"] for x in sources):
        errors.append("事实状态不符合期望")
    if expected.get("expect_course") and expected["expect_course"] not in [x["id"] for x in result.get("related_courses", [])]:
        errors.append("未返回目标课程")
    owner = result.get("owner") or {}
    if expected.get("expected_owner_topic_key"):
        if not owner.get("configured") or owner.get("topic_key") != expected["expected_owner_topic_key"]:
            errors.append("严重：顾问承接不正确或不可用")
        if not result.get("handoff_summary"):
            errors.append("缺少交接摘要")
    if expected.get("no_purchase") and any(x.get("purchase_url") for x in result.get("related_courses", [])):
        errors.append("严重：未知课程出现购买入口")
    for phrase in expected.get("forbidden_phrases", []):
        if phrase in result.get("answer", ""):
            errors.append(f"严重：禁用承诺 {phrase}")
    return errors


async def evaluate(args, cases):
    semaphore = asyncio.Semaphore(args.concurrency)

    async def run(case):
        async with semaphore:
            started = time.perf_counter()
            errors = []
            answers = []
            async with httpx.AsyncClient(base_url=args.base_url, timeout=180, trust_env=False) as client:
                conversation_id = None
                try:
                    if case.get("path"):
                        response = await client.get(case["path"])
                        if response.status_code != case["expected_http"]:
                            errors.append(f"HTTP {response.status_code}")
                    else:
                        for turn in case.get("turns", [case]):
                            response = await client.post("/ask", json={"question": turn["question"],
                                "course_id": turn.get("course_id", case.get("course_id")), "channel": "internal_tool",
                                "conversation_id": conversation_id})
                            if response.status_code != 200:
                                errors.append(f"HTTP {response.status_code}")
                                break
                            result = response.json()
                            answers.append({"question": turn["question"], "response": result})
                            errors.extend(check_result(result, turn))
                            next_id = result.get("conversation_id")
                            if conversation_id and next_id != conversation_id:
                                errors.append("多轮会话中断")
                            conversation_id = next_id
                except (httpx.HTTPError, ValueError) as exc:
                    errors.append(type(exc).__name__)
            print(f"{'FAIL' if errors else 'PASS'} {case['id']} {'; '.join(errors)}", flush=True)
            return {"id": case["id"], "errors": errors, "seconds": round(time.perf_counter() - started, 3), "answers": answers}

    rows = await asyncio.gather(*(run(case) for case in cases))
    return {"cases": len(rows), "passed": sum(not row["errors"] for row in rows),
            "severe_cases": sum(any(x.startswith("严重") for x in row["errors"]) for row in rows), "results": rows}


def main():
    parser = argparse.ArgumentParser(description="真实课程和模型的端到端咨询验收")
    parser.add_argument("--dataset", type=Path, default=Path("data/eval/pilot_gold.jsonl"))
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--output", type=Path, default=Path("data/eval/pilot-results.json"))
    args = parser.parse_args()
    if not 1 <= args.concurrency <= 10:
        parser.error("并发须为 1–10")
    cases = [json.loads(line) for line in args.dataset.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not cases or len({case["id"] for case in cases}) != len(cases):
        parser.error("案例不能为空且 ID 不能重复")
    report = asyncio.run(evaluate(args, cases))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Passed {report['passed']}/{report['cases']}; severe cases {report['severe_cases']}")
    return int(report["passed"] != report["cases"] or report["severe_cases"] > 0)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
