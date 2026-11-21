"""Grid page (grid.py): European grids from Ember open data next to the company's electricity.

The Ember files are downloaded with `greenledger grid-fetch` and are git-ignored, so the data tests skip on a machine
without them; the build must still work and say how to get them.
"""
import json

import pytest

from greenledger import grid
from greenledger.config import PROCESSED


@pytest.fixture(scope="module")
def data():
    return json.loads((PROCESSED / "app_data.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def g(data):
    gr = data["grid"]
    if not gr["available"]:
        pytest.skip("Ember grid files not downloaded (uv run greenledger grid-fetch)")
    return gr


def test_build_without_files_explains_how_to_get_them(tmp_path):
    out = grid.build([], 0.95, folder=tmp_path)
    assert out["available"] is False and out["fetch"] == "uv run greenledger grid-fetch"
    assert len(out["status"]) == 3 and all(not s["present"] and "grid-fetch" in s["note"] for s in out["status"])


def test_files_with_changed_columns_are_skipped_not_fatal(tmp_path):
    (tmp_path / grid.FILES["monthly"][0]).write_text("Area,Date\nX,2026-01-01\n", encoding="utf-8")
    out = grid.build([], 0.95, folder=tmp_path)
    assert out["available"] is False and "columns missing" in out["status"][0]["note"]


def test_every_country_is_complete_and_plausible(g):
    cs = g["countries"]
    assert len(cs) >= 30 and any(c["eu"] for c in cs)
    for c in cs:
        assert 0 < c["gen_g"] < 1200 and 0 < c["cons_g"] < 1200, c["key"]
        assert 0 <= c["ren"] <= 1 and c["ren"] <= c["clean"] + 1e-9, c["key"]
        assert sum(c["mix"].values()) == pytest.approx(1, abs=0.02), c["key"]   # the mix covers all generation
        if not c["eu"]:
            assert tuple(c["tile"]) == tuple(grid.TILES[c["key"]])
    tiles = [tuple(c["tile"]) for c in cs if c["tile"]]
    assert len(tiles) == len(set(tiles)), "two countries on the same map tile"
    assert len(g["months"]) == grid.MONTHS_SHOWN and g["months"][-1] == g["as_of"]
    for k, sr in g["series"].items():
        assert all(len(v) == len(g["months"]) for v in sr["mix"].values()), k


def test_imports_only_change_the_mix_of_importers(g):
    """Consumption estimate: a net exporter keeps its generation intensity; Switzerland imports in winter, so its
    consumption mix is above its production mix (the reason the ledger uses the consumption mix)."""
    by = {c["key"]: c for c in g["countries"]}
    for c in g["countries"]:
        if c["import_share"] == 0:
            assert c["cons_g"] == pytest.approx(c["gen_g"], abs=0.2), c["key"]
    ch = by["CHE"]
    assert ch["import_share"] > 0 and ch["cons_g"] > ch["gen_g"] and ch["winter_g"] > ch["summer_g"]


def test_our_grids_are_mapped_and_ledger_factors_are_in_range(g, data):
    ours = {o["grid_key"]: o for o in g["ours"]}
    assert set(ours) == {"CH_consumption", "DE", "IE", "EU"} and not ours["EU"]["movable"]
    kwh = sum(o["kwh"]["mid"] for o in g["ours"])
    assert kwh == pytest.approx(data["baseline"]["normalised"]["kwh_mid"], rel=0.01)   # same electricity as the ledger
    for o in g["ours"]:
        # Ember's figures are a cross-check of factors.py: within a factor of two of the ledger's mid value
        assert 0.5 < o["cons_g"] / o["factor_g"]["mid"] < 2, o["grid_key"]
    assert ours["DE"]["cons_g"] > 3 * ours["CH_consumption"]["cons_g"]   # Frankfurt vs Zurich: the case's finding


def test_sources_cloud_regions_and_data_centres(g):
    assert "CC BY 4.0" in g["licence"] and all(s["ok"] for s in g["status"])
    assert all(c["cloud"] for c in g["countries"] if c["key"] in ("CHE", "DEU", "IRL", "SWE", "FRA"))
    for d in g["data_centres"]:
        assert d["source"] and d["kind"] in ("published", "derived")
        if d["share"] is not None:
            assert 0 < d["share"] < 0.5
        if d["kind"] == "derived" and d["share"] is not None:
            assert d["share_calc"]
    assert any(c["price"] for c in g["countries"] if c["key"] == "CHE")


def test_flow_attribution_cancels_transit_and_splits_net_imports():
    """Every 15 minutes the country's net import is credited to the neighbours sending at that moment."""
    from greenledger import gridflows
    payload = {"interval_minutes": 60, "series": [{"id": "germany", "name": "Germany"}, {"id": "italy", "name": "Italy"},
                                                  {"id": "france", "name": "France"}, {"id": "sum", "name": "sum"}],
               "data": [{"timestamp": "2026-01-01T03:00:00+01:00", "values": {"germany": 2.0, "italy": -2.0, "france": 0.0}},   # transit only
                        {"timestamp": "2026-01-01T04:00:00+01:00", "values": {"germany": 3.0, "france": 1.0, "italy": -2.0}}]}  # net import 2
    monthly, hourly = gridflows.aggregate(payload, "CHE")
    by = {r["neighbour"]: r for r in monthly}
    assert by["DEU"]["import_gwh"] == 5 and by["ITA"]["export_gwh"] == 4           # gross flows kept
    assert by["DEU"]["net_import_gwh"] == pytest.approx(1.5) and by["FRA"]["net_import_gwh"] == pytest.approx(0.5)
    assert by["ITA"]["net_import_gwh"] == 0 and by["ITA"]["net_export_gwh"] == 0    # transit cancels out
    assert {(h["hour"], h["net_import_gw"]) for h in hourly} == {(3, 0.0), (4, 2.0)}


def test_last_12_months_window():
    import datetime as dt
    from greenledger import gridflows
    assert gridflows.last_12_months(dt.date(2026, 11, 21)) == ("2025-11-01", "2026-10-31")
    assert gridflows.last_12_months(dt.date(2026, 1, 5)) == ("2025-01-01", "2025-12-31")


def test_committed_map_covers_every_country():
    from greenledger import gridflows
    m = gridflows.load_map()
    assert m and "public domain" in m["source"]
    assert set(grid.TILES) <= set(m["countries"]), set(grid.TILES) - set(m["countries"])
    assert {"Zurich", "Frankfurt", "Dublin"} <= set(m["cities"])
    for k in ("Zurich", "Frankfurt", "Dublin"):
        x, y = m["cities"][k]
        assert 0 < x < m["width"] and 0 < y < m["height"]


def test_flows_explain_where_the_electricity_comes_from(g):
    fl = g["flows"]
    if not fl["available"]:
        pytest.skip("cross-border flows not downloaded (uv run greenledger grid-fetch)")
    for k, s in fl["sources"].items():
        dom = sum(s["domestic"].values())
        assert dom + sum(i["twh"] for i in s["imports"]) == pytest.approx(s["total_twh"], abs=0.02), k
        assert 1 <= s["months_used"] <= 12
    ch = fl["sources"]["CHE"]
    assert {i["key"] for i in ch["imports"]} <= {"FRA", "DEU", "AUT", "ITA", "LIE"}
    for p in fl["pairs"]:   # direction and size follow from the two gross flows
        assert p["net_twh"] == pytest.approx(abs(p["ab_twh"] - p["ba_twh"]), abs=0.02)
        assert p["from"] == (p["a"] if p["ab_twh"] >= p["ba_twh"] else p["b"])
    assert len(fl["heat"]["CHE"]) == len(fl["months"]) and all(len(r) == 24 for r in fl["heat"]["CHE"])
    assert 0 <= fl["cheap_to_dear"]["yes"] <= fl["cheap_to_dear"]["n"]
    assert next(c for c in g["countries"] if c["key"] == "DEU")["cons_method"] == "flows"
