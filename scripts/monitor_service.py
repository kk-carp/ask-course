"""单副本独立采集器；仅输出指标和告警，不读取问答正文，也不主动向外发送通知。"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.config import settings


def evaluate(state: dict, sample: dict, *, now: float, ready: bool, config=settings) -> dict:
    """Pure state transition, persisted after every poll. Costs use configured billing currency."""
    day = datetime.fromtimestamp(now, timezone.utc).date().isoformat()
    previous = state.get("last", {})
    counts = sample.get("counters", {})
    same_process = sample.get("process_id") == previous.get("process_id")
    prior_counts = previous.get("counters", {}) if same_process else {}
    delta = {key: max(0, value - prior_counts.get(key, 0)) for key, value in counts.items()}
    usage = dict(state.get("daily_usage", {})) if state.get("day") == day else {}
    usage_counts = sample.get("usage_counters", counts) if sample.get("usage_day", day) == day else {}
    prior_usage = (previous.get("usage_counters", prior_counts)
                   if same_process and previous.get("usage_day", day) == day else {})
    for key in ("input_tokens", "output_tokens", "unknown_usage", "model_calls"):
        usage[key] = usage.get(key, 0) + max(0, usage_counts.get(key, 0) - prior_usage.get(key, 0))
    window = [row for row in state.get("window", []) if row["time"] > now - 300]
    if sample:
        # A first sample/reset is a baseline, not five minutes of recent traffic.
        recent = previous and same_process and now - state.get("updated_at", now) <= 300
        window.append({"time": now, "delta": delta if recent else {}})
    totals = {key: sum(row["delta"].get(key, 0) for row in window)
              for key in ("requests", "http_errors", "rate_limited", "model_calls", "model_errors", "model_timeouts")}
    cost = (usage.get("input_tokens", 0) * config.monitoring_input_price_per_million
            + usage.get("output_tokens", 0) * config.monitoring_output_price_per_million) / 1_000_000
    alerts = []
    def alert(code, severity="warning"):
        alerts.append({"code": code, "severity": severity})
    if not ready:
        alert("service_unavailable", "critical")
    if not sample:
        alert("metrics_unavailable", "critical")
    if previous and sample and not same_process:
        alert("process_restarted_sampling_gap")
    if (totals["http_errors"] >= 3 or
        totals["requests"] >= 5 and totals["http_errors"] / totals["requests"] >= config.monitoring_error_rate):
        alert("http_error_rate", "critical")
    if totals["model_calls"] >= 3 and totals["model_errors"] / totals["model_calls"] >= config.monitoring_error_rate:
        alert("model_error_rate", "critical")
    if totals["model_timeouts"]:
        alert("model_timeout")
    if sample.get("request_window_samples", 0) >= 5 and sample.get("request_p95_ms", 0) >= config.monitoring_p95_ms:
        alert("request_latency_p95")
    if totals["rate_limited"] >= config.monitoring_rate_limit_count:
        alert("abnormal_rate_limited_calls")
    prices_set = config.monitoring_input_price_per_million > 0 and config.monitoring_output_price_per_million > 0
    if not prices_set or config.monitoring_daily_budget <= 0:
        alert("cost_monitor_not_configured")
    if usage.get("unknown_usage"):
        alert("model_usage_missing_cost_incomplete")
    if prices_set and config.monitoring_daily_budget > 0 and cost >= config.monitoring_daily_budget:
        alert("daily_cost_budget", "critical")
    active = {entry["code"] for entry in alerts}
    old = {entry["code"] for entry in state.get("alerts", [])}
    history = list(state.get("history", []))
    for code in sorted(active - old):
        history.append({"time": now, "code": code, "state": "firing"})
    for code in sorted(old - active):
        history.append({"time": now, "code": code, "state": "resolved"})
    return {"updated_at": now, "day": day, "daily_usage": usage,
            "estimated_cost": round(cost, 6), "cost_is_estimate": True,
            "window": window, "window_totals": totals, "alerts": alerts,
            "history": history[-1000:], "last": sample or previous}


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def poll(state: dict) -> dict:
    base = settings.monitoring_url.rstrip("/")
    try:
        with urlopen(Request(base + "/ops/metrics", headers={"Authorization": "Bearer " + settings.monitoring_token}), timeout=5) as response:
            sample = json.load(response)
    except (OSError, ValueError):
        sample = {}
    try:
        with urlopen(base + "/ready", timeout=5) as response:
            ready = response.status == 200
    except OSError:
        ready = False
    return evaluate(state, sample, now=time.time(), ready=ready)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if len(settings.monitoring_token) < 32:
        raise SystemExit("请先配置至少 32 字符的 MONITORING_TOKEN")
    path = Path(settings.monitoring_state_file)
    state = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    while True:
        old_history = state.get("history", [])
        state = poll(state)
        save_state(path, state)
        for entry in state["history"]:
            if entry not in old_history:
                print(json.dumps({"event": "operations_alert", **entry}), flush=True)
        if args.once:
            return int(bool(state["alerts"]))
        time.sleep(settings.monitoring_interval_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
