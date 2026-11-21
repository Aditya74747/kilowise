"""Grid page: Europe's electricity grids from open data, next to the company's own electricity use.

Inputs (data/raw/external/grid/, refreshed with `greenledger grid-fetch`; Ember updates twice a month):
  release_generation_monthly_lower.csv              Ember monthly electricity data, Europe: generation by source,
                                                    emissions, demand, net imports per country and month
  release_generation_yearly_lower.csv               Ember yearly electricity data, Europe (long history)
  european_wholesale_electricity_price_data_monthly.csv  Ember day-ahead wholesale prices per country and month
All three: Ember, CC BY 4.0. Newer downloads with the same columns are picked up by the next build; files that are
missing or have changed columns are reported on the page and skipped, the rest of the build is unaffected.

What is derived here (always labelled in the app):
  - generation intensity  = Ember emissions / generation (life-cycle factors per fuel, as published by Ember)
  - consumption intensity = (domestic emissions + net imports x the neighbours' average intensity that month) /
                            (generation + net imports). An estimate: real flows depend on the hour and the border.
  - wholesale cost of the company's kWh = kWh x the 12-month average day-ahead price. Cloud and hosting prices do not
    follow the wholesale price one to one; this shows how small electricity is next to the IT bill.

The ledger keeps the factors in factors.py; this page is for comparing and choosing, never for the baseline.
"""
from __future__ import annotations

import math
import shutil
import urllib.request
from pathlib import Path

import pandas as pd

from . import factors as F
from . import gridflows
from .config import EXTERNAL

GRID_DIR = EXTERNAL / "grid"
EMBER = "https://files.ember-energy.org/public-downloads"
FILES = {
    "monthly": ("release_generation_monthly_lower.csv", f"{EMBER}/generation/outputs/release_generation_monthly_lower.csv",
                "Ember monthly electricity data, Europe (ember-energy.org/data/monthly-electricity-data)"),
    "yearly": ("release_generation_yearly_lower.csv", f"{EMBER}/generation/outputs/release_generation_yearly_lower.csv",
               "Ember yearly electricity data, Europe (ember-energy.org/data/yearly-electricity-data)"),
    "prices": ("european_wholesale_electricity_price_data_monthly.csv",
               f"{EMBER}/price/outputs/european_wholesale_electricity_price_data_monthly.csv",
               "Ember European wholesale electricity prices, monthly (ember-energy.org/data/european-wholesale-electricity-price-data)"),
}
LICENCE = "Ember, CC BY 4.0 (ember-energy.org). Day-ahead prices from ENTSO-E, EMR and SEMOpx via Ember."
REQUIRED = {
    "monthly": ["Area", "ISO 3 code", "Date", "Area type", "Electricity source", "Generation (TWh)", "Emissions (MtCO2e)"],
    "yearly": ["Area", "ISO 3 code", "Year", "Area type", "Electricity source", "Generation (TWh)", "Emissions (MtCO2e)"],
    "prices": ["Country", "ISO3 Code", "Date", "Price (EUR/MWhe)"],
}
EU = "EU"   # Ember's EU-27 aggregate has no ISO code; it is keyed by its area name
MIX = ["Coal", "Gas", "Other fossil", "Nuclear", "Hydro", "Wind", "Solar", "Bioenergy", "Other renewables"]
RENEWABLE = {"Hydro", "Wind", "Solar", "Bioenergy", "Other renewables"}
MONTHS_SHOWN = 36

