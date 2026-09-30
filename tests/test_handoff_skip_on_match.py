from backend.services.ask_orchestrator import apply_handoff
from backend.schemas import OwnerInfo, RelatedCourse
from backend.services.qa_service import AskResult

QR = "https://publicqn.arborseek.com/tstj/images/1785143748273.png"


def test_matched_courses_skip_handoff(monkeypatch) -> None:
    monkeypatch.setattr(
        "backend.services.ask_orchestrator.resolve_handoff",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("must not hand off after matching courses")
        ),
    )
    result = AskResult(answer="知识库暂无依据", hit=False, sources=[])
    related = [
        RelatedCourse(id="43", title="四足机器人无人巡检实训营", description=None)
    ]
    out = apply_handoff(
        result,
        question="有没有四足课",
        course_id=None,
        related_courses=related,
    )
    assert out.owner is None
    assert out.answer == "知识库暂无依据"


def test_miss_without_courses_still_handoffs(monkeypatch) -> None:
    owner = OwnerInfo(
        configured=True,
        topic_key="43",
        topic_name="四足",
        name="课程顾问",
        contact=QR,
    )
    monkeypatch.setattr(
        "backend.services.ask_orchestrator.resolve_handoff",
        lambda **_kwargs: type("H", (), {"owner": owner, "route": "fallback"})(),
    )
    monkeypatch.setattr(
        "backend.services.ask_orchestrator.settings.handoff_miss_answer",
        "已转接顾问",
    )
    result = AskResult(answer="原始未命中", hit=False, sources=[])
    out = apply_handoff(
        result,
        question="今天天气怎么样",
        course_id=None,
        related_courses=[],
    )
    assert out.owner is not None
    assert out.owner.contact == QR
    assert out.answer == "已转接顾问"
