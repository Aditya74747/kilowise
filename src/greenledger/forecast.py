"""Forecast for the next three years (Sep-Aug years 2026/27 .. 2028/29), with and without the package.

Every driver comes from the data or a ticket; the range (low/mid/high) is the growth uncertainty.
Conversion factors stay at mid so that the forecast shows the effect of growth, not of factor choice.
"""
from __future__ import annotations

import pandas as pd

from . import load
from .config import BASELINE_END, BASELINE_START

YEARS = ["2026/27", "2027/28", "2028/29"]
METRICS = {"cost": "cost_chf", "kwh": "kwh_mid", "co2": "co2_mid_consumption"}
BUCKET_OF_MEASURE = {"M1": "dp-prod", "M2": "cloud", "M3": "cloud", "M4": "servers", "M5": "servers", "M6": "servers",
                     "M7": "subs", "M8": "saas", "M9": "ai", "M10": "ai", "M11": "ai",
                     "M12": "cloud", "B3": "cloud", "B4": "cloud", "B5": "cloud"}
RAMP_Y1 = 0.85   # measures go live during the first months; SaaS right-sizing only at renewal


def _bucket(row) -> str:
    if row.resource_id == "dp-prod":
        return "dp-prod"
    if row.source == "ai_usage.csv" or str(row.source).startswith("normalisation (T-1212)"):
        return "ai"
    if row.source == "ai_subscriptions.csv":
        return "subs"
    if row.source == "saas_contracts.csv":
        return "saas"
    return "servers" if row.category == "Servers" else "cloud"


STEP_RESOURCES = {"vm-test"}   # one-off enlargement 16 -> 64 vCPU in Apr 2025 (T-1058): a step, not a trend
DAMPING = 0.5                  # observed trends fade: year 2 grows at half the rate of year 1, year 3 at a quarter


def _yoy(led: pd.DataFrame, bucket: str) -> float:
    """Growth of the same 10 months (Nov-Aug) year on year, one-offs and known steps excluded."""
    d = led[(led.bucket == bucket) & ~led.adjustment & ~led.resource_id.isin(STEP_RESOURCES)]
    a = d[(d.month >= "2024-11") & (d.month <= "2025-08")].cost_chf.sum()
    b = d[(d.month >= "2025-11") & (d.month <= "2026-08")].cost_chf.sum()
    if bucket == "ai":   # remove the endless-loop excess (T-1212) from the second year
        b += led[led.source == "normalisation (T-1212)"].cost_chf.sum()
    return float(b / a - 1) if a else 0.0