# Neighbours with a power link, for the import mix of the consumption estimate (ENTSO-E interconnections).
NEIGHBOURS = {
    "AUT": ["DEU", "CZE", "HUN", "SVN", "ITA", "CHE"], "BEL": ["FRA", "NLD", "DEU", "LUX", "GBR"],
    "BGR": ["ROU", "SRB", "MKD", "GRC", "TUR"], "BIH": ["HRV", "SRB", "MNE"], "CHE": ["DEU", "FRA", "ITA", "AUT"],
    "CYP": [], "CZE": ["DEU", "POL", "SVK", "AUT"], "DEU": ["DNK", "POL", "CZE", "AUT", "CHE", "FRA", "LUX", "BEL", "NLD", "SWE", "NOR"],
    "DNK": ["DEU", "SWE", "NOR", "NLD", "GBR"], "ESP": ["FRA", "PRT"], "EST": ["FIN", "LVA"],
    "FIN": ["SWE", "EST", "NOR"], "FRA": ["BEL", "DEU", "CHE", "ITA", "ESP", "GBR"], "GBR": ["IRL", "FRA", "BEL", "NLD", "NOR", "DNK"],
    "GRC": ["BGR", "MKD", "ITA", "TUR"], "HRV": ["SVN", "HUN", "SRB", "BIH"], "HUN": ["AUT", "SVK", "UKR", "ROU", "SRB", "HRV", "SVN"],
    "IRL": ["GBR"], "ITA": ["FRA", "CHE", "AUT", "SVN", "GRC", "MNE"], "LTU": ["LVA", "POL", "SWE"],
    "LUX": ["DEU", "BEL", "FRA"], "LVA": ["EST", "LTU"], "MKD": ["SRB", "BGR", "GRC", "XKX"], "MLT": ["ITA"],
    "MNE": ["SRB", "BIH", "ITA", "XKX"], "NLD": ["DEU", "BEL", "GBR", "NOR", "DNK"], "NOR": ["SWE", "FIN", "DNK", "DEU", "NLD", "GBR"],
    "POL": ["DEU", "CZE", "SVK", "LTU", "SWE", "UKR"], "PRT": ["ESP"], "ROU": ["HUN", "SRB", "BGR", "UKR"],
    "SRB": ["HUN", "ROU", "BGR", "MKD", "XKX", "MNE", "BIH", "HRV"], "SVK": ["CZE", "POL", "HUN", "UKR", "AUT"],
    "SVN": ["AUT", "ITA", "HRV", "HUN"], "SWE": ["NOR", "FIN", "DNK", "DEU", "POL", "LTU"], "TUR": ["BGR", "GRC"],
    "UKR": ["POL", "SVK", "HUN", "ROU"], "XKX": ["SRB", "MKD", "MNE"],
}

# Tile map of Europe (column, row): one square per country, roughly where it lies.
TILES = {
    "NOR": (5, 0), "SWE": (6, 0), "FIN": (7, 0),
    "IRL": (1, 1), "GBR": (2, 1), "DNK": (5, 1), "EST": (7, 1),
    "NLD": (4, 2), "DEU": (5, 2), "POL": (6, 2), "LVA": (7, 2),
    "BEL": (3, 3), "LUX": (4, 3), "CZE": (5, 3), "SVK": (6, 3), "LTU": (7, 3), "UKR": (8, 3),
    "FRA": (3, 4), "CHE": (4, 4), "AUT": (5, 4), "HUN": (6, 4), "ROU": (7, 4),
    "PRT": (1, 5), "ESP": (2, 5), "ITA": (4, 5), "SVN": (5, 5), "HRV": (6, 5), "SRB": (7, 5), "BGR": (8, 5),
    "BIH": (6, 6), "MNE": (7, 6), "MKD": (8, 6), "TUR": (9, 6), "XKX": (7, 7), "GRC": (8, 7), "CYP": (9, 7), "MLT": (4, 7),
}

# The company's grids (factors.GRID keys from the ledger) and the Ember area that describes them.
OUR_GRIDS = {"CH_consumption": ("CHE", "Zurich"), "DE": ("DEU", "Frankfurt"), "IE": ("IRL", "Dublin"),
             "EU": (EU, "AI services and SaaS (EU mixed)")}

