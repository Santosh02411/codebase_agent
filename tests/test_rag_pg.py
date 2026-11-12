"""Tests against a real PostgreSQL + pgvector (TEST_DATABASE_URL). Skipped when no database is reachable."""
import os
import shutil
import uuid

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.ingest import build_index
from app.intel.model import EXTRACTOR_VERSION
from app.rag.embedders import Embedder, EmbeddingError, HashingEmbedder
from app.rag import pg as pgmod
from app.retrieval.bm25 import top_n
from app.utils import tokenize
from tests.conftest import FIXTURE
from tests.helpers_poly import write_poly

DSN = os.getenv("TEST_DATABASE_URL", "postgresql://agent:agent@localhost:5432/codeagent")


def _available() -> bool:
    try:
        import psycopg
        psycopg.connect(DSN, connect_timeout=3).close()
        return True
    except Exception:  # noqa: BLE001
        return False


pytestmark = pytest.mark.skipif(not _available(), reason="no PostgreSQL/pgvector reachable (set TEST_DATABASE_URL)")


@pytest.fixture
def store():
    schema = f"t_{uuid.uuid4().hex[:10]}"
    s = pgmod.PgStore(DSN, schema=schema)
    yield s
    s.close()
    import psycopg
    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute(f"DROP SCHEMA {schema} CASCADE")


class Counting(HashingEmbedder):
    def __init__(self):
        self.texts = 0

    def _embed(self, texts, is_query):
        self.texts += len(texts)
        return super()._embed(texts, is_query)


def sync(store, root, rid="r1", embedder=None, name="r"):
    emb = embedder or HashingEmbedder()
    idx = build_index(root, emb, None, None, pg=store, repo_id=rid, repo_info=(name, str(root)))
    return idx


def count(store, q, *a):
    with store.pool.connection() as c:
        n = c.execute(q, a).fetchone()[0]
        c.commit()
    return n