def build(r: dict, led: pd.DataFrame, measures: list[dict]) -> dict:
    led = led.copy()
    led["bucket"] = [_bucket(x) for x in led.itertuples()]
    bl = led[(led.month >= "2025-09") & (led.month <= "2026-08")]
    base = bl.groupby("bucket")[list(METRICS.values())].sum()

    # ---- drivers -------------------------------------------------------------------------
    hc = load.headcount()
    fte_g = 0.0
    if hc is not None:
        t = hc.groupby("month").fte.sum().sort_index()
        years = (t.index[-1] - t.index[0]).days / 365.25
        fte_g = float((t.iloc[-1] / t.iloc[0]) ** (1 / years) - 1)
    dp = load.data_platform(load.DQLog())
    nodes_bl = dp[(dp.resource_id == "dp-prod") & (dp.date >= BASELINE_START) & (dp.date <= BASELINE_END)].node_count.mean()
    node_step = 24 / nodes_bl                                             # T-1261: 24 nodes from 2026-10-01
    sa = r["saas"]
    m365_bl = sa[(sa.contract == "Microsoft 365") & (sa.month >= BASELINE_START) & (sa.month <= BASELINE_END)]
    m365_price = float((m365_bl.price_per_licence * m365_bl.licences_purchased).sum() / m365_bl.licences_purchased.sum())
    m365_share = float(m365_bl.cost_chf.sum() / sa[(sa.month >= BASELINE_START) & (sa.month <= BASELINE_END)].cost_chf.sum())
    saas_step = 1 + m365_share * (14.0 / m365_price - 1)                  # M365 14 USD from 2026-07-01
    su = r["subs"]
    cop = su[(su["product"] == "Microsoft Copilot") & (su.month >= BASELINE_START) & (su.month <= BASELINE_END)]
    cop_price = float((cop.price_per_seat * cop.licences_purchased).sum() / cop.licences_purchased.sum())
    cop_share = float(cop.cost_chf.sum() / su[(su.month >= BASELINE_START) & (su.month <= BASELINE_END)].cost_chf.sum())
    subs_step = 1 + cop_share * (21.0 / cop_price - 1)                    # Copilot Business 21 USD from Dec 2025
    g_ai, g_cloud, g_srv = _yoy(led, "ai"), _yoy(led, "cloud"), _yoy(led, "servers")

    mid = {"dp-prod": max(g_cloud, 0.0), "cloud": g_cloud, "servers": g_srv, "ai": g_ai, "subs": fte_g, "saas": fte_g}
    scen = {
        "low": {k: (fte_g if k in ("subs", "saas") else min(v, fte_g)) for k, v in mid.items()},
        "mid": mid,
        "high": {k: v * 1.5 if v > 0 else v * 0.5 for k, v in mid.items()},
    }
    step = {"dp-prod": node_step, "cloud": 1.0, "servers": 1.0, "ai": 1.0, "subs": subs_step, "saas": saas_step}

    # ---- package share per bucket and metric --------------------------------------------
    on = [m for m in measures if m["default_on"]]
    share = {b: {} for b in base.index}
    for b in base.index:
        for k, col in METRICS.items():
            sav = sum((m["cost"]["mid"] if k == "cost" else m["kwh"]["mid"] if k == "kwh" else m["co2"]["mid_consumption"])
                      for m in on if BUCKET_OF_MEASURE.get(m["id"]) == b)
            share[b][k] = min(sav / base.loc[b, col], 0.95) if base.loc[b, col] else 0.0

    # ---- projection ---------------------------------------------------------------------
    series = {k: {"baseline": float(base[col].sum())} for k, col in METRICS.items()}
    by_bucket = {b: {k: {"baseline": float(base.loc[b, col])} for k, col in METRICS.items()} for b in base.index}
    for k, col in METRICS.items():
        for s in ("low", "mid", "high"):
            wo, wi = [], []
            for y in range(1, 4):
                tot_wo = tot_wi = 0.0
                for b in base.index:
                    g = scen[s][b]
                    damp = 1.0 if b in ("subs", "saas") else DAMPING   # FTE growth is structural, not damped
                    factor = 1.0
                    for i in range(y):
                        factor *= 1 + g * damp ** i
                    v = base.loc[b, col] * step[b] * factor
                    by_bucket[b][k].setdefault(f"without_{s}", []).append(float(v))
                    tot_wo += v
                    tot_wi += v * (1 - share[b][k] * (RAMP_Y1 if y == 1 else 1.0))
                wo.append(tot_wo)
                wi.append(tot_wi)
            series[k][f"without_{s}"] = wo
            series[k][f"with_{s}"] = wi
    growth = {s: float((series["cost"][f"without_{s}"][-1] / series["cost"]["baseline"]) ** (1 / 3) - 1)
              for s in ("low", "mid", "high")}
    drivers = [
        {"driver": "Headcount (FTE)", "value": f"{fte_g:+.1%} per year", "applies_to": "AI seats, SaaS licences",
         "source": "extra/headcount.csv, Nov 2024 to Aug 2026 (CAGR)"},
        {"driver": "AI token usage", "value": f"{g_ai:+.1%} per year", "applies_to": "AI API (gateway)",
         "source": "ai_usage.csv, Nov-Aug year on year, endless loop T-1212 excluded"},
        {"driver": "Cloud services", "value": f"{g_cloud:+.1%} per year", "applies_to": "Cloud excl. dp-prod",
         "source": "azure/aws/hoster line items, Nov-Aug year on year"},
        {"driver": "Servers", "value": f"{g_srv:+.1%} per year", "applies_to": "vm-app, db-fin, gpu-ml",
         "source": "Nov-Aug year on year; vm-test step (T-1058) excluded"},
        {"driver": "Production platform 24 nodes", "value": f"x {node_step:.2f} from Oct 2026",
         "applies_to": "dp-prod", "source": f"it_tickets.csv T-1261 (baseline average {nodes_bl:.1f} nodes)"},
        {"driver": "Microsoft 365 price 14 USD", "value": f"x {saas_step:.3f} on SaaS",
         "applies_to": "SaaS", "source": "README list prices (12.50 -> 14 USD from 2026-07-01)"},
        {"driver": "Copilot Business 21 USD", "value": f"x {subs_step:.3f} on AI seats",
         "applies_to": "AI subscriptions", "source": f"README list prices (baseline average {cop_price:.1f} USD; promo "
                                                     "18 USD Jul-Dec 2026 ignored, conservative)"},
        {"driver": "Trend damping", "value": "year 2 at 1/2, year 3 at 1/4 of the observed rate",
         "applies_to": "AI, cloud, servers", "source": "assumption (trends from 22 months of data do not compound)"},
        {"driver": "Range", "value": "low = growth capped at FTE; high = observed trends x 1.5",
         "applies_to": "all", "source": "assumption"},
        {"driver": "Package ramp-up", "value": f"{RAMP_Y1:.0%} of savings in year 1, 100 % after",
         "applies_to": "with package", "source": "assumption (go-live during the year, SaaS at renewal)"},
    ]
    return {"years": YEARS, "series": series, "by_bucket": by_bucket, "growth_per_year": growth, "drivers": drivers,
            "package_share": {b: share[b] for b in share}}
