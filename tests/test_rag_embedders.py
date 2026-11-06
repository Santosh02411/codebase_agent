import json
import sys
import types

import httpx
import numpy as np
import pytest

from app.rag import embedders as em


@pytest.fixture
def http(monkeypatch):
    """Route every provider HTTP call to a handler; record requests and sleeps."""
    state = types.SimpleNamespace(requests=[], sleeps=[], handler=None)

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        state.requests.append((str(req.url), dict(req.headers), body))
        return state.handler(req, body)

    monkeypatch.setattr(em, "_client", lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(em, "_sleep", lambda s: state.sleeps.append(s))
    return state


def openai_reply(dim=4):
    def h(req, body):
        rows = [{"index": i, "embedding": [float(i + 1)] + [0.5] * (dim - 1)} for i in range(len(body["input"]))]
        return httpx.Response(200, json={"data": list(reversed(rows)), "usage": {"total_tokens": 10 * len(rows)}})  # out of order on purpose
    return h


def test_openai_request_shape_ordering_normalisation_and_usage(http):
    http.handler = openai_reply()
    e = em.OpenAIEmbedder("sk-secret", "text-embedding-3-small", 4)
    v = e.embed_documents(["a", "b", "c"])
    url, headers, body = http.requests[0]
    assert url == "https://api.openai.com/v1/embeddings" and headers["authorization"] == "Bearer sk-secret"
    assert body == {"model": "text-embedding-3-small", "input": ["a", "b", "c"], "dimensions": 4}
    assert v.shape == (3, 4) and np.allclose(np.linalg.norm(v, axis=1), 1)
    assert v[0, 0] < v[2, 0]                          # restored input order despite shuffled response
    assert e.usage["tokens"] == 30 and e.usage["calls"] == 1 and e.name == "openai:text-embedding-3-small:4"


def test_openai_batches_and_truncates(http):
    http.handler = openai_reply()
    e = em.OpenAIEmbedder("k", "text-embedding-3-small", 4)
    out = e.embed_documents([f"t{i}" for i in range(150)] + ["x" * 50_000, ""])
    assert out.shape == (152, 4) and len(http.requests) == 3                        # 64 + 64 + 24
    sent = [t for _, _, b in http.requests for t in b["input"]]
    assert max(len(t) for t in sent) <= 8000 and "" not in sent                     # empty strings would be rejected by the API


def test_openai_retries_rate_limits_then_succeeds(http):
    calls = {"n": 0}

    def h(req, body):
        calls["n"] += 1
        if calls["n"] <= 2:
            return httpx.Response(429, headers={"retry-after": "3"}, json={"error": {"message": "slow down"}})
        return openai_reply()(req, body)
    http.handler = h
    em.OpenAIEmbedder("k", "text-embedding-3-small", 4).embed_documents(["a"])
    assert calls["n"] == 3 and http.sleeps[0] == 3.0 and http.sleeps[1] >= 3.0       # honours Retry-After, then backs off


def test_openai_errors_are_clear_and_never_leak_the_key(http):
    http.handler = lambda req, body: httpx.Response(401, json={"error": {"message": "Incorrect API key provided"}})
    with pytest.raises(em.EmbeddingError) as ei:
        em.OpenAIEmbedder("sk-very-secret", "m", 4).embed_documents(["a"])
    assert "401" in str(ei.value) and "sk-very-secret" not in str(ei.value) and http.sleeps == []     # 401 is not retried
    http.handler = lambda req, body: httpx.Response(503, json={})
    with pytest.raises(em.EmbeddingError, match="after 6 attempts"):
        em.OpenAIEmbedder("k", "m", 4).embed_documents(["a"])
    with pytest.raises(em.EmbeddingError, match="OPENAI_API_KEY"):
        em.OpenAIEmbedder("", "m")


def test_openai_compatible_server_needs_no_key(http):
    http.handler = openai_reply()
    e = em.OpenAIEmbedder("", "bge-small", None, base_url="http://localhost:11434/v1/")
    e.embed_documents(["a"])
    assert http.requests[0][0] == "http://localhost:11434/v1/embeddings" and "authorization" not in http.requests[0][1]
    assert "dimensions" not in http.requests[0][2]


def gemini_reply(dim=6):
    return lambda req, body: httpx.Response(200, json={"embeddings": [{"values": [float(i + 1)] + [1.0] * (dim - 1)} for i, _ in enumerate(body["requests"])]})


def test_gemini_uses_asymmetric_task_types_and_code_queries(http):
    http.handler = gemini_reply()
    e = em.GeminiEmbedder("g-key", "gemini-embedding-001", 6)
    e.embed_documents(["def f(): pass"])
    e.embed_query("where is f defined")
    (u1, h1, b1), (u2, _, b2) = http.requests
    assert u1.endswith("/models/gemini-embedding-001:batchEmbedContents") and h1["x-goog-api-key"] == "g-key"
    assert b1["requests"][0]["taskType"] == "RETRIEVAL_DOCUMENT" and b2["requests"][0]["taskType"] == "CODE_RETRIEVAL_QUERY"
    assert b1["requests"][0]["outputDimensionality"] == 6 and b1["requests"][0]["model"] == "models/gemini-embedding-001"
    em.GeminiEmbedder("k", "text-embedding-004").embed_query("q")
    assert http.requests[-1][2]["requests"][0]["taskType"] == "RETRIEVAL_QUERY"         # code query type only exists on -001


def test_gemini_batches_of_100_and_renormalises_truncated_dims(http):
    http.handler = gemini_reply()
    e = em.GeminiEmbedder("k", "gemini-embedding-001", 6)
    v = e.embed_documents([f"t{i}" for i in range(230)])
    assert [len(b["requests"]) for _, _, b in http.requests] == [100, 100, 30]
    assert np.allclose(np.linalg.norm(v, axis=1), 1)                                     # API returns un-normalised vectors for truncated dims
    with pytest.raises(em.EmbeddingError, match="GEMINI_API_KEY"):
        em.GeminiEmbedder("")


def test_spec_parsing_and_factory(monkeypatch):
    assert em.parse_spec("openai:text-embedding-3-small:512") == ("openai", "text-embedding-3-small", 512)
    assert em.parse_spec("bge:BAAI/bge-small-en-v1.5") == ("bge", "BAAI/bge-small-en-v1.5", None)
    assert em.parse_spec("hash") == ("hash", "", None)
    assert em.get_embedder("hash").name == "hash" and em.get_embedder("hash").dim == 512
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    e = em.get_embedder("openai:text-embedding-3-large:1024")
    assert (e.model, e.dim, e.name) == ("text-embedding-3-large", 1024, "openai:text-embedding-3-large:1024")
    with pytest.raises(em.EmbeddingError, match="unknown embedding provider"):
        em.get_embedder("nope:x")


def fake_st(monkeypatch, dim=8):
    seen = types.SimpleNamespace(inputs=[], kwargs=[])

    class ST:
        def __init__(self, name, device=None, trust_remote_code=False):
            self.name = name

        def get_sentence_embedding_dimension(self):
            return dim

        def encode(self, texts, **kw):
            seen.inputs.append(list(texts)); seen.kwargs.append(kw)
            return np.tile(np.arange(1, dim + 1, dtype=np.float32), (len(texts), 1))
    mod = types.ModuleType("sentence_transformers"); mod.SentenceTransformer = ST
    monkeypatch.setitem(sys.modules, "sentence_transformers", mod)
    return seen


def test_local_bge_model_applies_the_query_instruction_only_to_queries(monkeypatch):
    seen = fake_st(monkeypatch)
    e = em.SentenceTransformerEmbedder("BAAI/bge-small-en-v1.5")
    d = e.embed_documents(["def f(): pass"])
    q = e.embed_query("where is f")
    assert seen.inputs[0] == ["def f(): pass"] and seen.inputs[1] == ["Represent this sentence for searching relevant passages: where is f"]
    assert e.dim == 8 and np.isclose(np.linalg.norm(d[0]), 1) and np.isclose(np.linalg.norm(q), 1)
    assert seen.kwargs[0]["normalize_embeddings"] is True and e.name == "bge:BAAI/bge-small-en-v1.5"


@pytest.mark.parametrize("model,qp,dp", [("BAAI/bge-m3", "", ""), ("intfloat/e5-base-v2", "query: ", "passage: "), ("nomic-ai/nomic-embed-text-v1.5", "search_query: ", "search_document: ")])
def test_prefix_conventions_per_model_family(monkeypatch, model, qp, dp):
    seen = fake_st(monkeypatch)
    e = em.SentenceTransformerEmbedder(model)
    e.embed_documents(["d"]); e.embed_query("q")
    assert seen.inputs[0] == [dp + "d"] and seen.inputs[1] == [qp + "q"]


def test_missing_optional_packages_give_actionable_errors(monkeypatch):
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)
    with pytest.raises(em.EmbeddingError, match="pip install sentence-transformers"):
        em.SentenceTransformerEmbedder("BAAI/bge-small-en-v1.5")
    monkeypatch.setitem(sys.modules, "fastembed", None)
    with pytest.raises(em.EmbeddingError, match="pip install fastembed"):
        em.FastEmbedEmbedder()


def test_fastembed_path(monkeypatch):
    seen = []

    class TE:
        def __init__(self, model_name):
            pass

        def embed(self, texts, batch_size=32):
            seen.append(list(texts))
            for _ in texts:
                yield np.array([3.0, 4.0, 0.0], dtype=np.float32)
    mod = types.ModuleType("fastembed"); mod.TextEmbedding = TE
    monkeypatch.setitem(sys.modules, "fastembed", mod)
    e = em.FastEmbedEmbedder("BAAI/bge-small-en-v1.5")
    q = e.embed_query("hello")
    assert seen[-1][0].startswith("Represent this sentence") and e.dim == 3 and np.allclose(q, [0.6, 0.8, 0.0])


def test_hash_embedder_is_deterministic_and_symmetric():
    e = em.HashingEmbedder()
    a, b = e.embed_documents(["calculate delivery eta"]), e.embed_query("calculate delivery eta")
    assert np.allclose(a[0], b) and np.isclose(np.linalg.norm(b), 1)
    assert em.HashingEmbedder().embed_documents([""]).sum() == 0                         # empty text -> zero vector, no NaN