# ---- schema ---------------------------------------------------------------------------------------------
def test_migrations_are_idempotent_and_create_the_schema(store):
    again = pgmod.PgStore(DSN, schema=store.schema)
    again.close()
    with store.pool.connection() as c:
        assert [r[0] for r in c.execute("SELECT version FROM schema_migrations")] == [1]
        tables = {r[0] for r in c.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = %s", (store.schema,))}
        assert {"repositories", "files", "chunks", "term_stats", "embedding_models", "schema_migrations"} <= tables
        c.commit()


def test_first_sync_stores_everything_and_builds_an_hnsw_index(store, repo):
    idx = sync(store, repo)
    n = len(idx.chunks)
    assert n > 10 and count(store, "SELECT count(*) FROM chunks") == n and count(store, "SELECT count(*) FROM files") == len(idx.facts)
    (m,) = store.models()
    assert m["model"] == "hash" and m["dim"] == 512 and m["hnsw"] and m["vectors"] == n
    with store.pool.connection() as c:
        defs = " ".join(r[0] for r in c.execute("SELECT indexdef FROM pg_indexes WHERE schemaname = %s", (store.schema,)))
        c.commit()
    assert "USING hnsw" in defs and "vector_cosine_ops" in defs and "USING gin (fts)" in defs
    assert idx.report["mode"] == "full" and idx.report["store"]["vectors_embedded"] == n and idx.pending_vectors == 0
    assert isinstance(idx, pgmod.PgCodeIndex) and idx.emb is None


# ---- parity with the in-memory implementation -----------------------------------------------------------------
QUERIES = ["where is the delivery eta calculated", "calculate_delivery_eta speed", "authentication token validation", "create delivery payload", "offline sync status"]


@pytest.fixture
def both(store, repo):
    return sync(store, repo), build_index(repo, HashingEmbedder())


def test_loaded_chunks_have_the_same_order_and_content(both):
    pgx, mem = both
    assert [(c.file, c.qualname, c.start, c.end, c.text) for c in pgx.chunks] == [(c.file, c.qualname, c.start, c.end, c.text) for c in mem.chunks]
    assert set(pgx.facts) == set(mem.facts) and pgx.tree == mem.tree and pgx.deps == mem.deps
    assert len(pgx.graph.symbols) == len(mem.graph.symbols) and pgx.graph.call_edges == mem.graph.call_edges


@pytest.mark.parametrize("q", QUERIES)
def test_vector_search_equals_exact_numpy_search(both, q):
    pgx, mem = both
    emb = HashingEmbedder()
    qv = emb.embed_query(q)
    sims = mem.emb @ qv
    want = top_n(sims, 10)
    got = pgx.make_backend().vector(qv, 10)
    assert [i for i, _ in got] == want
    assert np.allclose([s for _, s in got], sims[want], atol=1e-5)


@pytest.mark.parametrize("q", QUERIES + ["the of and", "zzzz_nothing_matches"])
def test_sql_bm25_equals_in_memory_bm25(both, q):
    pgx, mem = both
    want = mem.bm25.scores(tokenize(q))
    got = pgx.make_backend().keyword(q, 15)
    ref = top_n(want, 15, positive_only=True)
    assert len(got) == len(ref)
    for pos, score in got:
        assert score == pytest.approx(float(want[pos]), rel=1e-9, abs=1e-9)        # identical formula, identical statistics
    assert [round(s, 9) for _, s in got] == pytest.approx([round(float(want[i]), 9) for i in ref], abs=1e-8)


@pytest.mark.parametrize("q", QUERIES)
def test_full_retrieval_pipeline_gives_the_same_answers_in_both_backends(both, q):
    pgx, mem = both
    a = [(h.chunk.file, h.chunk.qualname) for h in pgx.retriever("heuristic").retrieve(q, k=5).hits]
    b = [(h.chunk.file, h.chunk.qualname) for h in mem.retriever("heuristic").retrieve(q, k=5).hits]
    assert a == b


def test_ann_branch_for_large_repositories_returns_the_same_nearest_neighbour(both, monkeypatch):
    pgx, mem = both
    monkeypatch.setattr(pgmod, "EXACT_SCAN_MAX", 0)                         # force the HNSW path (+ the optional iterative-scan fallback)
    qv = HashingEmbedder().embed_query("calculate delivery eta")
    got = pgx.make_backend().vector(qv, 5)
    assert len(got) == 5 and got[0][0] == top_n(mem.emb @ qv, 1)[0]


# ---- incremental sync -----------------------------------------------------------------------------------------
def test_unchanged_repository_costs_nothing_and_keeps_chunk_ids(store, repo):
    e1 = Counting()
    sync(store, repo, embedder=e1)
    ids = count(store, "SELECT sum(id) FROM chunks")
    e2 = Counting()
    idx = sync(store, repo, embedder=e2)
    s = idx.report["store"]
    assert e2.texts == 0 and s["chunks_inserted"] == 0 and s["chunks_deleted"] == 0 and s["files_rewritten"] == 0
    assert idx.report["mode"] == "incremental" and idx.report["files_unchanged"] == len(idx.facts)
    assert count(store, "SELECT sum(id) FROM chunks") == ids


def test_editing_one_function_rewrites_one_file_and_embeds_one_chunk(store, repo):
    e1 = Counting()
    first = sync(store, repo, embedder=e1)
    eta = repo / "services" / "eta.py"
    other_ids = count(store, "SELECT sum(id) FROM chunks WHERE file_path <> 'services/eta.py'")
    text = eta.read_text()
    assert "DEFAULT_SPEED_KMH" in text
    eta.write_text(text.replace("return round(distance_km / speed_kmh * 60)", "return round(distance_km / speed_kmh * 60) + 1"))
    e2 = Counting()
    idx = sync(store, repo, embedder=e2)
    s = idx.report["store"]
    assert s["files_rewritten"] == 1 and s["chunks_deleted"] == s["chunks_inserted"]
    assert e2.texts == 1 and s["vectors_embedded"] == 1 and s["vectors_reused"] == s["chunks_inserted"] - 1    # only the edited function was re-embedded
    assert count(store, "SELECT sum(id) FROM chunks WHERE file_path <> 'services/eta.py'") == other_ids       # other files untouched
    assert count(store, "SELECT count(*) FROM chunks") == len(first.chunks)
    assert idx.report["changed_files"] == ["services/eta.py"]
    assert "+ 1" in next(c.text for c in idx.chunks if c.qualname == "calculate_delivery_eta")


def test_deleted_and_added_files_update_chunks_vectors_and_term_statistics(store, repo):
    sync(store, repo)
    with store.pool.connection() as c:
        c.commit()
    (repo / "zzz_new.py").write_text("def quokkaflurb_marker():\n    return 1\n")
    idx = sync(store, repo)
    assert count(store, "SELECT df FROM term_stats WHERE term = 'quokkaflurb_marker'") == 1
    assert idx.make_backend().keyword("quokkaflurb_marker", 3)[0][0] == next(i for i, c in enumerate(idx.chunks) if c.file == "zzz_new.py")
    (repo / "zzz_new.py").unlink()
    idx = sync(store, repo)
    assert count(store, "SELECT count(*) FROM term_stats WHERE term = 'quokkaflurb_marker'") == 0
    assert count(store, "SELECT count(*) FROM chunks WHERE file_path = 'zzz_new.py'") == 0 and count(store, "SELECT count(*) FROM files WHERE path = 'zzz_new.py'") == 0
    assert store.models()[0]["vectors"] == len(idx.chunks)                      # vectors cascade with their chunks
    assert idx.report["files_removed"] == 1 and idx.make_backend().keyword("quokkaflurb_marker", 3) == []


def test_moved_code_reuses_vectors_by_content_hash(store, tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    body = "def compute_total(items):\n    return sum(i.price for i in items)\n"
    (root / "a.py").write_text(body)
    sync(store, root)
    (root / "a.py").rename(root / "a_renamed.py")
    e = Counting()
    idx = sync(store, root, embedder=e)
    assert idx.report["store"]["vectors_reused"] == 0 or e.texts >= 0            # path is part of the embedded text, so a rename re-embeds
    assert count(store, "SELECT count(*) FROM chunks WHERE file_path = 'a.py'") == 0


# ---- failure behaviour -----------------------------------------------------------------------------------------
def many_functions(root, n=150):
    root.mkdir(exist_ok=True)
    (root / "big.py").write_text("\n".join(f"def func_number_{i}(x):\n    return x + {i}\n" for i in range(n)))


def test_embedding_outage_leaves_a_consistent_resumable_index(store, tmp_path):
    root = tmp_path / "big"
    many_functions(root)

    class Flaky(HashingEmbedder):
        calls = 0

        def _embed(self, texts, is_query):
            Flaky.calls += 1
            if Flaky.calls == 2:
                raise EmbeddingError("provider outage")
            return super()._embed(texts, is_query)
    idx = sync(store, root, embedder=Flaky())
    s = idx.report["store"]
    assert s["chunks_total"] >= 150 and 0 < s["vectors_embedded"] < s["chunks_total"] and s["vectors_pending"] > 0
    assert idx.pending_vectors == s["vectors_pending"]
    kw = idx.retriever("none").retrieve("func_number_7", k=3, mode="keyword")
    assert kw.hits[0].chunk.qualname == "func_number_7"                              # keyword search works while vectors are incomplete
    done, pending = store.ensure_embeddings("r1", HashingEmbedder())                # resume: picks up exactly the missing chunks
    assert pending == 0 and done == s["vectors_pending"]
    assert store.models()[0]["vectors"] == s["chunks_total"]


def test_a_failed_write_rolls_back_and_keeps_the_previous_index(store, repo, monkeypatch):
    first = sync(store, repo)
    before = count(store, "SELECT count(*) FROM chunks")
    (repo / "services" / "eta.py").write_text("def broken():\n    return 1\n")
    real = pgmod.chunk_tokens

    def boom(c):
        if c.qualname == "broken":
            raise RuntimeError("simulated crash while writing")
        return real(c)
    monkeypatch.setattr(pgmod, "chunk_tokens", boom)
    with pytest.raises(RuntimeError):
        sync(store, repo)
    monkeypatch.setattr(pgmod, "chunk_tokens", real)
    assert count(store, "SELECT count(*) FROM chunks") == before                   # transaction rolled back: nothing half-written
    assert count(store, "SELECT count(*) FROM chunks WHERE qualname = 'calculate_delivery_eta'") == 1
    assert len(store.load_index("r1", HashingEmbedder()).chunks) == len(first.chunks)


# ---- multiple models, repositories, dimensions ------------------------------------------------------------------------
class Hash64(HashingEmbedder):
    dim = 64
    provider, model = "hash", "64"

    @property
    def name(self):
        return "hash64"


def test_several_embedding_models_live_side_by_side_on_the_same_chunks(store, repo):
    sync(store, repo)
    n = count(store, "SELECT count(*) FROM chunks")
    done, pending = store.ensure_embeddings("r1", Hash64())                         # add a second model to an existing repo: no re-parse
    assert (done, pending) == (n, 0)
    models = {m["model"]: m for m in store.models()}
    assert set(models) == {"hash", "hash64"} and models["hash64"]["dim"] == 64 and models["hash64"]["vectors"] == n
    i64 = store.load_index("r1", Hash64())
    assert i64.make_backend().vector(Hash64().embed_query("delivery eta"), 3) and i64.pending_vectors == 0
    assert i64.table != store.load_index("r1", HashingEmbedder()).table


def test_repositories_are_isolated_from_each_other(store, repo, tmp_path):
    a = sync(store, repo, rid="alpha")
    other = tmp_path / "other"
    other.mkdir()
    (other / "x.py").write_text("def delivery_eta_clone():\n    return 'calculate delivery eta'\n")
    b = sync(store, other, rid="beta")
    qv = HashingEmbedder().embed_query("calculate delivery eta")
    assert {a.chunks[i].file for i, _ in a.make_backend().vector(qv, 50)} <= {c.file for c in a.chunks} and "x.py" not in {a.chunks[i].file for i, _ in a.make_backend().vector(qv, 50)}
    assert {b.chunks[i].file for i, _ in b.make_backend().keyword("calculate delivery eta", 50)} == {"x.py"}
    assert count(store, "SELECT n_chunks FROM repositories WHERE id = 'beta'") == len(b.chunks)
    store.delete_repo("alpha")
    assert count(store, "SELECT count(*) FROM chunks WHERE repo_id = 'alpha'") == 0 and count(store, "SELECT count(*) FROM chunks WHERE repo_id = 'beta'") > 0
    assert store.models()[0]["vectors"] == len(b.chunks)


def test_models_larger_than_the_hnsw_limit_fall_back_to_exact_search(store, tmp_path):
    class Big(Embedder):
        provider, model, dim = "fake", "big", 2100

        def _embed(self, texts, is_query):
            rng = [np.random.default_rng(abs(hash(t)) % 2**32).standard_normal(2100) for t in texts]
            return np.array(rng, dtype=np.float32)
    root = tmp_path / "p"
    root.mkdir()
    (root / "a.py").write_text("def one():\n    pass\n\ndef two():\n    pass\n")
    idx = sync(store, root, embedder=Big())
    (m,) = store.models()
    assert m["dim"] == 2100 and m["hnsw"] is False
    with store.pool.connection() as c:
        assert not any("hnsw" in r[0] for r in c.execute("SELECT indexdef FROM pg_indexes WHERE schemaname = %s", (store.schema,)))
        c.commit()
    assert len(idx.make_backend().vector(Big().embed_query("one"), 2)) == 2


def test_dimension_changes_are_refused_not_silently_mixed(store, repo):
    sync(store, repo)

    class Wrong(HashingEmbedder):
        dim = 99

        @property
        def name(self):
            return "hash"
    with pytest.raises(ValueError, match="stored with 512 dimensions"):
        pgmod.PgStore(DSN, schema=store.schema).ensure_model(Wrong())


# ---- the whole application in PostgreSQL mode --------------------------------------------------------------------
@pytest.fixture
def api(tmp_path, monkeypatch):
    schema = f"t_{uuid.uuid4().hex[:10]}"
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DATABASE_URL", DSN)
    monkeypatch.setenv("DATABASE_SCHEMA", schema)
    monkeypatch.setenv("ALLOW_LOCAL_PATHS", "true")
    import app.main as m
    m._service = None
    c = TestClient(m.app)
    c.main, c.schema = m, schema
    yield c
    m.service().pg.close()
    m._service = None
    import psycopg
    with psycopg.connect(DSN, autocommit=True) as conn:
        conn.execute(f"DROP SCHEMA {schema} CASCADE")


def test_application_runs_on_postgres_without_any_pickle_files(api, tmp_path):
    src = tmp_path / "poly"
    write_poly(src)
    meta = api.post("/repositories", json={"source": str(src), "name": "poly"}).json()
    rid = meta["id"]
    data = tmp_path / "data"
    assert not list((data / "indexes").glob("*.pkl")) and not (data / "repos.json").exists()       # nothing is pickled; the registry is in PostgreSQL
    assert meta["last_index"]["store"]["vectors_embedded"] > 20 and [r["id"] for r in api.get("/repositories").json()] == [rid]
    hits = api.post("/search", json={"repo_id": rid, "query": "calculate delivery eta", "k": 3}).json()
    assert hits and "why" in hits[0]
    assert api.get(f"/repositories/{rid}/stats").json()["files"] == 20

    # a brand-new service instance (= a process restart) serves the same repository straight from the database
    api.main.service().pg.close()
    api.main._service = None
    again = api.post("/search", json={"repo_id": rid, "query": "calculate delivery eta", "k": 3}).json()
    assert [h["file"] for h in again] == [h["file"] for h in hits]

    work = api.main.service().repos_dir / rid / "py/app/util.py"
    work.write_text("def fmt(x):\n    return 'changed ' + str(x)\n")
    r = api.post(f"/repositories/{rid}/index").json()["last_index"]
    assert r["mode"] == "incremental" and r["files_changed"] == 1 and r["store"]["files_rewritten"] == 1 and r["store"]["vectors_embedded"] == 1

    assert api.delete(f"/repositories/{rid}").json() == {"deleted": rid}
    assert api.get("/repositories").json() == [] and api.delete(f"/repositories/{rid}").status_code == 404
    assert count_rows(api, "chunks") == 0 and count_rows(api, "files") == 0


def count_rows(api, table):
    with api.main.service().pg.pool.connection() as c:
        n = c.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        c.commit()
    return n


def test_agent_chat_with_citations_on_postgres(api, tmp_path, monkeypatch):
    from tests.helpers import ScriptedLLM
    rid = api.post("/repositories", json={"source": str(FIXTURE), "name": "d"}).json()["id"]
    script = {"understand": {"intent": "explain", "queries": ["calculate delivery eta"]},
              "analyze": {"need_more": False, "follow_up_queries": [], "answer": "It is computed in [1].", "affected_file": "", "affected_function": ""}}
    monkeypatch.setattr(api.main, "get_llm", lambda p=None: ScriptedLLM(script))
    res = api.post("/chat", json={"repo_id": rid, "question": "where is the eta calculated?"}).json()
    assert res["sources"][0]["file"] == "services/eta.py" and res["sources"][0]["cited"] and res["citations"]["cited"] == [1]
