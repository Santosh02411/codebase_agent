import math
import sys
import types

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.ingest import build_index
from app.parsing.chunker import Chunk
from app.rag import context as ctx
from app.rag import rerank as rr
from app.rag.embedders import EmbeddingError, HashingEmbedder
from app.rag.fusion import max_score, rrf
from app.rag.retriever import Hit, Retriever, RetrievalConfig
from app.retrieval.bm25 import BM25, bm25_idf, top_n
from tests.helpers import ScriptedLLM


# ---- fusion & BM25 -------------------------------------------------------------------------------------
def test_rrf_scores_weights_and_deterministic_ties():
    out = dict(rrf({"v": [1, 2, 3], "k": [3, 1]}, k=60))
    assert out[1] == pytest.approx(1 / 61 + 1 / 62) and out[3] == pytest.approx(1 / 63 + 1 / 61) and out[2] == pytest.approx(1 / 62)
    order = [d for d, _ in rrf({"v": [1, 2, 3], "k": [3, 1]})]
    assert order == [1, 3, 2]
    # a document found by both legs beats one found by a single leg even at a worse rank
    assert [d for d, _ in rrf({"v": [9, 5], "k": [5]})][0] == 5
    # weights shift the balance
    assert rrf({"v": [1], "k": [2]}, weights={"v": 1.0, "k": 3.0})[0][0] == 2
    # ties: equal fused score -> best individual rank, then id
    assert [d for d, _ in rrf({"a": [7], "b": [4]})] == [4, 7] or [d for d, _ in rrf({"a": [7], "b": [4]})] == [7, 4]
    assert rrf({}) == [] and max_score(2, 60) == pytest.approx(2 / 61) and max_score(2, 60, [1.0, 3.0]) == pytest.approx(4 / 61)


def test_bm25_matches_a_brute_force_implementation():
    docs = [["auth", "token", "token", "valid"], ["delivery", "eta", "speed"], ["auth", "user"], ["eta", "eta", "eta", "speed", "km", "h", "x"]]
    bm = BM25(docs)
    n, avg = len(docs), sum(map(len, docs)) / len(docs)

    def brute(q):
        total = np.zeros(n)
        for t in set(q):
            df = sum(t in d for d in docs)
            if not df:
                continue
            for i, d in enumerate(docs):
                f = d.count(t)
                total[i] += bm25_idf(n, df) * f * 2.5 / (f + 1.5 * (0.25 + 0.75 * len(d) / avg))
        return total
    for q in (["auth"], ["eta", "speed"], ["auth", "eta", "nonexistent"], []):
        assert np.allclose(bm.scores(q), brute(q))
    assert bm.scores(["zzz"]).sum() == 0


def test_top_n_breaks_ties_by_index_and_can_drop_zeros():
    s = np.array([0.5, 0.9, 0.5, 0.0, 0.9])
    assert top_n(s, 3) == [1, 4, 0] and top_n(s, 10, positive_only=True) == [1, 4, 0, 2] and top_n(np.array([]), 3) == []


def test_bm25_caps_very_long_queries_to_the_strongest_terms():
    docs = [[f"w{i}", "common"] for i in range(200)]
    bm = BM25(docs)
    q = [f"w{i}" for i in range(100)] + ["common"]
    assert len(bm.terms(q)) == 32 and all(t != "common" for t, _ in bm.terms(q))     # low-idf term dropped first


# ---- retriever -----------------------------------------------------------------------------------------
class Stub:
    """Search legs returning fixed rankings, so fusion behaviour is tested in isolation."""
    def __init__(self, vec, kw):
        self.vec, self.kw = vec, kw

    def vector(self, qvec, n):
        return self.vec[:n]

    def keyword(self, query, n):
        return self.kw[:n]


class FakeIndex:
    def __init__(self, n=10):
        self.chunks = [Chunk(i, f"f{i}.py", "function", f"fn{i}", f"fn{i}", 1, 5, f"def fn{i}(): pass", "python") for i in range(n)]


def retriever(vec, kw, **cfg):
    return Retriever(FakeIndex(), HashingEmbedder(), Stub(vec, kw), None, RetrievalConfig(**cfg))