# Public cloud regions in Europe of the three large providers (where a workload can realistically move).
# From the providers' region pages; check before a move (regions open often): azure.microsoft.com/explore/
# global-infrastructure/geographies, aws.amazon.com/about-aws/global-infrastructure/regions_az, cloud.google.com/about/locations
CLOUD_REGIONS = {
    "CHE": ["Azure Switzerland North (Zurich)", "Azure Switzerland West (Geneva)", "AWS eu-central-2 (Zurich)", "Google europe-west6 (Zurich)"],
    "DEU": ["Azure Germany West Central (Frankfurt)", "AWS eu-central-1 (Frankfurt)", "Google europe-west3 (Frankfurt)", "Google europe-west10 (Berlin)"],
    "IRL": ["Azure North Europe (Dublin)", "AWS eu-west-1 (Dublin)"],
    "NLD": ["Azure West Europe (Amsterdam)", "Google europe-west4 (Eemshaven)"],
    "BEL": ["Google europe-west1 (St. Ghislain)"],
    "GBR": ["Azure UK South (London)", "AWS eu-west-2 (London)", "Google europe-west2 (London)"],
    "FRA": ["Azure France Central (Paris)", "AWS eu-west-3 (Paris)", "Google europe-west9 (Paris)"],
    "SWE": ["Azure Sweden Central (Gävle)", "AWS eu-north-1 (Stockholm)", "Google europe-north2 (Stockholm)"],
    "NOR": ["Azure Norway East (Oslo)"],
    "FIN": ["Google europe-north1 (Hamina)"],
    "POL": ["Azure Poland Central (Warsaw)", "Google europe-central2 (Warsaw)"],
    "ITA": ["Azure Italy North (Milan)", "AWS eu-south-1 (Milan)", "Google europe-west8 (Milan)"],
    "ESP": ["Azure Spain Central (Madrid)", "AWS eu-south-2 (Aragón)", "Google europe-southwest1 (Madrid)"],
}
CLOUD_SOURCE = ("Provider region pages: azure.microsoft.com/explore/global-infrastructure/geographies, "
                "aws.amazon.com/about-aws/global-infrastructure/regions_az, cloud.google.com/about/locations (list as of 2026; "
                "check before a move)")

# Electricity used by data centres, per country, from national statistics and studies. kind: published = stated by the
# source; derived = TWh from the source, share computed here with Ember's demand of that year. Add rows as new
# statistics appear.
DATA_CENTRES = [
    {"iso3": "IRL", "year": 2023, "twh": 6.335, "share": None, "kind": "published",
     "source": "CSO Ireland, Data Centres Metered Electricity Consumption 2024 (cso.ie/en/releasesandpublications/ep/p-dcmec)"},
    {"iso3": "IRL", "year": 2024, "twh": 6.973, "share": 0.22, "kind": "published",
     "source": "CSO Ireland, Data Centres Metered Electricity Consumption 2024 and 2025 (2024 revised to 6,973 GWh)"},
    {"iso3": "IRL", "year": 2025, "twh": 7.663, "share": 0.23, "kind": "published",
     "source": "CSO Ireland, Data Centres Metered Electricity Consumption 2025 (July 2026): 23 % of metered electricity"},
    {"iso3": "NLD", "year": 2024, "twh": 5.1, "share": 0.046, "kind": "published",
     "source": "CBS Netherlands, 'Data centres consume 4.6 percent of the Netherlands' electricity' (cbs.nl, 2025)"},
    {"iso3": "NLD", "year": 2025, "twh": None, "share": 0.05, "kind": "published",
     "source": "CBS Netherlands, 'Data centres consume 5 percent of the Netherlands' electricity' (cbs.nl, 2026, provisional)"},
    {"iso3": "DEU", "year": 2024, "twh": 20.0, "share": None, "kind": "derived",
     "source": "Bitkom / Borderstep Institute: about 20 TWh in 2024 (bitkom.org, Rechenzentren in Deutschland)"},
    {"iso3": "DEU", "year": 2025, "twh": 21.3, "share": None, "kind": "derived",
     "source": "Bitkom Studienbericht Rechenzentren 2025: 21.3 TWh (bitkom.org, 2025-11)"},
    {"iso3": "CHE", "year": 2019, "twh": 1.77, "share": 0.031, "kind": "published",
     "source": "Swiss Federal Office of Energy (BFE / EnergieSchweiz) data centre study, May 2026 (pubdb.bfe.admin.ch)"},
    {"iso3": "CHE", "year": 2024, "twh": 2.1, "share": 0.036, "kind": "published",
     "source": "Swiss Federal Office of Energy (BFE / EnergieSchweiz) data centre study, May 2026: just under 2.1 TWh, about 3.6 %"},
]
DATA_CENTRE_OUTLOOK = [
    {"iso3": "CHE", "year": 2030, "text": "2.5–3.2 TWh, 4.3–5.6 % of Swiss consumption (high case 3.5 TWh)",
     "source": "BFE / EnergieSchweiz data centre study, May 2026"},
    {"iso3": "DEU", "year": 2030, "text": "25–35 TWh a year", "source": "Bitkom and Borderstep studies, cited by the German government (Bundestag hib 855/2024)"},
]
EUROPE_DC_SHARE = {"years": [2020, 2023, 2024, 2025], "share": [0.01444, 0.01752, 0.01769, 0.01870],
                   "source": "IEA, Energy and AI (2025, 2026), processed by Our World in Data with Ember demand "
                             "(ourworldindata.org/grapher/data-centers-share-electricity-demand), region 'Europe (IEA)'"}


