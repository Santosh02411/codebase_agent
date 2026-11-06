import json
import math
import os
import uuid
from pathlib import Path

import pytest

from app import ingest
from app.ingest import build_index, is_ignored, iter_source_files
from app.rag.embedders import EmbeddingError, HashingEmbedder
from app.rag.eval import __main__ as cli
from app.rag.eval import runner
from app.rag.eval.dataset import Dataset, Expected, Question, load_dataset, validate
from app.rag.eval.generate import generate_questions
from app.rag.eval.metrics import (Ref, bootstrap_ci, context_metrics, matches, paired_bootstrap_p, relevance, retrieval_metrics)
from app.rag.eval.report import to_csv, to_markdown
from app.rag.eval.runner import ExpConfig, preset_configs, run_experiment, save_result
from tests.conftest import FIXTURE
from tests.helpers import ScriptedLLM

ROOT = Path(__file__).resolve().parents[1]
A, B = Expected("a.py", "f"), Expected("b.py", "g")


def R(file, sym="x", s=1, e=5):
    return Ref(file, sym, s, e)


# ---- metrics: values computed by hand -----------------------------------------------------------------------
def test_ranking_metrics_hand_computed():
    ranked = [R("z.py"), R("a.py", "f"), R("y.py"), R("b.py", "g"), R("a.py", "f")]      # relevant at ranks 2, 4, 5 (rank 5 repeats item A)
    m = retrieval_metrics(ranked, [A, B], ks=(1, 2, 4, 5))
    assert m["mrr"] == 0.5
    assert (m["recall@1"], m["recall@2"], m["recall@4"], m["recall@5"]) == (0.0, 0.5, 1.0, 1.0)
    assert m["precision@5"] == pytest.approx(3 / 5) and m["precision@2"] == pytest.approx(1 / 2)       # chunk-level: the repeat counts as relevant
    assert (m["hit@1"], m["hit@2"]) == (0.0, 1.0)
    dcg = 1 / math.log2(3) + 1 / math.log2(5)                                                          # gains at ranks 2 and 4; the repeat gains nothing
    assert m["ndcg@4"] == pytest.approx(dcg / (1 + 1 / math.log2(3))) and m["ndcg@5"] == pytest.approx(m["ndcg@4"])


def test_perfect_and_empty_rankings():
    perfect = retrieval_metrics([R("a.py", "f"), R("b.py", "g")], [A, B], ks=(2,))
    assert perfect["ndcg@2"] == pytest.approx(1.0) and perfect["mrr"] == 1.0 and perfect["recall@2"] == 1.0 and perfect["precision@2"] == 1.0
    none = retrieval_metrics([], [A], ks=(5,))
    assert set(none.values()) == {0.0}
    assert retrieval_metrics([R("a.py", "f")], [], ks=(3,))["recall@3"] == 0.0                            # no division by zero


def test_symbol_level_versus_file_level_matching():
    r = R("a.py", "other_function")
    assert not matches(r, A, "symbol") and matches(r, A, "file")
    assert retrieval_metrics([r], [A], (1,), "symbol")["recall@1"] == 0 and retrieval_metrics([r], [A], (1,), "file")["recall@1"] == 1
    assert matches(R("README.md", "README.md"), Expected("README.md"))                                  # file-only label matches any chunk of the file
    lines = Expected("cfg.py", lines=(10, 20))
    assert matches(R("cfg.py", "x", 18, 30), lines) and not matches(R("cfg.py", "x", 21, 30), lines) and not matches(R("other.py", "x", 10, 20), lines)


def test_context_precision_follows_the_ragas_definition_and_recall_counts_items():
    ctx = [R("a.py", "f"), R("noise.py"), R("b.py", "g")]
    m = context_metrics(ctx, [A, B])
    assert m["context_precision"] == pytest.approx((1 / 1 + 2 / 3) / 2) and m["context_recall"] == 1.0
    assert context_metrics([R("noise.py"), R("a.py", "f")], [A, B]) == {"context_precision": pytest.approx(0.5), "context_recall": 0.5}
    assert context_metrics([R("n.py")], [A]) == {"context_precision": 0.0, "context_recall": 0.0}
    # putting the relevant chunk first is rewarded even though recall is identical
    assert context_metrics([R("a.py", "f"), R("n.py")], [A])["context_precision"] > context_metrics([R("n.py"), R("a.py", "f")], [A])["context_precision"]


def test_relevance_gain_counts_each_expected_item_once():
    rel, gain = relevance([R("a.py", "f"), R("a.py", "f"), R("b.py", "g")], [A, B])
    assert rel == [True, True, True] and gain == [1, 0, 1]


