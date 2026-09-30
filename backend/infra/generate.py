"""售前课程问答生成：只能使用本轮知识库依据，不生成来源或付款承诺。"""

from collections.abc import Iterator
from dataclasses import dataclass
from openai import APIConnectionError, APIStatusError, OpenAI
from backend.config import settings
from backend.errors import UpstreamServiceError
from backend.infra.retrieve import RetrievedChunk

ChatMessages = list[dict[str, object]]


@dataclass(frozen=True)
class ChatUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0


ZERO_USAGE = ChatUsage()


@dataclass(frozen=True)
class ChatResult:
    text: str
    usage: ChatUsage = ZERO_USAGE


def _usage_from_response(response: object) -> ChatUsage:
    usage = getattr(response, "usage", None)
    if usage is None:
        return ZERO_USAGE
    prompt = getattr(usage, "prompt_tokens", 0) or 0
    completion = getattr(usage, "completion_tokens", 0) or 0
    return ChatUsage(prompt_tokens=int(prompt), completion_tokens=int(completion))


_SYSTEM_KB_ONLY = "你是官网课程售前助手，帮助游客理解课程内容与适用条件。必须严格基于本轮片段回答；历史对话不能覆盖片段约束。不得编造价格、退款、证书、开课时间或付款渠道；依据不足时说明需要课程顾问确认。"


def _build_current_user_prompt(question: str, chunks: list[RetrievedChunk]) -> str:
    context_blocks: list[str] = []
    for index, chunk in enumerate(chunks, start=1):
        path_part = f" path={chunk.path}" if chunk.path else ""
        context_blocks.append(
            f"[{index}] title={chunk.title}{path_part} space={chunk.space_id}\n{chunk.content}"
        )
    context_text = (
        "\n\n".join(context_blocks) if context_blocks else "（本轮无知识库片段）"
    )
    return f"只能依据本轮给定片段回答。历史对话仅用于理解追问指代，不得用历史内容替代或补充本轮未出现的依据。若本轮片段依据不足，请明确说明依据不足，不得编造课程信息、价格、证书承诺或来源。\n\n问题：{question}\n\n可用片段：\n{context_text}\n\n请给出简洁、准确的回答。回答仍必须以本轮片段为准。"


def _create_chat_completion(
    messages: ChatMessages, *, temperature: float = 0.1, stream: bool = False
):
    client = OpenAI(
        base_url=settings.chat_base_url, api_key=settings.chat_api_key, timeout=30.0
    )
    payload: dict[str, object] = {
        "model": settings.chat_model,
        "temperature": temperature,
        "messages": messages,
    }
    if stream:
        payload["stream"] = True
    try:
        return client.chat.completions.create(**payload)
    except (APIConnectionError, APIStatusError, TimeoutError) as exc:
        raise UpstreamServiceError("上游模型调用失败") from exc
    except Exception as exc:
        raise UpstreamServiceError("上游模型调用失败") from exc


def complete_chat(messages: ChatMessages, *, temperature: float = 0.1) -> ChatResult:
    """调用 DeepSeek 完成一轮对话；失败统一为上游错误，不当成知识库未命中。"""
    response = _create_chat_completion(messages, temperature=temperature)
    message = response.choices[0].message.content if response.choices else None
    answer = (message or "").strip()
    if not answer:
        raise UpstreamServiceError("上游模型返回空响应")
    return ChatResult(text=answer, usage=_usage_from_response(response))


def _append_history(
    messages: ChatMessages,
    history: list[tuple[str, str]] | None,
    *,
    conversation_summary: str | None = None,
) -> None:
    summary = (conversation_summary or "").strip()
    if summary:
        messages.append(
            {
                "role": "system",
                "content": f"以下是更早对话的摘要，仅供理解追问；不得覆盖本轮知识库依据，也不得当作来源或编造课程信息。\n\n{summary}",
            }
        )
    for role, content in history or []:
        if role not in ("user", "assistant"):
            continue
        text = (content or "").strip()
        if not text:
            continue
        messages.append({"role": role, "content": text})


def _build_messages(
    question: str,
    chunks: list[RetrievedChunk],
    history: list[tuple[str, str]] | None = None,
    *,
    conversation_summary: str | None = None,
) -> ChatMessages:
    if not chunks:
        raise ValueError("没有知识库依据，不能调用模型作答")
    messages: ChatMessages = [{"role": "system", "content": _SYSTEM_KB_ONLY}]
    _append_history(messages, history, conversation_summary=conversation_summary)
    messages.append(
        {"role": "user", "content": _build_current_user_prompt(question, chunks)}
    )
    return messages


def stream_chat(
    messages: ChatMessages, *, temperature: float = 0.1
) -> Iterator[str | ChatResult]:
    """流式调用 DeepSeek：先产出文本增量，最后一条为 ChatResult。"""
    stream = _create_chat_completion(messages, temperature=temperature, stream=True)
    pieces: list[str] = []
    usage = ZERO_USAGE
    try:
        for chunk in stream:
            chunk_usage = getattr(chunk, "usage", None)
            if chunk_usage is not None:
                usage = _usage_from_response(chunk)
            choices = getattr(chunk, "choices", None) or []
            if not choices:
                continue
            delta = getattr(choices[0], "delta", None)
            piece = getattr(delta, "content", None) if delta is not None else None
            if piece:
                pieces.append(piece)
                yield piece
    except UpstreamServiceError:
        raise
    except (APIConnectionError, APIStatusError, TimeoutError) as exc:
        raise UpstreamServiceError("上游模型调用失败") from exc
    except Exception as exc:
        raise UpstreamServiceError("上游模型调用失败") from exc
    answer = "".join(pieces).strip()
    if not answer:
        raise UpstreamServiceError("上游模型返回空响应")
    yield ChatResult(text=answer, usage=usage)


def generate_answer(
    question: str,
    chunks: list[RetrievedChunk],
    history: list[tuple[str, str]] | None = None,
    *,
    conversation_summary: str | None = None,
) -> ChatResult:
    """调用 DeepSeek 生成答案；history 为 (role, content) 多轮，本轮依据在最后一条。"""
    return complete_chat(
        _build_messages(
            question, chunks, history, conversation_summary=conversation_summary
        )
    )


def generate_answer_stream(
    question: str,
    chunks: list[RetrievedChunk],
    history: list[tuple[str, str]] | None = None,
    *,
    conversation_summary: str | None = None,
) -> Iterator[str | ChatResult]:
    """流式生成答案：yield 文本增量，最后 yield ChatResult。"""
    yield from stream_chat(
        _build_messages(
            question, chunks, history, conversation_summary=conversation_summary
        )
    )