def fetch(dest: Path = GRID_DIR, timeout: int = 300) -> list[str]:
    """Download the newest Ember files. Writes to a temporary name first, so a failed download keeps the old file."""
    dest.mkdir(parents=True, exist_ok=True)
    out = []
    for key, (name, url, _) in FILES.items():
        tmp = dest / (name + ".part")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "kilowise-grid-fetch"})
            with urllib.request.urlopen(req, timeout=timeout) as r, open(tmp, "wb") as f:
                shutil.copyfileobj(r, f)
            head = tmp.read_text(encoding="utf-8-sig", errors="replace").split("\n", 1)[0]
            missing = [c for c in REQUIRED[key] if c not in head]
            if missing:
                tmp.unlink()
                out.append(f"{name}: kept the old file, the download lacks the columns {missing}")
                continue
            tmp.replace(dest / name)
            out.append(f"{name}: {(dest / name).stat().st_size / 1e6:.1f} MB")
        except OSError as e:   # no internet, proxy, server down: the build keeps working with what is there
            if tmp.exists():
                tmp.unlink()
            out.append(f"{name}: not downloaded ({e})")
    from . import gridflows   # cross-border flows (Energy-Charts) and the map (Natural Earth)
    out += gridflows.fetch_flows(dest)
    out.append(gridflows.fetch_map(dest))
    return out


def _read(key: str, folder: Path) -> tuple[pd.DataFrame | None, dict]:
    name, url, title = FILES[key]
    p = folder / name
    st = {"key": key, "file": name, "title": title, "url": url, "present": p.exists(), "ok": False, "note": ""}
    if not p.exists():
        st["note"] = "missing: run `uv run greenledger grid-fetch`"
        return None, st
    df = pd.read_csv(p, encoding="utf-8-sig", keep_default_na=False, na_values=[""], low_memory=False)
    missing = [c for c in REQUIRED[key] if c not in df.columns]
    if missing:
        st["note"] = f"skipped: columns missing {missing}"
        return None, st
    st.update(ok=True, rows=len(df))
    return df, st


def _r(v, n=1):
    return None if v is None or (isinstance(v, float) and not math.isfinite(v)) else round(float(v), n)