def test_bootstrap_ci_and_paired_test():
    xs = [0.0, 1.0] * 20
    lo, hi = bootstrap_ci(xs, seed=1)
    assert lo < 0.5 < hi and bootstrap_ci(xs, seed=1) == (lo, hi) and hi - lo > 0.1                      # deterministic for a seed
    assert bootstrap_ci([0.7] * 10) == (0.7, 0.7) and bootstrap_ci([0.3]) == (0.3, 0.3) and bootstrap_ci([]) == (0.0, 0.0)
    a, b = [0.9, 0.8, 1.0, 0.7, 0.9, 1.0] * 5, [0.2, 0.1, 0.3, 0.0, 0.2, 0.1] * 5
    assert paired_bootstrap_p(a, b) < 0.01 and paired_bootstrap_p(a, a) == 1.0
    noisy = [0.4, 0.6, 0.5, 0.45, 0.55] * 4
    assert paired_bootstrap_p(noisy, list(reversed(noisy))) > 0.05                                         # no real difference -> not significant


# ---- datasets -----------------------------------------------------------------------------------------------
def test_dataset_round_trip_comments_and_legacy_format(tmp_path):
    p = tmp_path / "d.jsonl"
    p.write_text('# comment\n{"_meta": {"name": "mine", "repo": "."}}\n\n'
                 '{"id": "q1", "question": "Where?", "relevant": [{"file": "a.py", "symbol": "f"}, {"file": "c.cfg", "lines": [3, 9]}], "tags": ["x"]}\n'
                 '{"question": "No id", "relevant": [{"file": "b.py"}]}\n')
    ds = load_dataset(p)
    assert ds.name == "mine" and ds.meta == {"repo": "."} and [q.id for q in ds.questions] == ["q1", "q2"]
    assert ds.questions[0].relevant == [Expected("a.py", "f"), Expected("c.cfg", None, (3, 9))]
    out = tmp_path / "copy.jsonl"
    ds.save(out)
    again = load_dataset(out)
    assert [q.to_dict() for q in again.questions] == [q.to_dict() for q in ds.questions] and again.name == "mine"
    legacy = tmp_path / "old.json"
    legacy.write_text(json.dumps([{"question": "Where is auth?", "expected_files": ["auth.py"]}]))
    assert load_dataset(legacy).questions[0].relevant == [Expected("auth.py")]


def test_dataset_errors_point_at_the_line(tmp_path):
    p = tmp_path / "bad.jsonl"
    p.write_text('{"question": "ok", "relevant": [{"file": "a.py"}]}\n{not json}\n')
    with pytest.raises(ValueError, match=r"bad.jsonl:2: invalid JSON"):
        load_dataset(p)
    p.write_text('{"question": "no labels"}\n')
    with pytest.raises(ValueError, match=r":1: missing field 'relevant'"):
        load_dataset(p)


def test_validate_catches_stale_labels(repo):
    idx = build_index(repo, HashingEmbedder())
    ds = Dataset("x", [Question("q1", "ok", [Expected("auth.py", "authenticate_user")]),
                       Question("q1", "duplicate id", [Expected("auth.py")]),
                       Question("q3", "stale file", [Expected("gone.py")]),
                       Question("q4", "stale symbol", [Expected("auth.py", "renamed_function")]),
                       Question("q5", " ", []),
                       ])
    problems = validate(ds, idx)
    text = "\n".join(problems)
    assert "q1: duplicate id" in text and "gone.py" in text and "renamed_function" in text and "found: authenticate_user" in text
    assert "q5: empty question" in text and "q5: no relevant items" in text and len(problems) == 5


def test_shipped_datasets_match_their_repositories():
    """If this fails after a refactor, update the labels in eval/datasets/ (run `python -m app.rag.eval validate`)."""
    for repo, path in ((FIXTURE, "eval/datasets/delivery_sync.jsonl"), (ROOT, "eval/datasets/codebase_agent.jsonl")):
        ds = load_dataset(ROOT / path)
        problems = validate(ds, build_index(repo, HashingEmbedder()))
        assert not problems, f"{path} is stale:\n" + "\n".join(problems)
    assert len(load_dataset(ROOT / "eval/datasets/codebase_agent.jsonl").questions) == 50


