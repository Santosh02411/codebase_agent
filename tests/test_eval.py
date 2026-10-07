import json
from pathlib import Path
from app.evaluation import evaluate_retrieval


def test_retrieval_quality_on_fixture(tools):
    ds = json.loads((Path(__file__).parent.parent / "eval" / "dataset.json").read_text())
    res = evaluate_retrieval(tools, ds, k=3)
    assert res["recall@k"] >= 0.8 and res["mrr"] >= 0.7