def _monthly(m: pd.DataFrame, flows: pd.DataFrame | None = None) -> pd.DataFrame:
    """One row per area and month: generation, emissions, demand, net imports and the mix, wide. CO2 of consumption:
    from the 15-minute cross-border flows where they exist (each neighbour's net delivery at its own intensity),
    else imports at the neighbours' average intensity."""
    m = m[m["Area type"].isin(["Country or economy", "Region"])].copy()
    m["key"] = m["ISO 3 code"].where(m["ISO 3 code"].notna() & (m["ISO 3 code"] != ""), m["Area"])
    m = m[m.key.isin(list(TILES) + [EU])]
    m["month"] = m["Date"].astype(str).str[:7]
    g = m.pivot_table(index=["key", "month"], columns="Electricity source", values="Generation (TWh)", aggfunc="sum")
    e = m[m["Electricity source"] == "Total generation"].set_index(["key", "month"])["Emissions (MtCO2e)"]
    w = pd.DataFrame(index=g.index)
    w["gen"] = g.get("Total generation")
    w["emis"] = e
    w["demand"] = g.get("Demand")
    w["imports"] = g.get("Net imports", 0.0)
    for s in MIX:
        w[s] = g[s] if s in g.columns else float("nan")
    parts = [g[c] for c in ("Lignite", "Hard coal") if c in g.columns]   # where no "Coal" total is given
    if parts:
        w["Coal"] = w["Coal"].fillna(sum(p.fillna(0) for p in parts))
    w = w.fillna({s: 0.0 for s in MIX + ["imports"]}).reset_index()
    w = w[w.gen > 0]
    w["gen_g"] = w.emis / w.gen * 1000
    # consumption estimate: imports at the neighbours' average generation intensity of the same month
    gi = w.set_index(["key", "month"]).gen_g
    eu = w[w.key == EU].set_index("month").gen_g

    def imp_g(row):
        vals = [gi.get((n, row.month)) for n in NEIGHBOURS.get(row.key, [])]
        vals = [v for v in vals if v is not None and math.isfinite(v)]
        return sum(vals) / len(vals) if vals else eu.get(row.month, row.gen_g)
    w["imp_g"] = w.apply(imp_g, axis=1)
    ni = w.imports.clip(lower=0)
    w["num"] = w.emis + ni * w.imp_g / 1000                 # Mt CO2 of what the country uses
    w["den"] = w.gen + ni                                    # TWh it uses
    w["net_in"] = ni
    w["src"] = "neighbours"
    if flows is not None and len(flows):
        f = flows.assign(twh_in=flows.net_import_gwh / 1000, twh_out=flows.net_export_gwh / 1000)
        f["g_nb"] = [gi.get((n, mo), eu.get(mo)) for n, mo in zip(f.neighbour, f.month)]
        f["co2_in"] = f.twh_in * f.g_nb.astype(float) / 1000
        agg = f.groupby(["country", "month"])[["twh_in", "twh_out", "co2_in"]].sum()
        a = agg.reindex(pd.MultiIndex.from_frame(w[["key", "month"]]))
        has = a.twh_in.notna().to_numpy()
        X, NI, CI = a.twh_out.to_numpy(), a.twh_in.to_numpy(), a.co2_in.to_numpy()
        dom = (w.gen - X).clip(lower=0)                     # net exports leave at the domestic average
        w.loc[has, "num"] = (w.emis * dom / w.gen + CI)[has]
        w.loc[has, "den"] = (dom + NI)[has]
        w.loc[has, "net_in"] = NI[has]
        w.loc[has, "src"] = "flows"
    w["cons_g"] = w.num / w.den * 1000
    w["ren"] = w[list(RENEWABLE)].sum(axis=1) / w.gen
    return w


def _prices(p: pd.DataFrame | None) -> pd.DataFrame:
    if p is None:
        return pd.DataFrame(columns=["key", "month", "price"])
    out = pd.DataFrame({"key": p["ISO3 Code"], "month": p["Date"].astype(str).str[:7],
                        "price": pd.to_numeric(p["Price (EUR/MWhe)"], errors="coerce")})
    return out.dropna()


def _yearly(y: pd.DataFrame | None) -> dict:
    if y is None:
        return {}
    y = y[y["Area type"].isin(["Country or economy", "Region"])].copy()
    y["key"] = y["ISO 3 code"].where(y["ISO 3 code"].notna() & (y["ISO 3 code"] != ""), y["Area"])
    tot = y[y["Electricity source"] == "Total generation"].set_index(["key", "Year"])
    ren = y[y["Electricity source"] == "Renewables"].set_index(["key", "Year"])["Generation (TWh)"]
    dem = y[y["Electricity source"] == "Demand"].set_index(["key", "Year"])["Generation (TWh)"]
    out = {}
    for k in set(tot.index.get_level_values(0)) & (set(TILES) | {EU}):
        t = tot.loc[k].sort_index()
        t = t[t["Generation (TWh)"] > 0]
        yrs = [int(v) for v in t.index if v >= 2000]
        out[k] = {"years": yrs,
                  "gen_g": [_r(t.loc[v, "Emissions (MtCO2e)"] / t.loc[v, "Generation (TWh)"] * 1000) for v in yrs],
                  "ren": [_r(ren.get((k, v), float("nan")) / t.loc[v, "Generation (TWh)"], 3) for v in yrs],
                  "demand": [_r(dem.get((k, v), float("nan")), 2) for v in yrs]}
    return out


