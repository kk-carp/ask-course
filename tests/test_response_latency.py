import threading
from uuid import uuid4

import pytest
from fastapi import HTTPException

from backend.config import settings
from backend.infra.metrics import latency_snapshot
from backend.infra.request_context import (
    bind_request_id,
    get_request_id,
    reset_request_id,
)
from backend.schemas import AskRequest, AskResponse
from backend.services import ask_orchestrator as orchestrator
from backend.services import turn_understanding
from backend.services.ask_orchestrator import AskIdentity
from backend.services.turn_understanding import Understanding


def test_first_consultation_skips_catalog_and_semantic_model(monkeypatch):
    monkeypatch.setattr(settings, "chat_api_key", "test")
    calls = []
    monkeypatch.setattr(orchestrator, "load_recommendable_courses", lambda: calls.append("catalog") or ())
    monkeypatch.setattr(turn_understanding, "complete_chat", lambda *_a: calls.append("model"))
    monkeypatch.setattr(orchestrator, "_run_questions", lambda *_a: iter([("final", AskResponse(answer="目标？"))]))
    orchestrator.run_ask_turn(AskRequest(question="推荐一门适合我的课程"), AskIdentity(["courses"], None, None, None))
    assert calls == []
    assert latency_snapshot()["ask_first_turn"]["samples"] >= 1


def test_explicit_facts_skip_semantic_model(monkeypatch):
    monkeypatch.setattr(settings, "chat_api_key", "test")
    calls = []
    monkeypatch.setattr(turn_understanding, "complete_chat", lambda *_a: calls.append("model"))
    result = turn_understanding.understand_turn(
        "价格多少？能看多久？有优惠吗？", page_course_id="43", profile={}, history=[], catalog=(),
    )
    assert len(result.questions) == 3
    assert calls == []


def test_independent_content_questions_overlap_and_keep_order(monkeypatch):
    barrier = threading.Barrier(3)

    def answer(payload, *_a, **_kw):
        barrier.wait(timeout=1)
        return AskResponse(answer=payload.question, hit=True)

    monkeypatch.setattr(orchestrator, "_run_single_question", answer)
    questions = ["价格多少", "能看多久", "有优惠吗"]
    events = list(orchestrator._run_questions(
        AskRequest(question="？".join(questions), course_id="43"),
        AskIdentity(["courses"], None, None, None), Understanding(questions, "content", course_id="43"),
    ))
    assert [data["question"] for name, data in events if name == "part"] == questions
    assert events[-1][1].intent == "multi_question"


@pytest.mark.parametrize("failed", [1, 3])
def test_parallel_failure_preserves_other_answers_or_raises(monkeypatch, failed):
    def answer(payload, *_a, **_kw):
        if int(payload.question) <= failed:
            raise HTTPException(status_code=502, detail="unavailable")
        return AskResponse(answer="有依据的回答", hit=True, prompt_tokens=7)

    monkeypatch.setattr(orchestrator, "_run_single_question", answer)
    events = orchestrator._run_questions(
        AskRequest(question="test", course_id="43"), AskIdentity(["courses"], None, None, None),
        Understanding(["1", "2", "3"], "content", course_id="43"),
    )
    if failed == 3:
        with pytest.raises(HTTPException) as error:
            list(events)
        assert error.value.status_code == 502
    else:
        result = list(events)[-1][1]
        assert result.hit and result.error_type == "upstream_error"
        assert result.prompt_tokens == 14
        assert "有依据的回答" in result.answer


def test_guest_prepares_one_context_and_parallel_workers_keep_request_id(monkeypatch):
    dialogue_id = uuid4()
    prepared = []
    context = (str(dialogue_id), [("user", "上一轮")], None, "43")
    monkeypatch.setattr(orchestrator, "_prepare_guest_dialogue", lambda *_a, **_kw: prepared.append(1) or context)

    def answer(payload, *_a, **kwargs):
        assert kwargs["guest_context"] is context
        assert payload.conversation_id == dialogue_id
        assert get_request_id() == "latency-regression"
        return AskResponse(answer=payload.question, conversation_id=dialogue_id)

    monkeypatch.setattr(orchestrator, "_run_single_question", answer)
    token = bind_request_id("latency-regression")
    try:
        result = list(orchestrator._run_questions(
            AskRequest(question="test", course_id="43"), AskIdentity(["courses"], None, None, "visitor"),
            Understanding(["价格", "期限"], "content", course_id="43"),
        ))[-1][1]
    finally:
        reset_request_id(token)
    assert prepared == [1] and result.conversation_id == dialogue_id


def test_logged_in_multi_question_keeps_sequential_conversation(monkeypatch):
    dialogue_id = uuid4()
    seen = []

    def answer(payload, *_a, **_kw):
        seen.append(payload.conversation_id)
        return AskResponse(answer=payload.question, conversation_id=dialogue_id)

    monkeypatch.setattr(orchestrator, "_run_single_question", answer)
    list(orchestrator._run_questions(
        AskRequest(question="test", course_id="43"), AskIdentity(["courses"], "admin", "admin", None),
        Understanding(["价格", "期限"], "content", course_id="43"),
    ))
    assert seen == [None, dialogue_id]
