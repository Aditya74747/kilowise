"""Checks that guard the must-have rules. Run: uv run pytest -q"""
import pandas as pd
import pytest

from greenledger import export, ledger, limits, load, measures


@pytest.fixture(scope="module")
def data():
    return export.build_all()


def test_package_meets_targets_and_budget(data):
    b = data["baseline"]["normalised"]
    on = [m for m in data["measures"] if m["default_on"]]
    assert sum(m["effort_pd"] for m in on) <= 15
    assert sum(m["cost"]["mid"] for m in on) / b["cost_chf"] >= 0.25
    for scen in ("low", "mid", "high"):
        assert sum(m["co2"][f"{scen}_consumption"] for m in on) / b[f"co2_{scen}_consumption"] >= 0.40, scen
    # keep at least one point of margin with pessimistic factors: the jury recalculates on its own reference
    assert sum(m["co2"]["high_consumption"] for m in on) / b["co2_high_consumption"] >= 0.41


def test_injections_detected_and_ignored(data):
    ids = {i["where"] for i in data["injections"]}
    assert "ticket_id=T-1230" in ids and "ticket_id=T-1251" in ids
    assert len(data["injections"]) == 4
    # T-1251 asks to set db-fin costs to 0: costs must stay as invoiced
    db = [r for r in data["by_resource"] if r["resource_id"] == "db-fin"]
    assert db and db[0]["cost_chf"] > 10000


def test_cleaning_rules():
    log = load.DQLog()
    aw = load.aws(load.exchange_rates(), log)
    assert not aw.resource_id.eq("sandbox").any()          # test account excluded
    sub = load.ai_subscriptions(load.exchange_rates(), log)
    assert set(sub.contract_status) == {"Final"}            # drafts dropped
    az = load.azure(load.exchange_rates(), log)
    assert az.cost_chf.notna().all()                         # missing costs filled


def test_dr_failover_never_removed():
    r = ledger.build()
    m5 = measures.m5_test_scale_back(r)
    assert "dr-failover" in m5.change and "W5" in m5.windows


def test_prod_schedule_respects_month_end_and_january():
    cal = load.calendar()
    lwd = limits.last_working_days(cal)
    assert all(d.weekday() < 5 for d in lwd)
    win = {w["id"] for w in limits.windows(ledger.build())}
    assert {"W1", "W2", "W3", "W4", "W5"} <= win


def test_example_answers(data):
    q1 = data["answers"][0]
    assert sum(r["idle"] for r in q1["table"]) == 67


def test_rule_engine_package_passes_and_x1_blocked(data):
    res = {c["measure"]: c for c in data["rule_checks"]}
    for mid in ("M1", "M2", "M4", "M5", "M6"):
        assert res[mid]["conflicts"] == 0, mid           # no protected job run falls into a sleep window
    assert res["M1"]["checks"] and sum(c["checked"] for c in res["M1"]["checks"]) > 2000
    assert res["X1"]["status"] == "blocked" and res["X1"]["conflicts"] > 1000   # the rejected idea is refused


def test_targets_hold_with_swiss_production_mix(data):
    b = data["baseline"]["normalised"]
    on = [m for m in data["measures"] if m["default_on"]]
    for scen in ("low", "mid", "high"):
        assert sum(m["co2"][f"{scen}_production"] for m in on) / b[f"co2_{scen}_production"] >= 0.40, scen


def test_market_based_view_and_templates():
    from greenledger.config import OUTPUTS, RAW
    b = pd.read_csv(OUTPUTS / "template_baseline_and_assumptions.csv", encoding="utf-8-sig").set_index("parameter")
    assert float(b.loc["total_co2_market_based_baseline_year_kg", "value_mid"]) > 0
    assert float(b.loc["growth_per_year", "value_mid"]) > 0
    for key in ("total_cost_baseline_year_chf", "pue", "allocation_rule_shared_costs", "energy_per_gpu_hour"):
        assert str(b.loc[key, "value_mid"]) not in ("", "nan"), key
    m = pd.read_csv(OUTPUTS / "template_measures_package.csv", encoding="utf-8-sig")
    assert m.savings_co2_kg_market_based.notna().all()
    case = RAW.parent.parent.parent / "sprintd-basel-green-ai-data-main"
    for t in ("template_baseline_and_assumptions.csv", "template_measures_package.csv"):
        if (case / t).exists():   # column names must match the official templates exactly
            assert list(pd.read_csv(case / t, encoding="utf-8-sig").columns) == \
                   list(pd.read_csv(OUTPUTS / t, encoding="utf-8-sig").columns), t