def test_hybrid_fuses_both_legs_and_explains_each_hit():
    r = retriever([(1, .9), (2, .8), (3, .7)], [(3, 12.0), (4, 5.0), (1, 3.0)]).retrieve("q", k=4)
    ids = [h.chunk.id for h in r.hits]
    assert ids[:2] == [1, 3] and set(ids) == {1, 2, 3, 4}
    h1 = r.hits[0]
    assert (h1.vector_rank, h1.keyword_rank, h1.vector_score, h1.keyword_score) == (1, 3, .9, 3.0) and h1.why() == "vector #1, keyword #3"
    assert r.hits[-1].why() in ("vector #2", "keyword #2") and 0 < r.hits[0].score <= 1
    assert r.trace["vector_candidates"] == 3 and r.trace["keyword_candidates"] == 3 and r.trace["fused"] == 4


def test_vector_only_keyword_only_and_weights():
    rv = retriever([(1, .9)], [(2, 1.0)]).retrieve("q", k=3, mode="vector")
    rk = retriever([(1, .9)], [(2, 1.0)]).retrieve("q", k=3, mode="keyword")
    assert [h.chunk.id for h in rv.hits] == [1] and [h.chunk.id for h in rk.hits] == [2]
    heavy = retriever([(1, .9)], [(2, 1.0)], keyword_weight=5.0).retrieve("q", k=2)
    assert [h.chunk.id for h in heavy.hits] == [2, 1]


def test_pool_and_candidates_limits_and_reranker_hook():
    class Reverse:
        name = "reverse"
        def rerank(self, query, hits, top_n):
            for i, h in enumerate(reversed(hits)):
                h.rerank_score = float(i)
            return list(reversed(hits))[:top_n]
    r = Retriever(FakeIndex(), HashingEmbedder(), Stub([(i, 1 - i / 10) for i in range(10)], []), Reverse(), RetrievalConfig(pool=6))
    out = r.retrieve("q", k=2)
    assert [h.chunk.id for h in out.hits] == [5, 4] and out.trace["reranker"] == "reverse"          # reranked the pool of 6, kept 2
    assert [h.chunk.id for h in r.retrieve("q", k=2, rerank=False).hits] == [0, 1]
    assert len(r.retrieve("q", k=2, candidates=3, rerank=False).hits) == 2


def test_embedding_outage_degrades_to_keyword_search_with_a_warning():
    class Down(HashingEmbedder):
        def embed_query(self, text):
            raise EmbeddingError("503 from provider")
    r = Retriever(FakeIndex(), Down(), Stub([(1, .9)], [(2, 3.0), (3, 1.0)]), None, RetrievalConfig())
    out = r.retrieve("q", k=3)
    assert [h.chunk.id for h in out.hits] == [2, 3] and "503 from provider" in out.trace["warnings"][0]
    with pytest.raises(EmbeddingError):                                   # asking for vector-only must not silently return nothing
        r.retrieve("q", k=3, mode="vector")


def test_empty_index_and_blank_query():
    assert Retriever(types.SimpleNamespace(chunks=[]), HashingEmbedder(), Stub([], []), None).retrieve("x").hits == []
    assert retriever([(1, 1.0)], []).retrieve("   ").hits == []


@pytest.fixture(scope="module")
def idx(tmp_path_factory):
    from tests.conftest import FIXTURE
    return build_index(FIXTURE, HashingEmbedder())


def test_real_index_hybrid_beats_nothing_and_modes_differ(idx):
    fused = idx.retriever("none").retrieve("where is the delivery ETA calculated", k=5)
    assert "services/eta.py" in {h.chunk.file for h in fused.hits}                       # found, but not necessarily first...
    assert idx.retriever("heuristic").retrieve("where is the delivery ETA calculated", k=5).hits[0].chunk.file == "services/eta.py"   # ...until reranked
    kw = idx.retriever("none").retrieve("calculate_delivery_eta", k=3, mode="keyword")
    assert kw.hits[0].chunk.qualname == "calculate_delivery_eta" and kw.hits[0].vector_rank is None
    assert {h.chunk.id for h in idx.retriever("none").retrieve("speed", k=20, mode="vector").hits}


def test_search_code_tool_reports_why_and_trace(tools):
    hits = tools.search_code("calculate delivery eta", k=3)
    assert hits[0]["file"] == "services/eta.py" and "keyword #" in hits[0]["why"] or "vector #" in hits[0]["why"]
    assert tools.last_trace["mode"] == "hybrid" and tools.last_trace["reranker"] == "heuristic"


# ---- rerankers -----------------------------------------------------------------------------------------
def hit(i, text, file="a.py", kind="function", rrf_norm=0.5):
    c = Chunk(i, file, kind, f"fn{i}", f"fn{i}", 1, 5, text, "python")
    return Hit(c, score=rrf_norm, rrf=rrf_norm, rrf_norm=rrf_norm, rank_pool=i)


