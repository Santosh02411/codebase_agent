from app.review import bench


def test_the_review_benchmark_finds_every_seeded_mistake_and_stays_quiet_on_clean_code():
    res = bench.run_cases()
    missed = [r["name"] for r in res["rows"] if not r["found"]]
    assert not missed, missed
    assert res["found"] == res["cases"] >= 50
    assert res["clean_false_positives"] == 0, [c for c in res["clean_cases"] if c["false_positives"]]
    assert res["right_line"] >= res["cases"] - 3            # the reported line is the mistake's line, give or take the parser's recovery