def test_forecast_with_package_below_without(data):
    s = data["forecast"]["series"]
    for k in ("cost", "co2"):
        for sc in ("low", "mid", "high"):
            assert all(w < wo for w, wo in zip(s[k][f"with_{sc}"], s[k][f"without_{sc}"])), (k, sc)
    g = data["forecast"]["growth_per_year"]
    assert g["low"] <= g["mid"] <= g["high"]


def test_clusters_cover_all_servers_and_explain_dr(data):
    c = data["clusters"]
    assert sum(x["n"] for x in c["clusters"]) == len(c["points"]) >= 50
    dr = next(p for p in c["points"] if p["id"] == "dr-failover")
    assert "T-1094" in dr["note"]                        # idle by design, never called waste
    assert all(o["why"] for o in c["outliers"])


def test_all_bonus_files_used(data):
    files = data["bonus_files"]
    assert len(files) == 15 and all(f["present"] and f["used_for"] for f in files)
    assert all(not m["default_on"] for m in data["measures"] if m["id"] in ("B3", "B4", "B5"))
    assert next(m for m in data["measures"] if m["id"] == "M12")["default_on"]   # log retention is in the package


def test_monthly_normalised_matches_the_baseline(data):
    """The Overview's period control reads monthly_normalised: over the baseline year it must equal the normalised
    baseline, and the actual series must differ only by the one-off events (T-1212, T-1189)."""
    norm, act, base = data["monthly_normalised"], data["monthly"], data["baseline"]
    in_year = lambda rows, k: sum(r[k] for r in rows if "2025-09" <= str(r["month"])[:7] <= "2026-08")
    for k in ("cost_chf", "kwh_mid", "co2_mid_consumption"):
        assert in_year(norm, k) == pytest.approx(base["normalised"][k], abs=1)   # app data rounds the baseline
    one_offs = -sum(a["cost_chf"] for a in base["adjustments"])
    assert in_year(act, "cost_chf") - in_year(norm, "cost_chf") == pytest.approx(one_offs, abs=1)


def test_model_catalogue_is_sourced_and_explains_the_invoice(data):
    """Models page: every model has a price source or says so, sizes and training figures carry their provenance,
    derived training emissions show their calculation, and the official prices reproduce the AI invoice."""
    md = data["ai_models"]
    assert len(md["models"]) >= 15 and len({m["id"] for m in md["models"]}) == len(md["models"])
    for m in md["models"]:
        assert m["size_kind"] in ("published", "estimate") and m["size_source"]
        a = m["active_b"]
        assert 0 < a["low"] <= a["mid"] <= a["high"]
        if m["size_kind"] == "published":
            assert a["low"] == a["high"]
        assert m["price_in"] is None or m["price_source"]
        t = m["training"]
        assert t["kind"] in ("published", "derived", "not disclosed")
        if t["kind"] == "derived":
            assert t["calc"] and t["source"]
    assert {m["open"] for m in md["models"]} == {True, False}
    used = [c for c in md["price_check"]]
    assert {c["name"] for c in used} >= {"GPT-5.4", "Claude Sonnet 4.6"}
    for c in used:   # official list prices x tokens = what the company paid, within 5 %
        assert c["ratio"] == pytest.approx(1.0, abs=0.05), c
    e = md["energy"]["per_b_active"]
    assert e["low"] < e["mid"] < e["high"]


def test_training_runs_carry_location_and_provenance(data):
    """Models page, training section: every run names where it was trained and its sources; every CO2 or cost value
    says whether it is published, an outside estimate or calculated here, and ranges are ordered."""
    runs = data["ai_models"]["training_runs"]
    assert len(runs) >= 10 and any(r["maker"] == "OpenAI" for r in runs) and any(r["open"] for r in runs)
    for r in runs:
        assert r["site"] and r["country"] and r["sources"]
        for v in (r["co2"], r["cost"]):
            if v:
                assert v["kind"] in ("published", "estimate", "derived") and v["label"] and v["low"] <= v["high"]