def fake_cross_encoder(monkeypatch, scorer):
    loads = []

    class CE:
        def __init__(self, model, max_length=512, device=None):
            loads.append(model)

        def predict(self, pairs, batch_size=16, show_progress_bar=False):
            return np.array([scorer(q, d) for q, d in pairs])
    mod = types.ModuleType("sentence_transformers"); mod.CrossEncoder = CE
    monkeypatch.setitem(sys.modules, "sentence_transformers", mod)
    rr.CrossEncoderReranker._loaded.clear()
    return loads


def test_cross_encoder_reorders_by_joint_relevance_and_loads_once(monkeypatch):
    loads = fake_cross_encoder(monkeypatch, lambda q, d: 8.0 if "token" in d else -6.0)
    r = rr.get_reranker("bge-reranker-base")
    hits = [hit(0, "def render(): pass"), hit(1, "def check_token(t): ...", rrf_norm=0.1), hit(2, "def other(): pass")]
    out = r.rerank("how is the token checked", hits, 2)
    assert [h.chunk.id for h in out] == [1, 0] and out[0].rerank_score > 0.99 and out[1].rerank_score < 0.01   # sigmoid of logits
    rr.get_reranker("bge-reranker-base")
    assert loads == ["BAAI/bge-reranker-base"] and r.name == "cross-encoder:BAAI/bge-reranker-base"


def test_cross_encoder_priors_keep_readmes_from_outranking_code(monkeypatch):
    fake_cross_encoder(monkeypatch, lambda q, d: 3.0)                     # the model likes everything equally
    r = rr.CrossEncoderReranker("m", priors=True)
    out = r.rerank("how does eta work", [hit(0, "# ETA docs", file="README.md", kind="module"), hit(1, "def eta(): ...", file="svc/eta.py")], 2)
    assert [h.chunk.file for h in out] == ["svc/eta.py", "README.md"]
    flat = rr.CrossEncoderReranker("m", priors=False).rerank("how does eta work", [hit(0, "# ETA docs", file="README.md", kind="module"), hit(1, "x", file="svc/eta.py")], 2)
    assert flat[0].score == flat[1].score


def test_reranker_specs_and_missing_dependencies(monkeypatch):
    assert isinstance(rr.get_reranker("none"), rr.NoopReranker)
    with pytest.raises(rr.RerankError, match="unknown reranker"):
        rr.get_reranker("magic")
    with pytest.raises(rr.RerankError, match="needs an index"):
        rr.get_reranker("heuristic")
    with pytest.raises(rr.RerankError, match="needs an LLM"):
        rr.get_reranker("llm")
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)
    with pytest.raises(rr.RerankError, match="pip install sentence-transformers"):
        rr.get_reranker("cross-encoder:cross-encoder/ms-marco-MiniLM-L-6-v2")
    assert rr.NoopReranker().rerank("q", [hit(0, "a"), hit(1, "b")], 1)[0].chunk.id == 0


def test_llm_reranker_orders_by_scores_and_never_fails_retrieval():
    hits = [hit(i, f"def f{i}(): pass") for i in range(4)]
    out = rr.LLMReranker(ScriptedLLM({"rerank": {"scores": {"0": 1, "1": 9, "2": 4, "3": "bad"}}})).rerank("q", list(hits), 3)
    assert [h.chunk.id for h in out] == [1, 2, 0] and out[0].rerank_score == 0.9
    assert [h.chunk.id for h in rr.LLMReranker(ScriptedLLM({"rerank": {"nonsense": 1}})).rerank("q", list(hits), 2)] == [0, 1]

    class Boom(ScriptedLLM):
        def json(self, *a, **k):
            raise RuntimeError("provider down")
    assert [h.chunk.id for h in rr.LLMReranker(Boom({})).rerank("q", list(hits), 2)] == [0, 1]


# ---- context & citations ---------------------------------------------------------------------------------
def cd(i, file="a.py", start=1, end=10, text=None, kind="function"):
    return {"id": i, "file": file, "start": start, "end": end, "qualname": f"fn{i}", "kind": kind, "route": "", "via": "search",
            "text": text if text is not None else f"def fn{i}():\n" + "    x = 1\n" * 20}


