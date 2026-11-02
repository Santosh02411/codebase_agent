from app.ingest import build_index
from app.retrieval.embeddings import HashingEmbedder
from tests.helpers_poly import write_poly


class CountingEmbedder(HashingEmbedder):
    def __init__(self):
        self.texts = 0

    def embed(self, texts):
        self.texts += len(texts)
        return super().embed(texts)


def test_second_run_reprocesses_nothing(tmp_path):
    repo, cache = tmp_path / "r", tmp_path / "cache"
    write_poly(repo)
    e1 = CountingEmbedder()
    first = build_index(repo, e1, cache)
    assert first.report["mode"] == "full" and first.report["files_added"] == first.report["files_total"] == 20
    assert e1.texts == first.report["chunks_total"]

    e2 = CountingEmbedder()
    second = build_index(repo, e2, cache)
    r = second.report
    assert r["mode"] == "incremental" and r["files_unchanged"] == 20 and r["changed_files"] == []
    assert e2.texts == 0 and r["chunks_embedded"] == 0 and r["chunks_reused"] > 0       # nothing re-embedded
    assert len(second.chunks) == len(first.chunks) and len(second.graph.symbols) == len(first.graph.symbols)


def test_only_changed_files_are_reparsed_and_reembedded(tmp_path):
    repo, cache = tmp_path / "r", tmp_path / "cache"
    write_poly(repo)
    build_index(repo, CountingEmbedder(), cache)

    (repo / "py/app/util.py").write_text("def fmt(x):\n    return str(x)\n\ndef brand_new(y):\n    return fmt(y)\n")
    (repo / "py/app/services/eta.py").unlink()
    (repo / "py/app/newmod.py").write_text("def added():\n    return 1\n")
    e = CountingEmbedder()
    idx = build_index(repo, e, cache)
    r = idx.report
    assert (r["files_changed"], r["files_added"], r["files_removed"]) == (1, 1, 1)
    assert sorted(r["changed_files"]) == ["py/app/newmod.py", "py/app/util.py"]
    assert r["files_unchanged"] == 18
    assert 0 < e.texts <= 5 and r["chunks_reused"] > 30                                 # a handful of chunks, not all ~45
    assert "py/app/util.py::brand_new" in idx.graph.symbols and "py/app/newmod.py::added" in idx.graph.symbols
    assert not any(s.file == "py/app/services/eta.py" for s in idx.graph.symbols.values())
    # the graph is rebuilt globally: the call into the deleted file is now unresolved, not stale
    assert not any(t.startswith("py/app/services/eta.py") for m in idx.graph.call_edges.values() for t in m)
    assert idx.search("brand new function fmt", k=3)[0][0].qualname in ("brand_new", "fmt")


def test_incremental_result_equals_full_rebuild(tmp_path):
    repo, cache = tmp_path / "r", tmp_path / "cache"
    write_poly(repo)
    build_index(repo, HashingEmbedder(), cache)
    (repo / "web/src/ui.ts").write_text("export function render() { draw(); }\nexport function draw() {}\nexport function extra() {}\n")
    inc = build_index(repo, HashingEmbedder(), cache)
    full = build_index(repo, HashingEmbedder())
    assert [(c.file, c.qualname, c.start, c.end) for c in inc.chunks] == [(c.file, c.qualname, c.start, c.end) for c in full.chunks]
    assert inc.graph.call_edges == full.graph.call_edges and inc.graph.module_edges == full.graph.module_edges
    assert (inc.emb == full.emb).all()


def test_cache_is_discarded_when_embedder_or_extractor_changes(tmp_path, monkeypatch):
    repo, cache = tmp_path / "r", tmp_path / "cache"
    write_poly(repo)
    build_index(repo, CountingEmbedder(), cache)

    class Other(CountingEmbedder):
        name = "other"
    e = Other()
    idx = build_index(repo, e, cache)
    assert idx.report["files_unchanged"] == 20 and e.texts == idx.report["chunks_total"]     # parsing reused, vectors recomputed

    import app.intel.store as store
    monkeypatch.setattr(store, "EXTRACTOR_VERSION", store.EXTRACTOR_VERSION + 1)
    idx = build_index(repo, e, cache)
    assert idx.report["mode"] == "full" and idx.report["files_unchanged"] == 0


def test_unreadable_and_binary_files_are_skipped(tmp_path):
    (tmp_path / "ok.py").write_text("def f():\n    pass\n")
    (tmp_path / "bin.py").write_bytes(b"\xff\xfe\x00\x01")
    idx = build_index(tmp_path, HashingEmbedder(), tmp_path / "c")
    assert idx.tree == ["ok.py"]
