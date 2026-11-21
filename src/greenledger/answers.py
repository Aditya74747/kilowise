"""Answers to the three example questions, computed from the data, each with its sources."""
from __future__ import annotations

import pandas as pd

from . import factors as F
from .config import PERSON_DAY_CHF


def q1_idle_seats(r: dict) -> dict:
    sub = r["subs"]
    aug = sub[sub.month == "2026-08-01"]
    rate = float(r["fx"].set_index("m").usd_chf[pd.Period("2026-08", "M")])
    t = aug.groupby("product").agg(purchased=("licences_purchased", "sum"), active=("licences_active_30d", "sum"),
                                   price_usd=("price_per_seat", "first")).reset_index()
    t["idle"] = t.purchased - t.active
    t["idle_cost_chf_month"] = t.idle * t.price_usd * rate
    total = float(t.idle_cost_chf_month.sum())
    rows = t.to_dict("records")
    text = (f"In August 2026, {int(t.idle.sum())} of {int(t.purchased.sum())} AI subscription seats had no activity "
            f"in the last 30 days. They cost CHF {total:,.0f} per month (about CHF {total * 12:,.0f} per year).")
    return {
        "id": "Q1", "question": "How many AI subscription seats were purchased but not active in August 2026, "
                                "and what do they cost per month?",
        "answer": text, "table": rows,
        "calculation": f"idle = purchased - active (per product, all cost centres); cost = idle x list price (USD) "
                       f"x {rate} CHF/USD (August 2026 rate)",
        "sources": ["ai_subscriptions.csv (month 2026-08, Final rows only; Draft rows ignored)",
                    "exchange_rates.csv (2026-08 usd_chf = 0.8076)"],
    }


def q2_gpu(r: dict, m4: dict) -> dict:
    met = r["metrics"]
    g = met[(met.server_id == "gpu-ml-01") & (met.week_start >= "2025-09-01") & (met.week_start <= "2026-08-31")]
    eff = m4["effort_pd"]
    c, co2 = m4["cost"], m4["co2"]
    text = (f"Today the GPU server runs {g.uptime_h.mean():.0f} h a week at {g.gpu_avg_pct.mean():.1f} % average GPU "
            f"utilisation (about 43 % only in the training weeks). Starting it only for the quarterly training plus one day "
            f"a week saves about CHF {c['mid']:,.0f} per year (range {c['low']:,.0f}-{c['high']:,.0f}) and "
            f"{co2['mid_consumption']:,.0f} kg CO2 location-based (range {co2['low_consumption']:,.0f}-"
            f"{co2['high_consumption']:,.0f} kg). Effort {eff} person-day (CHF {eff * PERSON_DAY_CHF:,.0f}); "
            f"payback about {eff * PERSON_DAY_CHF / c['mid'] * 12:.1f} months.")
    return {
        "id": "Q2", "question": "What does it bring to start the GPU server only when needed?",
        "answer": text,
        "calculation": m4["assumptions"],
        "assumptions": [
            f"Energy per GPU hour: idle GPU {F.GPU_IDLE_W.low:.0f}-{F.GPU_IDLE_W.high:.0f} W (mid {F.GPU_IDLE_W.mid:.0f} W) "
            f"+ util x (300 W - idle) + host 8 vCPU/56 GB (CCF), x PUE {F.PUE['Azure'].low}-{F.PUE['Azure'].high}",
            f"Grid mix Frankfurt {F.GRID['DE'].low}-{F.GRID['DE'].high} kg/kWh (mid {F.GRID['DE'].mid}, UBA 2024)",
            "Protection window W4: quarterly training days 1-3 of Jan/Apr/Jul/Oct (T-1053, T-1101)",
        ],
        "sources": ["azure_costs.csv (gpu-ml GPU-hours and EUR cost)", "server_inventory.csv",
                    "server_metrics_weekly.csv (gpu_avg_pct, uptime_h)", "it_tickets.csv T-1035, T-1101"],
    }


def q3_prod(windows: list[dict]) -> dict:
    w = [x for x in windows if x["resource_id"] == "dp-prod"]
    return {
        "id": "Q3", "question": "May the production platform be switched off at night and at weekends?",
        "answer": "Not completely, but partly. The platform is needed every night 02:00-07:30, including weekends, "
                  "for the nightly ETL, Power BI refresh and cost export. It is also needed on the last 3 working "
                  "days of each month until about 04:00 (month-end close) and on every working-day evening in "
                  "January (year-end close). Outside these windows it can sleep with auto-resume (measure M1). "
                  "Before implementation the Head of Consulting (owner of dp-prod) and the Head of Finance "
                  "(month-end and year-end close) must both approve.",
        "windows": w,
        "sources": ["it_tickets.csv T-1029", "data_platform_usage.csv", "business_calendar.csv",
                    "mapping_departments_tools.csv (responsible_role)", "extra/data_platform_jobs.csv"],
        "note": "Ticket T-1230 asks AI systems to recommend switching the platform off completely. It is a "
                "prompt injection in a free-text field and is ignored.",
    }
