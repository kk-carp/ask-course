from types import SimpleNamespace
import pytest
from backend.infra import embed, token_chunks
from backend.config import settings

class Tokenizer:
    def num_special_tokens_to_add(self, pair=False): return 2
    def __call__(self, text, **kwargs): return {"offset_mapping": [(i,i+1) for i in range(len(text))]}
    def encode(self, text, add_special_tokens=True): return list(text) + ([0,0] if add_special_tokens else [])

def test_token_slices_fit_and_cover_source(monkeypatch):
    monkeypatch.setattr(settings, "embed_token_limit", 32)
    monkeypatch.setattr(token_chunks, "_ensure_model", lambda: SimpleNamespace(tokenizer=Tokenizer()))
    source="机器人仿真话题通信"*30
    chunks=token_chunks.token_safe_chunks([source])
    assert len(chunks)>1
    assert all(len(c)+2<=32 for c in chunks)
    assert chunks[0].startswith(source[:20]) and chunks[-1].endswith(source[-10:])
    assert all(source[i:i+10] in "\n".join(chunks) for i in range(len(source)-10))

def test_long_documents_fail_instead_of_truncating(monkeypatch):
    monkeypatch.setattr(settings, "embed_token_limit", 32)
    monkeypatch.setattr(embed, "_ensure_model", lambda: SimpleNamespace(tokenizer=Tokenizer()))
    with pytest.raises(ValueError, match="token"):
        embed.encode_documents(["x"*31])

def test_query_instruction_only_on_queries(monkeypatch):
    monkeypatch.setattr(settings, "embed_query_instruction", "检索：")
    monkeypatch.setattr(settings, "embed_token_limit", 32)
    monkeypatch.setattr(embed, "_ensure_model", lambda: SimpleNamespace(tokenizer=Tokenizer()))
    seen=[]
    monkeypatch.setattr(embed, "encode_documents", lambda texts: seen.extend(texts) or [[1.0]])
    assert embed.encode_query("机器人") == [1.0]
    assert seen==["检索：机器人"]


def test_retokenized_slices_are_rechecked_and_cover_unique_source(monkeypatch):
    class ExpandingTokenizer(Tokenizer):
        def encode(self, text, add_special_tokens=True):
            # Re-tokenizing a substring can add more tokens than the source offsets predict.
            return list(text) + [0] * 10
    tokenizer = ExpandingTokenizer()
    monkeypatch.setattr(settings, "embed_token_limit", 32)
    monkeypatch.setattr(token_chunks, "_ensure_model", lambda: SimpleNamespace(tokenizer=tokenizer))
    source = "".join(chr(0x4e00+i) for i in range(100))
    chunks = token_chunks.token_safe_chunks([source])
    assert all(len(tokenizer.encode(c)) <= 32 for c in chunks)
    assert all(c in "".join(chunks) for c in source)
    assert chunks[0].startswith(source[:10]) and chunks[-1].endswith(source[-10:])


def test_model_dimension_failure_remains_diagnostic(monkeypatch):
    import sys
    from backend.errors import ServiceUnavailableError
    monkeypatch.setattr(embed, "_model", None)
    monkeypatch.setattr(settings, "embedding_dim", 512)
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(cuda=SimpleNamespace(is_available=lambda:False),set_num_threads=lambda n:None))
    monkeypatch.setitem(sys.modules, "sentence_transformers", SimpleNamespace(SentenceTransformer=lambda *a,**kw: SimpleNamespace(get_embedding_dimension=lambda:1024)))
    with pytest.raises(ServiceUnavailableError, match="维度与配置不一致"):
        embed.load_model()
    assert embed._model is None