def _flows(folder: Path) -> tuple[pd.DataFrame | None, pd.DataFrame | None]:
    fm, fh = folder / gridflows.FLOWS_MONTHLY, folder / gridflows.FLOWS_HOURLY
    flows = pd.read_csv(fm, encoding="utf-8") if fm.exists() else None
    hourly = pd.read_csv(fh, encoding="utf-8") if fh.exists() else None
    return flows, hourly


def _flow_outputs(flows, hourly, w, by_key, names) -> dict:
    """Map arrows, where each country's electricity comes from, net imports by hour, and how flows follow prices."""
    if flows is None or not len(flows):
        return {"available": False}
    months = sorted(flows.month.unique())
    nb_names = flows.drop_duplicates("neighbour").set_index("neighbour").neighbour_name.to_dict()
    name = lambda k: names.get(k) or nb_names.get(k, k)
    # border pairs over the flow window: gross both ways (either side's data; they agree), net direction
    pairs = {}
    for (c, n), g in flows.groupby(["country", "neighbour"]):
        key = tuple(sorted((c, n)))
        if key in pairs:
            continue
        ab = g.export_gwh.sum() if c == key[0] else g.import_gwh.sum()     # key[0] -> key[1]
        ba = g.import_gwh.sum() if c == key[0] else g.export_gwh.sum()
        pairs[key] = {"a": key[0], "b": key[1], "ab_twh": round(ab / 1000, 2), "ba_twh": round(ba / 1000, 2)}
    plist = []
    for q in pairs.values():
        net = q["ab_twh"] - q["ba_twh"]
        frm, to = (q["a"], q["b"]) if net >= 0 else (q["b"], q["a"])
        plist.append({**q, "from": frm, "to": to, "net_twh": round(abs(net), 2), "gross_twh": round(q["ab_twh"] + q["ba_twh"], 2)})
    plist.sort(key=lambda x: -x["net_twh"])
    # does electricity flow from the cheaper to the dearer side? (12-month average day-ahead prices)
    priced = [q for q in plist if q["net_twh"] >= 0.5 and (by_key.get(q["from"]) or {}).get("price") and (by_key.get(q["to"]) or {}).get("price")]
    cheap_to_dear = sum(by_key[q["from"]]["price"] <= by_key[q["to"]]["price"] for q in priced)
    # per country: where the electricity it uses comes from (domestic generation kept at home + net imports by neighbour)
    gi = w.set_index(["key", "month"])
    eu_g = w[w.key == EU].set_index("month").gen_g
    sources = {}
    for c, g in flows[flows.month.isin(months)].groupby("country"):
        dom = {s: 0.0 for s in MIX}
        dom_co2 = 0.0
        imp = {}
        for mo, gm in g.groupby("month"):
            if (c, mo) not in gi.index:
                continue
            row = gi.loc[(c, mo)]
            keep = max(row.gen - gm.net_export_gwh.sum() / 1000, 0) / row.gen
            for s in MIX:
                dom[s] += row[s] * keep
            dom_co2 += row.emis * keep
            for n, v in zip(gm.neighbour, gm.net_import_gwh):
                if v <= 0:
                    continue
                gnb = gi.gen_g.get((n, mo))
                x = imp.setdefault(n, {"key": n, "name": name(n), "twh": 0.0, "co2": 0.0, "measured": gnb is not None})
                x["twh"] += v / 1000
                x["co2"] += v / 1000 * (gnb if gnb is not None else eu_g.get(mo, 0)) / 1000
        total = sum(dom.values()) + sum(x["twh"] for x in imp.values())
        if total <= 0:
            continue
        dsum = sum(dom.values())
        sources[c] = {"total_twh": round(total, 2), "months_used": int(sum((c, mo) in gi.index for mo in g.month.unique())), "domestic": {s: round(v, 3) for s, v in dom.items()},
                      "domestic_g": round(dom_co2 / dsum * 1000, 1) if dsum else None,
                      "imports": sorted([{**x, "twh": round(x["twh"], 3), "g": round(x["co2"] / x["twh"] * 1000, 1) if x["twh"] else None,
                                          "co2": round(x["co2"], 4)} for x in imp.values()], key=lambda x: -x["twh"]),
                      "gross_in_twh": round(g.import_gwh.sum() / 1000, 2), "gross_out_twh": round(g.export_gwh.sum() / 1000, 2),
                      "net_in_twh": round(g.net_import_gwh.sum() / 1000, 2), "net_out_twh": round(g.net_export_gwh.sum() / 1000, 2)}
    heat = {}
    if hourly is not None:
        for c, g in hourly.groupby("country"):
            pv = g.pivot_table(index="month", columns="hour", values="net_import_gw").reindex(index=months, columns=range(24))
            heat[c] = [[_r(v, 2) for v in row] for row in pv.to_numpy()]
    balance = sorted(({"key": c, "name": name(c), "net_twh": round((g.import_gwh.sum() - g.export_gwh.sum()) / 1000, 2)}
                      for c, g in flows.groupby("country")), key=lambda x: x["net_twh"])
    return {"available": True, "source": gridflows.FLOW_SOURCE, "months": months, "pairs": plist, "sources": sources,
            "heat": heat, "balance": balance, "cheap_to_dear": {"n": len(priced), "yes": int(cheap_to_dear)},
            "total_gross_twh": round(sum(q["gross_twh"] for q in plist), 1)}