def test_pack_respects_the_token_budget_and_numbers_in_rank_order():
    chunks = [cd(i, file=f"f{i}.py") for i in range(10)]
    pack = ctx.build_pack(chunks, budget=300)
    assert pack.tokens <= 300 and 0 < len(pack.items) < 10
    assert [i.cite for i in pack.items] == list(range(1, len(pack.items) + 1))
    assert [i.chunk["id"] for i in pack.items] == sorted(i.chunk["id"] for i in pack.items)
    assert all(d["reason"] == "token budget" for d in pack.dropped)
    big = ctx.build_pack(chunks, budget=100_000)
    assert len(big.items) == 10 and not big.dropped


def test_pack_truncates_a_long_chunk_instead_of_dropping_it():
    long = cd(0, text="\n".join(f"line_{i} = {i}" for i in range(400)))
    pack = ctx.build_pack([long], budget=500)
    it = pack.items[0]
    assert it.truncated and it.chunk["text"].endswith("# ... (truncated)") and it.tokens <= 500 and "line_0 = 0" in it.chunk["text"]
    assert ctx.build_pack([long], budget=100).items == []                     # too small to be useful: skipped, not mangled


def test_pack_drops_overlapping_chunks_and_caps_files_but_refills_leftover_budget():
    a, b = cd(0, start=10, end=30), cd(1, start=12, end=28)                  # b sits inside a
    pack = ctx.build_pack([a, b], budget=10_000)
    assert [i.chunk["id"] for i in pack.items] == [0] and pack.dropped[0]["reason"].startswith("overlaps")
    same_file = [cd(i, start=i * 100, end=i * 100 + 5, text="x = 1") for i in range(6)] + [cd(9, file="other.py", text="y = 2")]
    first_pass = ctx.build_pack(same_file, budget=10_000, max_per_file=2)
    assert len(first_pass.items) == 7                                          # nothing is lost when there is room...
    tight = ctx.build_pack(same_file, budget=50, max_per_file=2)
    files = [i.chunk["file"] for i in tight.items]
    assert files.count("a.py") == 2 and "other.py" in files                    # ...but under pressure the cap keeps other files represented


def test_render_has_citation_headers_language_fences_and_routes():
    text = ctx.render_blocks([cd(0, file="svc/eta.py", start=3, end=9, text="def f(): pass"), dict(cd(1, file="app.js", kind="method"), route="GET /x")])
    assert text.startswith("[1] svc/eta.py:3-9 fn0 (function)\n```python\ndef f(): pass\n```")
    assert "[2] app.js:1-10 fn1 (method) · GET /x\n```javascript" in text


def test_citation_extraction_validates_markers_against_what_was_shown():
    out = ctx.extract_citations("Token checks happen in [1] and [3][2]; see also [1, 4] and [9].", n_items=4)
    assert out == {"cited": [1, 2, 3, 4], "invalid": [9]}
    code = ctx.extract_citations("Use `items[1]` or\n```python\nx = a[2]\n```\nbut the logic is in [2].", 5)
    assert code == {"cited": [2], "invalid": []}                                # indexing inside code is not a citation
    assert ctx.extract_citations("no markers", 3) == {"cited": [], "invalid": []} and ctx.extract_citations("", 0)["cited"] == []
    assert ctx.estimate_tokens("hello world " * 100) > 100


# ---- end to end: citations through the agent API ---------------------------------------------------------
def test_chat_answer_citations_are_validated_and_sources_sorted(tmp_path, monkeypatch):
    from tests.conftest import FIXTURE
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ALLOW_LOCAL_PATHS", "true")
    import app.main as m
    m._service = None
    c = TestClient(m.app)
    rid = c.post("/repositories", json={"source": str(FIXTURE), "name": "d"}).json()["id"]
    script = {"analyze_query": {"intent": "explain", "queries": ["calculate delivery eta"]},
              "analyze": {"need_more": False, "follow_up_queries": [], "answer": "ETA is computed in [2] using the speed from [99].", "affected_file": "", "affected_function": ""}}
    monkeypatch.setattr(m, "get_llm", lambda p=None: ScriptedLLM(script))
    res = c.post("/chat", json={"repo_id": rid, "question": "where is the eta calculated?"}).json()
    assert res["citations"] == {"cited": [2], "invalid": [99]}
    assert res["sources"][0]["cite"] == 2 and res["sources"][0]["cited"] is True
    assert all(s["cited"] is False for s in res["sources"][1:]) and {"file", "lines", "symbol", "cite", "cited"} <= set(res["sources"][0])
    assert any("invalid citation" in s["message"] for s in res["steps"])