# ---- .codeagentignore ---------------------------------------------------------------------------------------------
def test_ignore_patterns_follow_gitignore_conventions():
    pats = ["/eval/", "docs/old.md", "*.min.js", "vendor/", "generated/*"]
    assert is_ignored("eval/datasets/q.jsonl", pats) and not is_ignored("app/rag/eval/metrics.py", pats)      # anchored vs not
    assert is_ignored("docs/old.md", pats) and not is_ignored("docs/new.md", pats)
    assert is_ignored("web/app.min.js", pats) and is_ignored("a/b/vendor/x.py", pats) and is_ignored("generated/x.py", pats)
    assert not is_ignored("src/main.py", pats) and not is_ignored("evaluation.py", pats)


def test_ignored_files_are_never_indexed(tmp_path):
    (tmp_path / ".codeagentignore").write_text("# comment\n/eval/\n*.gen.py\n")
    (tmp_path / "eval").mkdir()
    (tmp_path / "eval" / "q.jsonl").write_text("{}")
    (tmp_path / "a.py").write_text("x = 1\n")
    (tmp_path / "b.gen.py").write_text("y = 1\n")
    (tmp_path / "pkg" / "eval").mkdir(parents=True)
    (tmp_path / "pkg" / "eval" / "m.py").write_text("z = 1\n")
    assert sorted(r for r, _ in iter_source_files(tmp_path) if r != ".codeagentignore") == ["a.py", "pkg/eval/m.py"]


# ---- the runner ----------------------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def ds():
    return load_dataset(ROOT / "eval/datasets/delivery_sync.jsonl")


@pytest.fixture(scope="module")
def result(ds):
    return run_experiment(FIXTURE, ds, preset_configs(["hash"], ["heuristic"]))


def strip_timing(r):
    return [{k: v for k, v in c.items() if k not in ("latency_ms", "per_question")} for c in r["configs"]]


def test_runner_produces_bounded_metrics_with_confidence_intervals(result, ds):
    assert [c["config"]["name"] for c in result["configs"]] == ["bm25-only", "hash · vector", "hash · hybrid", "hash · hybrid + heuristic"]
    assert result["store"] == "memory" and result["dataset"]["questions"] == 12 and not result["label_problems"]
    for c in result["configs"]:
        assert c["status"] == "ok" and c["n"] == 12 and len(c["per_question"]) == 12
        for lv in ("symbol", "file"):
            for metric, v in c["summary"][lv].items():
                assert 0 <= v["lo"] <= v["mean"] + 1e-9 and v["mean"] - 1e-9 <= v["hi"] <= 1
        assert c["summary"]["file"]["mrr"]["mean"] >= c["summary"]["symbol"]["mrr"]["mean"] - 1e-9        # file-level labels are never harder
    best = {c["config"]["name"]: c["summary"]["symbol"] for c in result["configs"]}
    assert best["hash · hybrid + heuristic"]["mrr"]["mean"] > best["bm25-only"]["mrr"]["mean"]           # reranking priors help on this fixture
    assert best["hash · hybrid + heuristic"]["recall@5"]["mean"] >= 0.8
    assert result["indexes"]["hash"]["chunks"] > 0 and "p < 0.05" in to_markdown(result)
    q = result["configs"][3]["per_question"][0]
    assert q["id"] == "d01" and q["retrieved"][0].startswith("services/eta.py") and q["first_relevant_rank"] == 1


def test_runs_are_deterministic(result, ds):
    again = run_experiment(FIXTURE, ds, preset_configs(["hash"], ["heuristic"]))
    assert strip_timing(again) == strip_timing(result) and again["comparisons"] == result["comparisons"]


def test_paired_comparisons_are_reported_against_the_baseline(result):
    assert result["baseline"] == "bm25-only" and "bm25-only" not in result["comparisons"]
    cmp = result["comparisons"]["hash · hybrid + heuristic"]
    assert set(cmp) == {"mrr", "ndcg@10", "recall@5"} and all(0 < v["p"] <= 1 for v in cmp.values()) and cmp["mrr"]["delta"] > 0