def build(by_region: list[dict], eur_chf: float, folder: Path = GRID_DIR) -> dict:
    """Everything the Grid page shows. Works without the files: then it says how to get them."""
    mon, st_m = _read("monthly", folder)
    yr, st_y = _read("yearly", folder)
    pr, st_p = _read("prices", folder)
    status = [st_m, st_y, st_p]
    base = {"available": False, "status": status, "licence": LICENCE, "tiles": TILES, "fetch": "uv run greenledger grid-fetch"}
    if mon is None:
        return base
    flows, hourly = _flows(folder)
    status.append({"key": "flows", "file": gridflows.FLOWS_MONTHLY, "title": gridflows.FLOW_SOURCE, "url": gridflows.API,
                   "present": flows is not None, "ok": flows is not None, "rows": 0 if flows is None else len(flows),
                   "note": "" if flows is not None else "optional: run `uv run greenledger grid-fetch` for cross-border flows"})
    w = _monthly(mon, flows)
    prices = _prices(pr)
    yearly = _yearly(yr)
    names = mon.assign(key=mon["ISO 3 code"].where(mon["ISO 3 code"].notna() & (mon["ISO 3 code"] != ""), mon["Area"])) \
               .drop_duplicates("key").set_index("key")["Area"].to_dict()
    last = w.groupby("key").month.max()
    as_of = last.mode().iloc[0]                          # the month most countries have reached
    months = sorted(m for m in w.month.unique() if m <= as_of)[-MONTHS_SHOWN:]
    pmax = prices.month.max() if len(prices) else None

    countries, series = [], {}
    for k in sorted(set(w.key)):
        c = w[(w.key == k) & (w.month <= as_of)].sort_values("month")
        win = c.tail(12)
        if len(win) < 12:
            continue
        G, E = win.gen.sum(), win.emis.sum()
        pk = prices[(prices.key == k) & (prices.month.isin(win.month))].price
        mix = {s: _r(win[s].sum() / G, 4) for s in MIX}
        cs = c.set_index("month").reindex(months)
        pm = prices[prices.key == k].set_index("month").price.reindex(months) if k != EU else pd.Series(index=months, dtype=float)
        series[k] = {"gen_g": [_r(v) for v in cs.gen_g], "cons_g": [_r(v) for v in cs.cons_g], "ren": [_r(v, 3) for v in cs.ren],
                     "demand": [_r(v, 3) for v in cs.demand], "imports": [_r(v, 3) for v in cs.imports],
                     "price": [_r(v) for v in pm], "mix": {s: [_r(v, 3) for v in cs[s]] for s in MIX}}
        winter = c[c.month.str[5:].isin(["11", "12", "01", "02"])].tail(4)
        summer = c[c.month.str[5:].isin(["05", "06", "07", "08"])].tail(4)
        y = yearly.get(k, {})
        countries.append({
            "key": k, "name": names.get(k, k), "tile": TILES.get(k), "last_month": last[k], "eu": k == EU,
            "gen_twh": _r(G, 2), "demand_twh": _r(win.demand.sum(), 2), "net_imports_twh": _r(win.imports.sum(), 2),
            "import_share": _r(win.net_in.sum() / win.den.sum(), 3) if win.den.sum() else 0,
            "cons_method": "flows" if (win.src == "flows").all() else "neighbours" if (win.src == "neighbours").all() else "mixed",
            "gen_g": _r(E / G * 1000), "cons_g": _r(win.num.sum() / win.den.sum() * 1000),
            "ren": _r(sum(win[s].sum() for s in RENEWABLE) / G, 3), "clean": _r((sum(win[s].sum() for s in RENEWABLE) + win["Nuclear"].sum()) / G, 3),
            "mix": mix, "price": _r(pk.mean()) if len(pk) else None, "price_months": int(len(pk)),
            "winter_g": _r(winter.emis.sum() / winter.gen.sum() * 1000) if len(winter) else None,
            "summer_g": _r(summer.emis.sum() / summer.gen.sum() * 1000) if len(summer) else None,
            "cloud": CLOUD_REGIONS.get(k, []),
            "trend": {"from_year": y["years"][y["years"].index(2015)] if 2015 in y.get("years", []) else None,
                      "from_g": y["gen_g"][y["years"].index(2015)] if 2015 in y.get("years", []) else None,
                      "to_year": y["years"][-1] if y else None, "to_g": y["gen_g"][-1] if y else None},
        })
    by_key = {c["key"]: c for c in countries}

    ours = []
    for r in by_region:
        if r["grid_key"] not in OUR_GRIDS:
            continue
        k, where = OUR_GRIDS[r["grid_key"]]
        c = by_key.get(k)
        f = F.GRID[r["grid_key"]]
        ours.append({"grid_key": r["grid_key"], "key": k, "where": where, "movable": r["grid_key"] != "EU",
                     "kwh": {s: r[f"kwh_{s}"] for s in ("low", "mid", "high")}, "cost_chf": r["cost_chf"],
                     "factor_g": {s: round(f.get(s) * 1000) for s in ("low", "mid", "high")}, "factor_source": f.source,
                     "gen_g": c and c["gen_g"], "cons_g": c and c["cons_g"], "ren": c and c["ren"], "price": c and c["price"]})

    dc = []
    for d in DATA_CENTRES:
        row = dict(d)
        if row["share"] is None and row["twh"]:
            dem = yearly.get(d["iso3"], {})
            if d["year"] in dem.get("years", []):
                v = dem["demand"][dem["years"].index(d["year"])]
                if v:
                    row["share"] = round(d["twh"] / v, 4)
                    row["kind"] = "derived"   # TWh published, share computed here
                    row["share_calc"] = f"{d['twh']} TWh / {v} TWh demand (Ember {d['year']})"
        row["name"] = names.get(d["iso3"], d["iso3"])
        dc.append(row)

    fl = _flow_outputs(flows, hourly, w, by_key, names)
    return {**base, "available": True, "flows": fl, "map": gridflows.load_map(), "as_of": as_of, "prices_as_of": pmax, "months": months, "countries": countries,
            "series": series, "yearly": {k: v for k, v in yearly.items() if k in by_key}, "ours": ours,
            "data_centres": dc, "data_centre_outlook": DATA_CENTRE_OUTLOOK, "europe_dc_share": EUROPE_DC_SHARE,
            "mix_order": MIX, "renewable": sorted(RENEWABLE), "cloud_source": CLOUD_SOURCE,
            "chf_per_eur": eur_chf,   # baseline-year average from exchange_rates.csv, to show EUR prices in CHF
            "method": {"gen": "Ember: emissions of all power plants in the country / their generation (life-cycle factors per fuel).",
                       "cons": "Estimate from the 15-minute cross-border flows: in each quarter hour the country's net import is "
                               "credited to the neighbours sending at that moment, each counted at its monthly generation "
                               "intensity; net exports leave at the domestic average. Where no flow data exists: net imports at "
                               "the neighbours' average. A neighbour's own imports are not traced further.",
                       "price": "Day-ahead wholesale price, average of the last 12 months. Cloud and hosting prices do not follow it "
                                "one to one."}}
