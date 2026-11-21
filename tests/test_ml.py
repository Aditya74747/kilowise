"""ML model selection (docs/ml_model_selection.md). Skipped if the optional `ml` group is not installed."""
import pytest

from greenledger import ledger, ml

pytestmark = pytest.mark.skipif(not ml.available(), reason="optional ml group not installed")


@pytest.fixture(scope="module")
def res():
    return ml.train(force=False)


def test_classifier_leaderboard_and_selection(res):
    c = res["classifier"]
    board = c["leaderboard"]
    assert sum(b["kind"] == "ml" for b in board) >= 4 and any(b["kind"] == "baseline" for b in board)
    chosen = next(b for b in board if b["selected"])
    best_ml = max((b for b in board if b["kind"] == "ml"), key=lambda b: b["val"]["f1"])
    best_base = max((b for b in board if b["kind"] == "baseline"), key=lambda b: b["val"]["f1"])
    # kept = the best by validation F1; an ML model only if it beats the best baseline
    assert chosen["val"]["f1"] == max(best_ml["val"]["f1"], best_base["val"]["f1"])
    assert c["kept_ml"] == (best_ml["val"]["f1"] > best_base["val"]["f1"])
    assert "test" in chosen


def test_protected_server_never_flagged(res):
    dr = [w for w in res["classifier"]["watch_list"] if w["server_id"] == "dr-failover"]
    assert dr and not dr[0]["flag"] and dr[0]["prob"] == 0.0


def test_forecaster_selected_by_mae_and_beats_naive(res):
    for b, v in res["forecaster"]["buckets"].items():
        rows = v["leaderboard"]
        assert sum(x["kind"] == "ml" for x in rows) >= 4, b
        chosen = next(x for x in rows if x["selected"])
        base = next(x for x in rows if x["kind"] == "baseline")
        assert chosen["mae"] <= base["mae"], b
        assert chosen["mae"] == min(x["mae"] for x in rows) or chosen["kind"] == "baseline", b
        assert all(y["low"] <= y["mid"] <= y["high"] for y in v["years"]), b


def test_classifier_is_deterministic():
    r = ledger.build()
    a, b = ml.train_classifier(r), ml.train_classifier(r)
    assert [x["val"]["f1"] for x in a["leaderboard"]] == [x["val"]["f1"] for x in b["leaderboard"]]
