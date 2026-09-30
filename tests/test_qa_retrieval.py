from uuid import uuid4

from backend.infra.generate import ChatResult, ChatUsage
from backend.infra.retrieve import RetrievedChunk
from backend.services import qa_service


def test_retrieval_returns_chunks_and_answer_uses_them(monkeypatch):
    chunks = [RetrievedChunk(content="实践项目资料", score=.9, document_id=uuid4(),
                             title="测试资料", space_id="public")]
    monkeypatch.setattr(qa_service, "is_loaded", lambda: True)
    monkeypatch.setattr(qa_service, "encode_query", lambda _: [1.0])
    monkeypatch.setattr(qa_service, "run_retrieval", lambda **_: chunks)
    calls = []

    def generate(question, retrieved):
        calls.append(retrieved)
        return ChatResult(text="项目实践说明", usage=ChatUsage(0, 0))

    monkeypatch.setattr(qa_service, "generate_answer", generate)
    result = qa_service.answer_question(["public"], "项目怎么实践？", course_id="42")
    assert result.hit and result.answer == "项目实践说明"
    assert calls == [chunks]
    assert result.sources[0].document_id == chunks[0].document_id
