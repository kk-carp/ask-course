"""受控上游延迟基准；不连接数据库、官网或模型，不代表线上绝对耗时。"""

import sys
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.schemas import AskRequest, AskResponse
from backend.services.ask_orchestrator import AskIdentity, _run_questions
from backend.services.turn_understanding import Understanding


def delayed_answer(payload, *_args, **_kwargs):
    time.sleep(0.12)
    return AskResponse(answer=payload.question, hit=True)


def measure(count, *, parallel):
    questions = ["课程内容如何安排"] * count
    identity = AskIdentity(["courses"], None if parallel else "reference", None, None)
    started = time.perf_counter()
    events = list(_run_questions(
        AskRequest(question="？".join(questions), course_id="43"), identity,
        Understanding(questions, "content", course_id="43"),
    ))
    assert len([event for event in events if event[0] == "part"]) == count
    return (time.perf_counter() - started) * 1000


def main():
    with patch("backend.services.ask_orchestrator._run_single_question", delayed_answer):
        for count in (3, 5):
            sequential = measure(count, parallel=False)
            parallel = measure(count, parallel=True)
            print(f"questions={count} sequential_reference_ms={sequential:.1f} "
                  f"parallel_ms={parallel:.1f} reduction={1 - parallel / sequential:.1%}")


if __name__ == "__main__":
    main()
