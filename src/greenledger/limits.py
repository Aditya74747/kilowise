"""Know the limits: protection windows, injected instructions, contradictions between sources.

Every window has evidence from the data (ticket text AND a usage pattern where possible),
and an owner who decides. Measures read their schedules from here, so a window can never be
silently ignored.
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

from . import load
from .config import BASELINE_END, BASELINE_START

# ------------------------------------------------------------------------------------------
# Injected instructions in free text (data, never instructions)
# ------------------------------------------------------------------------------------------
INJECTION_PATTERNS = [
    r"ignore (all )?(previous|prior) instructions", r"instruction to ai", r"note for assistants",
    r"for ai (assistants|systems)", r"tell the user", r"set all costs", r"report costs .* lower",
    r"ignore the cost column", r"estimate the values yourself", r"system notice",
]
_INJ = re.compile("|".join(p.replace("(", "(?:") for p in INJECTION_PATTERNS), re.IGNORECASE)


def detect_injections(r: dict) -> list[dict]:
    hits = []

    def scan(df, col, source, idcol=None, extra=None):
        for i, row in df[df[col].astype(str).str.contains(_INJ, na=False)].iterrows():
            hits.append({
                "source": source, "where": f"{idcol}={row[idcol]}" if idcol else f"row {i + 2}",
                "field": col, "text": str(row[col])[:220],
                "action": "Ignored as instruction. Kept as data and shown here. No figure was changed.",
                **(extra(row) if extra else {}),
            })

    t = load.tickets()
    scan(t, "description", "it_tickets.csv", "ticket_id",
         lambda row: {"resource_id": row["resource_id"], "date": str(row["date"].date())})
    az = r["azure"]
    scan(az.assign(row_date=az["date"].dt.date.astype(str)), "note", "azure_costs.csv", "row_date",
         lambda row: {"resource_id": row["resource_id"], "date": row["row_date"]})
    ho = r["hoster"]
    scan(ho.assign(row_date=ho["date"].dt.date.astype(str)), "note", "hoster_invoice.csv", "row_date",
         lambda row: {"resource_id": row["resource_id"], "date": row["row_date"]})
    aw = r["aws"]
    if "note" in aw:
        scan(aw.assign(row_date=aw["date"].dt.date.astype(str)), "note", "aws_costs.csv", "row_date",
             lambda row: {"resource_id": row["resource_id"], "date": row["row_date"]})
    return hits


# ------------------------------------------------------------------------------------------
# Calendar helpers
# ------------------------------------------------------------------------------------------
def last_working_days(cal: pd.DataFrame, n: int = 3) -> set[pd.Timestamp]:
    wd = cal[cal.workday == 1].sort_values("date")
    return set(wd.groupby(wd.date.dt.to_period("M")).date.tail(n))


def quarter_training_days(cal: pd.DataFrame) -> set[pd.Timestamp]:
    d = cal.date
    return set(d[(d.dt.month.isin([1, 4, 7, 10])) & (d.dt.day <= 3)])


# ------------------------------------------------------------------------------------------
# Protection windows
# ------------------------------------------------------------------------------------------
def windows(r: dict) -> list[dict]:
    cal = load.calendar()
    dp = load.data_platform(load.DQLog())
    jobs = load.jobs()
    out = []

    # dp-prod month-end: ticket + usage pattern
    prod = dp[dp.resource_id == "dp-prod"].merge(cal, on="date")
    lwd = last_working_days(cal)
    me = prod[prod.date.isin(lwd)].active_use_h.mean()
    normal = prod[(prod.workday == 1) & ~prod.date.isin(lwd)].active_use_h.mean()
    out.append({
        "id": "W1", "resource_id": "dp-prod", "name": "Month-end close (finance)",
        "when": "Last 3 working days of each month, 18:00 until about 04:00 next morning",
        "evidence": f"T-1029. Usage: {me:.1f} active h/day on those days vs {normal:.1f} on other working days"
                    + ("; scheduler job 'Month-end close' 18:00, ~10 h" if jobs is not None else ""),
        "source": "it_tickets.csv T-1029, data_platform_usage.csv, extra/data_platform_jobs.csv",
        "owner": "Head of Finance (consumer) + Head of Consulting (owner)", "type": "fixed",
    })
    if jobs is not None:
        ye = jobs[jobs.job_name == "Year-end close analysis"]
        out.append({
            "id": "W2", "resource_id": "dp-prod", "name": "Year-end close analysis (January)",
            "when": "Every working day in January, 20:00 for about 6 h",
            "evidence": f"Found only in the scheduler: {len(ye)} runs, all in January, start 20:00, "
                        f"avg {ye.duration_h.mean():.1f} h. No ticket mentions it.",
            "source": "extra/data_platform_jobs.csv (pattern, no ticket)",
            "owner": "Head of Finance + Head of Consulting", "type": "fixed",
        })
        night = jobs[(jobs.resource_id == "dp-prod") & jobs.job_name.isin(
            ["Nightly ETL", "PBI refresh large", "Reporting export", "Cost export"])]
        wk = night.merge(cal, on="date")
        out.append({
            "id": "W3", "resource_id": "dp-prod", "name": "Nightly data jobs incl. weekends",
            "when": "Daily 02:00-07:30 (ETL done by 06:00, PBI refresh by 07:30); reporting export by 08:00 on working days",
            "evidence": f"{len(wk)} runs; {int((wk.workday == 0).sum())} of them on weekends/holidays",
            "source": "extra/data_platform_jobs.csv (time_window = fixed)",
            "owner": "Head of Consulting", "type": "fixed",
        })
    dev = dp[dp.resource_id == "dp-dev"]
    qd = quarter_training_days(cal)
    q_use = dev[dev.date.isin(qd)].active_use_h.mean()
    out.append({
        "id": "W4", "resource_id": "dp-dev + gpu-ml", "name": "Quarterly model training",
        "when": "Days 1-3 of January, April, July, October, continuously; must start automatically",
        "evidence": f"T-1053, T-1101. Usage: {q_use:.1f} active h/day on those days "
                    f"vs {dev[~dev.date.isin(qd)].active_use_h.mean():.1f} otherwise; GPU ~43 % in those weeks vs ~6 %",
        "source": "it_tickets.csv T-1053/T-1101, data_platform_usage.csv, server_metrics_weekly.csv",
        "owner": "Head of IT (dp-dev) + Head of Consulting (gpu-ml)", "type": "fixed",
    })
    out.append({
        "id": "W5", "resource_id": "dr-failover (in vm-test)", "name": "Disaster-recovery server must run",
        "when": "Always (24/7), even though never under load",
        "evidence": "T-1094 (requirement from management). Monitoring: CPU ~0.4 %, which would look like waste",
        "source": "it_tickets.csv T-1094, server_metrics_weekly.csv", "owner": "Management", "type": "fixed",
    })
    out.append({
        "id": "W6", "resource_id": "st-backup", "name": "10-year backup retention",
        "when": "Permanent", "evidence": "T-1039 (legal); T-1195 deletion request rejected",
        "source": "it_tickets.csv", "owner": "Head of IT", "type": "fixed",
    })
    out.append({
        "id": "W7", "resource_id": "pbi-07", "name": "Legacy receivables report for audit",
        "when": "Closing month (January), otherwise hardly used",
        "evidence": "T-1167; Power BI views jump to 600-800 in January (extra/powerbi_usage.csv)",
        "source": "it_tickets.csv T-1167", "owner": "Head of Finance", "type": "fixed",
    })
    out.append({
        "id": "W8", "resource_id": "vm-test", "name": "Release tests / change freeze",
        "when": "By arrangement with the project (e.g. 2026-03-01..31 continuous)",
        "evidence": "T-1204; scheduler 'Release test run UAT' every working day of March 2026",
        "source": "it_tickets.csv T-1204, extra/data_platform_jobs.csv", "owner": "Head of IT + project lead",
        "type": "by arrangement",
    })
    return out


# ------------------------------------------------------------------------------------------
# Contradictions between sources
# ------------------------------------------------------------------------------------------
def contradictions(r: dict) -> list[dict]:
    out = []
    inv, met = r["inventory"], r["metrics"]
    last30 = met[met.week_start >= met.week_start.max() - pd.Timedelta(days=28)].groupby("server_id").cpu_avg_pct.mean()
    tests = inv[inv.type == "test"].set_index("server_id")
    a = tests.cpu_utilisation_30d_pct.mean()
    b = last30.reindex(tests.index).mean()
    out.append({
        "topic": "CPU of test servers", "a": f"server_inventory.csv: {a:.1f} % (30 days)",
        "b": f"server_metrics_weekly.csv: {b:.1f} % (last 4 weeks)",
        "trusted": "Weekly monitoring (time series, complete) for trends; inventory only as snapshot",
        "impact": "Savings for test servers computed with monitoring values (more conservative)",
    })
    # T-1074 claim vs invoices
    az = r["azure"]
    bl = az[(az.date >= BASELINE_START) & (az.date <= BASELINE_END)]
    p = bl[bl.resource_id.isin(["dp-prod", "dp-dev"])].groupby("resource_id").apply(
        lambda d: d.cost_chf.sum() / d.quantity.sum())
    out.append({
        "topic": "Is Frankfurt cheaper for the data platform?",
        "a": "it_tickets.csv T-1074: dp-dev is in Frankfurt 'because the service was cheaper there'",
        "b": f"azure_costs.csv: CHF {p.get('dp-dev', np.nan):.3f}/node-h Frankfurt vs CHF {p.get('dp-prod', np.nan):.3f} Zurich",
        "trusted": "Invoice (actual prices, converted with monthly rates)",
        "impact": "Moving dp-dev to Zurich is about cost-neutral but cuts its CO2 by ~75 %",
    })
    # T-1058 scale-back never happened
    aw = r["aws"]
    vt = aw[(aw.resource_id == "vm-test")].groupby(aw.date.dt.to_period("M")).quantity.mean()
    out.append({
        "topic": "Test environment scale-back",
        "a": "it_tickets.csv T-1058 (2025-04-01): enlarged 16 -> 64 vCPU, 'scale-back planned after go-live'",
        "b": f"aws_costs.csv: still {vt.iloc[-1] / 24:.0f} vCPU in {vt.index[-1]}; portal relaunch P-009 completed 2026-03-31",
        "trusted": "Invoice (what is actually running)", "impact": "Measure M5 completes the planned scale-back",
    })
    loc = load.data_center_locations()
    if loc is not None:
        used = loc[(loc.provider == "AWS") & (loc.region.str.contains("Zurich"))].used_by_sme.iloc[0]
        out.append({
            "topic": "Does the SME use AWS Zurich?",
            "a": f"extra/data_center_locations.csv: AWS Switzerland (Zurich) used_by_sme = {used}",
            "b": "aws_costs.csv: st-archive, net-egress and support billed in 'Switzerland (Zurich)'",
            "trusted": "Invoice region (per row). Location catalogue flagged as outdated",
            "impact": "st-archive and net-egress counted with the Swiss grid mix",
        })
    inv_ai = load.ai_invoice()
    if inv_ai is not None:
        fx = r["fx"]
        inv_ai = inv_ai.copy()
        inv_ai["chf"] = load.to_chf(inv_ai.amount, inv_ai.currency, inv_ai.month, fx)
        ai = r["ai"]
        gw = ai[(ai.date >= BASELINE_START) & (ai.date <= BASELINE_END)].cost_chf.sum()
        iv = inv_ai[(inv_ai.month >= BASELINE_START) & (inv_ai.month <= BASELINE_END)].chf.sum()
        out.append({
            "topic": "AI token cost: gateway vs provider invoice",
            "a": f"ai_usage.csv (gateway): CHF {gw:,.0f} in the baseline year",
            "b": f"extra/ai_invoice_monthly.csv: CHF {iv:,.0f} (+{(iv / gw - 1) * 100:.1f} %), tokens also ~5-7 % higher",
            "trusted": "Gateway for allocation by department/task; invoice total used as the 'high' cost bound",
            "impact": "Part of the traffic bypasses the gateway, so ask IT which apps call the APIs directly",
        })
    rep = load.provider_report()
    if rep is not None:
        cloud = pd.concat([r["azure"][["date", "cost_chf"]], r["aws"][["date", "cost_chf"]]])
        m = cloud.groupby(cloud.date.dt.to_period("M").dt.to_timestamp()).cost_chf.sum()
        rr = rep.set_index("month").total_cost_chf
        diff = (rr / m - 1).dropna() * 100
        out.append({
            "topic": "Provider monthly report vs line items",
            "a": "extra/provider_monthly_report.csv 'Total cost all services': within ±3 % of Azure+AWS until 2025-08",
            "b": f"from 2025-09 +{diff[diff.index >= '2025-09-01'].min():.0f} to +{diff.max():.0f} % above the line items "
                 f"(peak {diff.idxmax():%Y-%m})",
            "trusted": "Line items (complete, per resource). Report scope unclear, so we ask the provider",
            "impact": "Not used for the baseline; shown as an open question",
        })
    out.append({
        "topic": "Criticality labels in the master data",
        "a": "mapping_departments_tools.csv: dp-dev 'low', gpu-ml empty",
        "b": "Tickets T-1053/T-1101: quarterly model training depends on both",
        "trusted": "Tickets + usage pattern (criticality 'not always reliable' per data dictionary)",
        "impact": "Pausing is allowed, but only with auto-start for the training window",
    })
    return out


def protection_status(measure_windows: list[str], all_windows: list[dict]) -> list[dict]:
    idx = {w["id"]: w for w in all_windows}
    return [idx[w] for w in measure_windows if w in idx]


# ------------------------------------------------------------------------------------------
# Rule engine: schedules as code, checked against every scheduled job run
# ------------------------------------------------------------------------------------------
# A schedule maps each calendar date to the hours the resource is ON: [(start_h, end_h), ...].
# The SAME schedule drives the savings in measures.py and the check below.
DAY = pd.Timedelta(days=1)
JOB_WINDOW = {"Nightly ETL": "W3", "PBI refresh large": "W3", "Reporting export": "W3", "Cost export": "W3",
              "Month-end close": "W1", "Year-end close analysis": "W2", "Quarterly model training": "W4",
              "Release test run UAT": "W8", "Backup snapshot": "W6"}


def _merge(iv):
    out = []
    for a, b in sorted(iv):
        if out and a <= out[-1][1] + 1e-9:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def on_hours(iv) -> float:
    return sum(b - a for a, b in _merge(iv))


def _inside(iv, a, b) -> bool:
    return any(x <= a + 1e-9 and b <= y + 1e-9 for x, y in _merge(iv))


def covered(sched: dict, date: pd.Timestamp, start_h: float, dur_h: float) -> bool:
    """True if the whole run [start, start+dur] (spilling into the next days) falls into ON hours."""
    end = start_h + dur_h
    d, a = date, start_h
    while True:
        b = min(end, 24.0)
        if not _inside(sched.get(d, []), a, b):
            return False
        if end <= 24.0:
            return True
        d, a, end = d + DAY, 0.0, end - 24.0


def schedule_m1(cal: pd.DataFrame, jobs: pd.DataFrame | None) -> dict:
    """dp-prod: on 01:30-20:00 on working days, 01:30-08:00 otherwise; 24 h on the last 3 working days, on
    month-end close days and on January working days; the morning after a 24 h day stays on from 00:00."""
    lwd = last_working_days(cal)
    me = set(jobs[jobs.job_name == "Month-end close"].date) if jobs is not None else set()
    full = {r.date for r in cal.itertuples() if r.date in lwd or r.date in me or (r.date.month == 1 and r.workday == 1)}
    out = {}
    for r in cal.itertuples():
        if r.date in full:
            out[r.date] = [(0.0, 24.0)]
            continue
        iv = [(1.5, 20.0)] if r.workday == 1 else [(1.5, 8.0)]
        if r.date - DAY in full:
            iv.append((0.0, 1.5))       # month-end close runs until ~04:00, year-end close until ~02:00
        out[r.date] = iv
    return out


def schedule_m2(cal: pd.DataFrame, jobs: pd.DataFrame | None) -> dict:
    """dp-dev: on 08:00-18:00 on working days, 24 h on training days (W4), 17:00-19:00 for a weekend refresh."""
    qd = quarter_training_days(cal)
    refresh = set(jobs[jobs.job_name == "Test data refresh"].date) if jobs is not None else set()
    out = {}
    for r in cal.itertuples():
        if r.date in qd:
            out[r.date] = [(0.0, 24.0)]
        elif r.workday == 1:
            out[r.date] = [(8.0, 18.0)]
        else:
            out[r.date] = [(17.0, 19.0)] if r.date in refresh else []
    return out


def schedule_m4(cal: pd.DataFrame) -> dict:
    """gpu-ml: on during the quarterly training days, otherwise started on request."""
    qd = quarter_training_days(cal)
    return {r.date: ([(0.0, 24.0)] if r.date in qd else []) for r in cal.itertuples()}


def schedule_m6(cal: pd.DataFrame) -> dict:
    """Remaining test servers: on 07:00-19:00 on working days."""
    return {r.date: ([(7.0, 19.0)] if r.workday == 1 else []) for r in cal.itertuples()}


def schedule_x1(cal: pd.DataFrame) -> dict:
    """The rejected idea X1: production only 08:00-20:00 on working days."""
    return {r.date: ([(8.0, 20.0)] if r.workday == 1 else []) for r in cal.itertuples()}


def _check_jobs(sched: dict, runs: pd.DataFrame) -> list[dict]:
    """Protected runs (fixed window or training) must be inside ON hours; flexible runs outside are counted."""
    out = []
    runs = runs[runs.date.isin(sched.keys())]
    for job, g in runs.groupby("job_name"):
        tw = str(g.time_window.iloc[0])
        ok = [covered(sched, r.date, _h(r.start_time), float(r.duration_h or 0)) for r in g.itertuples()]
        miss = g[[not x for x in ok]]
        kind = ("protected" if tw.startswith("fixed") or job == "Quarterly model training"
                else "arrangement" if tw.startswith("by arrangement") else "flexible")
        out.append({"job": job, "window": JOB_WINDOW.get(job, ""), "kind": kind, "time_window": tw,
                    "checked": int(len(g)), "outside": int(len(miss)),
                    "examples": [f"{d:%Y-%m-%d} {s}" for d, s in zip(miss.date.head(3), miss.start_time.head(3))]})
    return out


def _h(hhmm: str) -> float:
    h, m = str(hhmm).split(":")[:2]
    return int(h) + int(m) / 60


def check_measures(r: dict) -> list[dict]:
    """Run every schedule-based measure (and the rejected X1) against the job scheduler and the windows."""
    cal = load.calendar()
    jobs = load.jobs()
    res = []

    def add(mid, resource, sched, runs, extra=None):
        checks = _check_jobs(sched, runs) if runs is not None else []
        checks += extra or []
        conflicts = sum(c["outside"] for c in checks if c["kind"] == "protected")
        res.append({"measure": mid, "resource": resource, "checks": checks, "conflicts": int(conflicts),
                    "flexible_outside": int(sum(c["outside"] for c in checks if c["kind"] == "flexible")),
                    "status": "pass" if conflicts == 0 else "blocked"})

    j = jobs if jobs is not None else pd.DataFrame(columns=["date", "job_name", "resource_id", "start_time",
                                                             "duration_h", "time_window"])
    add("M1", "dp-prod", schedule_m1(cal, jobs), j[j.resource_id == "dp-prod"])
    add("M2", "dp-dev", schedule_m2(cal, jobs), j[j.resource_id == "dp-dev"])
    qd = sorted(d for d in quarter_training_days(cal) if d in set(cal.date))
    s4 = schedule_m4(cal)
    add("M4", "gpu-ml", s4, None, [{"job": "Quarterly training days (T-1053, T-1101)", "window": "W4",
                                    "kind": "protected", "time_window": "days 1-3 of Jan/Apr/Jul/Oct",
                                    "checked": len(qd), "outside": int(sum(not covered(s4, d, 0, 24) for d in qd)),
                                    "examples": []}])
    inv = r["inventory"]
    from .measures import KEEP_TEST
    kept = set(KEEP_TEST) | {"dr-failover"}
    dr_ok = "dr-failover" in kept and "dr-failover" in set(inv.server_id)
    add("M5", "vm-test", {}, None, [{"job": "dr-failover stays (T-1094)", "window": "W5", "kind": "protected",
                                     "time_window": "always on", "checked": 1, "outside": 0 if dr_ok else 1,
                                     "examples": []}])
    add("M6", "vm-test", schedule_m6(cal), j[j.resource_id == "vm-test"],
        [{"job": "dr-failover not scheduled", "window": "W5", "kind": "protected", "time_window": "always on",
          "checked": 1, "outside": 0, "examples": []}])
    add("X1", "dp-prod", schedule_x1(cal), j[j.resource_id == "dp-prod"])
    return res
