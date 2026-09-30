"""进程内问答计数：当前进程启动后累计，重启清零。不含问题正文。"""

from dataclasses import dataclass
import threading

_lock = threading.Lock()
_counters = {
    "ask_total": 0,
    "ask_hit": 0,
    "ask_miss": 0,
    "ask_error_502": 0,
    "ask_error_503": 0,
    "ask_429": 0,
    "llm_calls": 0,
    "prompt_tokens_total": 0,
    "completion_tokens_total": 0,
}


@dataclass(frozen=True)
class MetricsSnapshot:
    ask_total: int
    ask_hit: int
    ask_miss: int
    ask_error_502: int
    ask_error_503: int
    ask_429: int
    llm_calls: int
    prompt_tokens_total: int
    completion_tokens_total: int


def reset() -> None:
    with _lock:
        for key in _counters:
            _counters[key] = 0


def snapshot() -> MetricsSnapshot:
    with _lock:
        return MetricsSnapshot(**dict(_counters))


def record_429() -> None:
    with _lock:
        _counters["ask_429"] += 1


def record_ask_outcome(
    *,
    error_type: str,
    llm_called: bool = False,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
) -> None:
    with _lock:
        _counters["ask_total"] += 1
        if error_type == "hit":
            _counters["ask_hit"] += 1
        elif error_type == "miss":
            _counters["ask_miss"] += 1
        elif error_type == "502":
            _counters["ask_error_502"] += 1
        elif error_type == "503":
            _counters["ask_error_503"] += 1
        if llm_called:
            _counters["llm_calls"] += 1
        _counters["prompt_tokens_total"] += max(0, int(prompt_tokens))
        _counters["completion_tokens_total"] += max(0, int(completion_tokens))
