"""预发布容量采样：独立访客并发请求，不改变灰度比例或购买状态。"""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

import httpx


async def sample(args):
    semaphore = asyncio.Semaphore(args.concurrency)

    async def one():
        async with semaphore:
            started = time.perf_counter()
            try:
                async with httpx.AsyncClient(base_url=args.base_url, trust_env=False, timeout=180) as client:
                    response = await client.post("/ask", json={"question": args.question, "course_id": args.course_id, "channel": "internal_tool"})
                ok = response.status_code == 200 and not response.json().get("error_type")
                return time.perf_counter() - started, ok
            except (httpx.HTTPError, ValueError):
                return time.perf_counter() - started, False

    before = time.perf_counter()
    results = await asyncio.gather(*(one() for _ in range(args.requests)))
    elapsed = time.perf_counter() - before
    latencies = sorted(value for value, _ in results)
    return {"requests": args.requests, "concurrency": args.concurrency,
            "errors": sum(not ok for _, ok in results), "elapsed_seconds": round(elapsed, 3),
            "p50_seconds": round(latencies[(len(latencies) - 1) // 2], 3),
            "p95_seconds": round(latencies[min(len(latencies) - 1, int(len(latencies) * .95))], 3)}


def main():
    parser = argparse.ArgumentParser(description="采样真实模型响应时间与并发错误率")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--course-id", default="42")
    parser.add_argument("--question", default="课程中的实践项目如何开展？")
    parser.add_argument("--requests", type=int, default=20)
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument("--output", type=Path, default=Path("data/eval/load-results.json"))
    args = parser.parse_args()
    if not 1 <= args.concurrency <= 20 or not 1 <= args.requests <= 200:
        parser.error("并发须为 1–20，请求数须为 1–200")
    report = asyncio.run(sample(args))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return int(report["errors"] > 0)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
