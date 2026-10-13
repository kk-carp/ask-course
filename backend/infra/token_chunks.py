"""Tokenizer-bounded slices, checked again after slicing the source text."""
from backend.config import settings
from backend.infra.embed import _ensure_model


def token_safe_chunks(chunks):
    if not settings.embed_token_limit:
        return chunks
    tokenizer = _ensure_model().tokenizer
    budget = settings.embed_token_limit - tokenizer.num_special_tokens_to_add(pair=False) - 4
    if budget < 16:
        raise ValueError("模型 token 预算过小")
    result = []
    for chunk in chunks:
        if len(tokenizer.encode(chunk, add_special_tokens=True)) <= settings.embed_token_limit:
            result.append(chunk)
            continue
        offsets = tokenizer(chunk, add_special_tokens=False, return_offsets_mapping=True)["offset_mapping"]
        start = 0
        while start < len(offsets):
            end = min(start + budget, len(offsets))
            left = 0 if start == 0 else offsets[start][0]
            right = len(chunk) if end == len(offsets) else offsets[end - 1][1]
            content = chunk[left:right]
            while len(tokenizer.encode(content, add_special_tokens=True)) > settings.embed_token_limit:
                if end - start <= 1:
                    raise ValueError("单个 token 对应的文本超过模型上限")
                end -= 1
                right = offsets[end - 1][1]
                content = chunk[left:right]
            result.append(content)
            if end == len(offsets):
                break
            overlap = min(64, (end - start) // 4)
            start = end - overlap
    return result
