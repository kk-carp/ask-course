"""无正文的运行计数；独立采集器持久化采样和预算估算。"""

import threading
import time
from collections import Counter, deque
from datetime import datetime, timezone
from uuid import uuid4

_lock = threading.Lock()
_process_id = uuid4().hex
_counts = Counter()
_requests = deque(maxlen=10000)
_usage_day = ""
_daily_usage = Counter()


def record_http(status: int, duration_ms: float) -> None:
    with _lock:
        _counts["requests"] += 1
        _counts["http_errors"] += int(status >= 500)
        _counts["rate_limited"] += int(status == 429)
        _requests.append((time.monotonic(), duration_ms))


def record_model(*, prompt_tokens=0, completion_tokens=0, failed=False, timed_out=False, usage_known=True) -> None:
    global _usage_day
    with _lock:
        day = datetime.now(timezone.utc).date().isoformat()
        if _usage_day != day:
            _daily_usage.clear()
            _usage_day = day
        _counts["model_calls"] += 1
        _counts["model_errors"] += int(failed)
        _counts["model_timeouts"] += int(timed_out)
        _counts["unknown_usage"] += int(not usage_known)
        _counts["input_tokens"] += max(0, int(prompt_tokens))
        _counts["output_tokens"] += max(0, int(completion_tokens))
        for key, value in (("input_tokens", max(0, int(prompt_tokens))),
                           ("output_tokens", max(0, int(completion_tokens))),
                           ("model_calls", 1), ("unknown_usage", int(not usage_known))):
            _daily_usage[key] += value


def snapshot() -> dict:
    cutoff = time.monotonic() - 300
    with _lock:
        values = sorted(duration for moment, duration in _requests if moment >= cutoff)
        return {"process_id": _process_id, "counters": dict(_counts),
                "usage_day": _usage_day, "usage_counters": dict(_daily_usage),
                "request_window_samples": len(values),
                "request_p95_ms": round(values[min(len(values)-1, int(len(values)*.95))], 1) if values else 0}