def test_unavailable_models_are_skipped_not_fatal(ds, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setitem(__import__("sys").modules, "sentence_transformers", None)
    cfgs = [ExpConfig("ok", "hash", "hybrid"), ExpConfig("openai", "openai:text-embedding-3-small", "hybrid"),
            ExpConfig("ce", "hash", "hybrid", reranker="bge-reranker-base")]
    r = run_experiment(FIXTURE, ds, cfgs)
    st = {c["config"]["name"]: c for c in r["configs"]}
    assert st["ok"]["status"] == "ok"
    assert st["openai"]["status"] == "skipped" and "OPENAI_API_KEY" in st["openai"]["reason"]
    assert st["ce"]["status"] == "skipped" and "sentence-transformers" in st["ce"]["reason"]
    assert "openai:text-embedding-3-small" in r["skipped_embedders"] and "skipped" in to_markdown(r)


def test_a_failing_provider_marks_only_its_own_configs(ds, monkeypatch):
    class Flaky(HashingEmbedder):
        dim, provider, model = 512, "hash", "flaky"
        name = "flaky"
        queries = 0

        def embed_query(self, text):
            raise EmbeddingError("quota exceeded")
    real = runner.get_embedder
    monkeypatch.setattr(runner, "get_embedder", lambda spec, **k: Flaky() if spec == "flaky" else real(spec, **k))
    r = run_experiment(FIXTURE, ds, [ExpConfig("good", "hash", "keyword"), ExpConfig("bad", "flaky", "vector")])
    st = {c["config"]["name"]: c for c in r["configs"]}
    assert st["good"]["status"] == "ok" and st["bad"]["status"] == "failed" and "quota exceeded" in st["bad"]["reason"]


def test_strict_mode_rejects_stale_labels(repo):
    bad = Dataset("bad", [Question("q1", "x?", [Expected("nope.py", "f")])])
    with pytest.raises(ValueError, match="do not match the repository"):
        run_experiment(repo, bad, [ExpConfig("c")], strict=True)
    assert run_experiment(repo, bad, [ExpConfig("c")])["label_problems"]


def test_reports_and_saved_files(result, tmp_path):
    md, csv = to_markdown(result), to_csv(result)
    assert "**" in md and "| hash · hybrid + heuristic" in md and md.count("\n| ") >= 5
    rows = csv.strip().splitlines()
    assert rows[0].startswith("config,embedder,mode,reranker,mrr") and len(rows) == 5 and rows[1].split(",")[2] == "keyword"
    path = save_result(result, tmp_path)
    assert json.loads(path.read_text())["id"] == result["id"] and path.with_suffix(".md").read_text() == md


def test_preset_expansion():
    names = [c.name for c in preset_configs(["hash", "openai:text-embedding-3-small:512", "bge:BAAI/bge-small-en-v1.5"], ["heuristic", "bge-reranker-base"])]
    assert names[0] == "bm25-only" and len(names) == 1 + 3 * 4
    assert "text-embedding-3-small:512 · hybrid + heuristic" in names and "bge-small-en-v1.5 · hybrid + bge-reranker-base" in names
    with pytest.raises(ValueError, match="unknown config field"):
        ExpConfig.from_dict({"name": "x", "modee": "hybrid"})


def test_embedding_cost_is_accounted(ds):
    r = run_experiment(FIXTURE, ds, [ExpConfig("c", "hash", "hybrid")])
    info = r["indexes"]["hash"]
    assert info["embed_texts"] == info["chunks"] and info["embed_calls"] >= 1
    assert r["configs"][0]["query_cost"]["embed_calls"] == 12                         # one query embedding per question


# ---- the same experiment on PostgreSQL --------------------------------------------------------------------------------
DSN = os.getenv("TEST_DATABASE_URL", "postgresql://agent:agent@localhost:5432/codeagent")


def _pg():
    try:
        import psycopg
        psycopg.connect(DSN, connect_timeout=3).close()
        return True
    except Exception:  # noqa: BLE001
        return False


@pytest.mark.skipif(not _pg(), reason="no PostgreSQL/pgvector reachable")
def test_experiment_on_pgvector_matches_memory_and_adds_models_without_reparsing(ds, monkeypatch):
    from app.rag import pg as pgmod

    class Hash64(HashingEmbedder):
        dim = 64
        name = "hash64"
    real = runner.get_embedder
    monkeypatch.setattr(runner, "get_embedder", lambda spec, **k: Hash64() if spec == "hash64" else real(spec, **k))
    schema = f"t_{uuid.uuid4().hex[:10]}"
    store = pgmod.PgStore(DSN, schema=schema)
    try:
        cfgs = [ExpConfig("hybrid", "hash", "hybrid", "heuristic"), ExpConfig("keyword", "hash", "keyword"), ExpConfig("hybrid64", "hash64", "hybrid", "heuristic")]
        mem = run_experiment(FIXTURE, ds, cfgs)
        pg = run_experiment(FIXTURE, ds, cfgs, store=store, keep=True)
        assert pg["store"] == "pgvector"
        for a, b in zip(mem["configs"], pg["configs"]):
            name = a["config"]["name"]
            if name != "hybrid64":      # 512-dim hashing: identical rankings, ties included
                assert [q["retrieved"] for q in a["per_question"]] == [q["retrieved"] for q in b["per_question"]], name
                for metric, v in a["summary"]["symbol"].items():
                    assert b["summary"]["symbol"][metric]["mean"] == pytest.approx(v["mean"], abs=1e-9)
            else:                       # 64-dim hashing yields mathematically equal similarities that numpy-float32 and pgvector round differently:
                for qa, qb in zip(a["per_question"], b["per_question"]):    # same candidates and (up to such ties) the same order
                    assert set(qa["retrieved"]) == set(qb["retrieved"]) and qa["retrieved"][:2] == qb["retrieved"][:2]
                assert b["summary"]["symbol"]["mrr"]["mean"] == pytest.approx(a["summary"]["symbol"]["mrr"]["mean"], abs=0.05)
        assert {m["model"] for m in store.models()} == {"hash", "hash64"}          # second model added to the same chunks (no re-parse)
        with store.pool.connection() as c:
            assert c.execute("SELECT count(*) FROM repositories").fetchone()[0] == 1
            c.commit()
        run_experiment(FIXTURE, ds, cfgs[:1], store=store, keep=False)
        assert store.list_repos() == []                                              # keep=False removes the benchmark repository again
    finally:
        store.close()
        import psycopg
        with psycopg.connect(DSN, autocommit=True) as c:
            c.execute(f"DROP SCHEMA {schema} CASCADE")


# ---- synthetic questions -----------------------------------------------------------------------------------------------
def test_generator_writes_questions_without_leaking_symbol_names(tmp_path):
    idx = build_index(ROOT / "tests" / "fixtures" / "delivery_sync", HashingEmbedder())
    import re

    def make_llm():
        calls = []

        class LLM(ScriptedLLM):
            def json(self, task, system, prompt, hints=None):
                name = re.search(r"Symbol: (\S+)", prompt).group(1)
                calls.append(name)
                if len(calls) == 1:
                    return {"question": f"What does {name} return?"}                  # leaks the identifier -> rejected
                if len(calls) == 2:
                    return {"question": "too short"}                                   # rejected
                return {"question": f"Explain the behaviour number {len(calls)} of this part of the delivery service"}
        return LLM({}), calls
    llm, calls = make_llm()
    out = generate_questions(idx, llm, n=10, seed=3)
    assert len(out.questions) == len(calls) - 2 >= 1 and out.meta["rejected_for_leaking_the_name"] == 2
    for q in out.questions:
        sym = q.relevant[0].symbol
        assert q.id.startswith("syn-") and "synthetic" in q.tags and sym.lower() not in q.question.lower() and len(q.question) >= 12
        assert not q.relevant[0].file.startswith("tests/")                              # tests are not worth asking about
    again = generate_questions(idx, make_llm()[0], n=10, seed=3)
    assert [q.relevant[0].symbol for q in again.questions] == [q.relevant[0].symbol for q in out.questions]       # same seed, same picks
    path = tmp_path / "syn.jsonl"
    out.save(path)
    assert not validate(load_dataset(path), idx)                                         # generated labels are valid by construction


# ---- CLI ---------------------------------------------------------------------------------------------------------------
def test_cli_validate_run_and_show(tmp_path, capsys):
    good = str(ROOT / "eval/datasets/delivery_sync.jsonl")
    assert cli.main(["validate", "--repo", str(FIXTURE), "--dataset", good]) == 0
    stale = tmp_path / "stale.jsonl"
    stale.write_text('{"id": "s1", "question": "x", "relevant": [{"file": "missing.py"}]}\n')
    capsys.readouterr()
    assert cli.main(["validate", "--repo", str(FIXTURE), "--dataset", str(stale)]) == 1
    assert "missing.py" in capsys.readouterr().out
    out = tmp_path / "exp"
    assert cli.main(["run", "--repo", str(FIXTURE), "--dataset", good, "--preset", "offline", "--out", str(out), "--ks", "1,5,10"]) == 0
    printed = capsys.readouterr().out
    assert "| hash · hybrid + heuristic" in printed and "saved:" in printed
    saved = sorted(out.glob("*.json"))
    assert len(saved) == 1 and sorted(out.glob("*.md"))
    capsys.readouterr()
    assert cli.main(["show", str(saved[0])]) == 0 and "bm25-only" in capsys.readouterr().out
    assert cli.main(["run", "--repo", str(FIXTURE), "--dataset", good, "--store", "pgvector", "--out", str(out)]) in (0, 2)
