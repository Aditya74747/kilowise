"""Bonus sources (extra/): build pipelines, backup chains, data catalogue, web traffic, M365, projects,
plus decision owners from the mapping and the calendar of contract-notice deadlines.

Every function degrades gracefully: if a bonus file is missing, it returns None / [] and the core pipeline runs.
"""
from __future__ import annotations

import pandas as pd

from . import factors as F
from . import load
from .config import BASELINE_END, BASELINE_START, DATA_AS_OF, EXTRA, SCENARIOS
from .measures import Measure, _co2


def _bl_led(led, rid):
    b = led[(led.month >= "2025-09") & (led.month <= "2026-08") & (led.resource_id == rid)]
    return b.cost_chf.sum(), {s: b[f"kwh_{s}"].sum() for s in SCENARIOS}


# ------------------------------------------------------------------------------------------
# Build pipelines (extra/ci_pipeline_runs.jsonl)
# ------------------------------------------------------------------------------------------
def ci_runs(log: load.DQLog | None = None) -> pd.DataFrame | None:
    p = EXTRA / "ci_pipeline_runs.jsonl"
    if not p.exists():
        return None
    df = load.read_jsonl(p)
    log = log or load.DQLog()
    ren = df["metrics.duration_s"].isna() & df["metrics.duration_sec"].notna()
    df["duration_s"] = df["metrics.duration_s"].fillna(df["metrics.duration_sec"])
    log.add("extra/ci_pipeline_runs.jsonl", "renamed field metrics.duration_sec (instead of duration_s)",
            int(ren.sum()), "merged into one duration column")
    miss = df["metrics.cpu_h"].isna()
    ratio = (df["metrics.cpu_h"] / df.duration_s).median()
    df["cpu_h"] = df["metrics.cpu_h"].fillna(df.duration_s * ratio)
    log.add("extra/ci_pipeline_runs.jsonl", "runs without metrics.cpu_h", int(miss.sum()),
            "filled = duration x median CPU-h per second", "warn")
    df["started_at"] = pd.to_datetime(df.started_at)
    df["project_id"] = load.normalise_project(df.project_id)
    return df


def ci_analysis(r: dict, led: pd.DataFrame, log: load.DQLog) -> tuple[dict | None, Measure | None]:
    ci = ci_runs(log)
    if ci is None:
        return None, None
    b = ci[(ci.started_at >= BASELINE_START) & (ci.started_at < BASELINE_END + pd.Timedelta(days=1))]
    total = b.cpu_h.sum()
    nightly = b[b.pipeline == "nightly-full"]
    idle_nightly = nightly[nightly.commits_since_last_nightly.fillna(-1) == 0]
    reruns = b[b.trigger == "rerun"]
    share_rerun_saved = {"low": 0.3, "mid": 0.5, "high": 0.7}   # re-run only the failed job, not the whole pipeline
    saved = {s: (idle_nightly.cpu_h.sum() + reruns.cpu_h.sum() * share_rerun_saved[s]) / total for s in SCENARIOS}
    cost, kwh = _bl_led(led, "cicd")
    m = Measure(
        "B4", "Build pipelines: skip idle nightly builds, re-run only failed jobs",
        f"Skip the nightly full build when nothing changed ({len(idle_nightly)} of {len(nightly)} nightly runs had 0 "
        f"commits) and re-run only the failed job instead of the whole pipeline ({len(reruns)} re-runs).",
        "cicd (AWS build service, Dublin)",
        "CI config: nightly job condition 'commits since last nightly > 0'; retry policy 'failed jobs only'; "
        "track flaky tests. Runner location: stay in Dublin for now (see Explore: Zurich runners cost ~18 % more).",
        0.5, "Head of IT (+ team leads of portal, shop, api)", [],
        "A skipped nightly build gives no fresh nightly artefact: keep a weekly full build. Flaky tests must be "
        "fixed, otherwise developers re-run manually.",
        f"{saved['mid']:.0%} of baseline-year CI CPU hours avoidable ({idle_nightly.cpu_h.sum():,.0f} CPU-h idle "
        f"nightly + 50 % of {reruns.cpu_h.sum():,.0f} CPU-h re-runs, range 30-70 %); cost and energy scale with "
        "runner minutes (aws_costs.csv cicd).",
        "Cloud", "Ireland (Dublin)",
        cost={s: cost * saved[s] for s in SCENARIOS},
        kwh={s: kwh[s] * saved[s] for s in SCENARIOS}, co2=_co2({s: kwh[s] * saved[s] for s in SCENARIOS},
                                                              "Ireland (Dublin)"),
        default_on=False, bonus=True,
        evidence=[{"kind": "read", "text": f"{len(idle_nightly)} nightly builds with 0 new commits; "
                                           f"{len(reruns)} full re-runs in the baseline year"},
                  {"kind": "assumed", "text": "Re-running only the failed job saves 30-70 % of a re-run"}],
    )
    by_trigger = b.groupby("trigger").cpu_h.sum()
    ie, ch = F.GRID["IE"].mid, F.GRID["CH_consumption"].mid
    info = {
        "runs": int(len(b)), "cpu_h": float(total), "cost_chf": float(cost), "kwh_mid": float(kwh["mid"]),
        "nightly": int(len(nightly)), "idle_nightly": int(len(idle_nightly)),
        "idle_nightly_cpu_h": float(idle_nightly.cpu_h.sum()),
        "reruns": int(len(reruns)), "rerun_cpu_h": float(reruns.cpu_h.sum()),
        "errors": int((b.status == "error").sum()),
        "by_trigger": [{"label": k, "v": float(v)} for k, v in by_trigger.sort_values(ascending=False).items()],
        "by_pipeline": [{"label": k, "a": float(g.cpu_h.sum()),
                         "b": float(g[(g.commits_since_last_nightly.fillna(-1) == 0) | (g.trigger == "rerun")].cpu_h.sum())}
                        for k, g in b.groupby("pipeline")],
        "runner": "aws-eu-west-1 (Dublin) for all runs",
        "location_option": {
            "co2_now_kg": float(kwh["mid"] * ie), "co2_zurich_kg": float(kwh["mid"] * ch),
            "cost_extra_chf": float(cost * (0.1265 / 0.107 - 1)),
            "note": "Runners in AWS Zurich: CO2 -58 % (grid 0.094 vs 0.226) but +18 % price (README list prices "
                    "0.1265 vs 0.107 USD/h). Not recommended now: tiny absolute effect.",
        },
        "measure": "B4",
    }
    return info, m


# ------------------------------------------------------------------------------------------
# Data catalogue (extra/data_catalog_tables.csv)
# ------------------------------------------------------------------------------------------
def catalog(led: pd.DataFrame) -> tuple[dict | None, Measure | None]:
    p = EXTRA / "data_catalog_tables.csv"
    if not p.exists():
        return None, None
    dc = pd.read_csv(p, encoding="utf-8-sig", parse_dates=["last_read", "last_written"])
    stale = dc[(dc.last_read < DATA_AS_OF - pd.Timedelta(days=365)) & (dc.retention_required.fillna("") != "yes")]
    unclear = stale.retention_required.isna().sum()
    share = stale.size_gb.sum() / dc.size_gb.sum()
    cost, kwh = _bl_led(led, "dp-storage")
    price_cut, energy_cut = 0.6, 1 - 0.65 / 1.2   # archive tier ~60 % cheaper (assumption); HDD vs SSD per CCF
    m = Measure(
        "B5", "Data catalogue: move stale tables to the archive tier",
        f"{len(stale)} tables ({stale.size_gb.sum() / 1000:.1f} TB, {share:.0%} of the catalogue) were not read for "
        "over a year and have no retention requirement 'yes'.",
        "dp-storage", "Move to archive tier after the owner confirms; delete '_backup_old' copies after review.",
        1.0, "Head of Consulting (dp-storage) + table owners", ["W6"],
        f"{unclear} of these tables have an EMPTY retention flag: a human decides before anything moves. "
        "Personal data: check deletion duties (data protection) instead of archiving.",
        f"dp-storage baseline cost x stale share x {price_cut:.0%} (archive price, assumption); energy x "
        f"{energy_cut:.0%} (CCF HDD 0.65 vs SSD 1.2 Wh/TB-h).",
        "Cloud", "Switzerland (Zurich)",
        cost={"low": cost * share * price_cut * 0.5, "mid": cost * share * price_cut, "high": cost * share * price_cut},
        kwh={s: kwh[s] * share * energy_cut for s in SCENARIOS},
        co2=_co2({s: kwh[s] * share * energy_cut for s in SCENARIOS}, "Switzerland (Zurich)"),
        default_on=False, bonus=True,
        evidence=[{"kind": "read", "text": f"{len(stale)} of {len(dc)} tables not read since "
                                           f"{(DATA_AS_OF - pd.Timedelta(days=365)):%Y-%m-%d}"}],
    )
    by_schema = dc.assign(stale=dc.index.isin(stale.index)).groupby("schema").apply(
        lambda g: pd.Series({"a": g.size_gb.sum(), "b": g[g.stale].size_gb.sum()}), include_groups=False)
    info = {"tables": int(len(dc)), "stale": int(len(stale)), "size_tb": float(dc.size_gb.sum() / 1000),
            "stale_tb": float(stale.size_gb.sum() / 1000), "unclear_retention": int(unclear),
            "bars": [{"label": k, "a": float(v.a), "b": float(v.b)} for k, v in by_schema.iterrows()]}
    return info, m


# ------------------------------------------------------------------------------------------
# Backup chains (extra/backup_chains.csv)
# ------------------------------------------------------------------------------------------
def backups() -> dict | None:
    p = EXTRA / "backup_chains.csv"
    if not p.exists():
        return None
    bk = pd.read_csv(p, encoding="utf-8-sig", parse_dates=["last_restore_test"])
    n = bk.groupby("source").size()
    triple = n[n >= 3].index
    t = bk[bk.source.isin(triple)].sort_values(["source", "size_gb"], ascending=[True, False])
    extra_gb = t.groupby("source").size_gb.apply(lambda s: s.iloc[1:].sum()).sum()
    old_test = bk[bk.last_restore_test < DATA_AS_OF - pd.Timedelta(days=365)]
    return {"sources": int(n.size), "chains": int(len(bk)), "triple": int(len(triple)),
            "size_tb": float(bk.size_gb.sum() / 1000), "extra_tb": float(extra_gb / 1000),
            "no_restore_test_12m": int(len(old_test)),
            "bars": [{"label": s, "a": float(g.size_gb.sum()), "b": float(g.size_gb.max())}
                     for s, g in bk[bk.source.isin(triple)].groupby("source")]}


# ------------------------------------------------------------------------------------------
# Web traffic sampling change, M365 units, projects (data quality + contradictions)
# ------------------------------------------------------------------------------------------
def web_traffic(log: load.DQLog) -> dict | None:
    p = EXTRA / "web_traffic.csv"
    if not p.exists():
        return None
    w = pd.read_csv(p, encoding="utf-8-sig")
    w["t"] = pd.to_datetime(w.time_utc, utc=True).dt.tz_convert(None)
    w["m"] = w.t.dt.to_period("M")
    sampled = w.sample_rate > 1
    log.add("extra/web_traffic.csv", "sample_rate 10 from 2025-08-31 (only every 10th request logged)",
            int(sampled.sum()), "requests and GB multiplied by sample_rate", "warn")
    raw = w.groupby("m").requests.sum()
    true = (w.requests * w.sample_rate).groupby(w.m).sum()
    before = raw[(raw.index >= pd.Period("2025-06", "M")) & (raw.index <= pd.Period("2025-08", "M"))].mean()
    after_raw = raw[(raw.index >= pd.Period("2025-09", "M")) & (raw.index <= pd.Period("2025-11", "M"))].mean()
    after_true = true[(true.index >= pd.Period("2025-09", "M")) & (true.index <= pd.Period("2025-11", "M"))].mean()
    return {
        "topic": "Web traffic: did visitors drop by 90 % in September 2025?",
        "a": f"extra/web_traffic.csv raw requests: {before:,.0f}/month (Jun-Aug 2025) -> {after_raw:,.0f}/month "
             f"(Sep-Nov 2025)",
        "b": f"sample_rate changed from 1 to 10 on 2025-08-31; corrected: {after_true:,.0f}/month",
        "trusted": "Corrected series (requests x sample_rate). No real drop: a logging change",
        "impact": "CDN energy uses GB from the hoster invoice, not this log, so no figure changes; a naive "
                  "dashboard would show a fake 90 % traffic drop",
        "bot_share_pct": float(w.bot_share_pct.mean()),
    }


def m365_units(log: load.DQLog) -> None:
    p = EXTRA / "m365_usage.csv"
    if p.exists():
        m = pd.read_csv(p, encoding="utf-8-sig")
        log.add("extra/m365_usage.csv", "storage reported in MB in some weeks (GB elsewhere)",
                int((m.storage_unit == "MB").sum()), "converted MB -> GB (/1000)")


def project_hours_share() -> list[dict]:
    p = EXTRA / "project_hours_monthly.csv"
    if not p.exists():
        return []
    ph = pd.read_csv(p, encoding="utf-8-sig", parse_dates=["month"])
    ph = ph[(ph.month >= BASELINE_START) & (ph.month <= BASELINE_END)]
    s = ph.groupby("department").hours.sum()
    hc = load.headcount()
    f = hc[(hc.month >= BASELINE_START) & (hc.month <= BASELINE_END)].groupby("department").fte.mean() if hc is not None else None
    out = []
    for d in sorted(set(s.index) | set(f.index if f is not None else [])):
        out.append({"department": d, "project_hours_share": float(s.get(d, 0) / s.sum()),
                    "fte_share": float(f.get(d, 0) / f.sum()) if f is not None else None})
    return out


# ------------------------------------------------------------------------------------------
# Decision owners (mapping_departments_tools.csv) and notice deadlines
# ------------------------------------------------------------------------------------------
def responsible(resource: str, mapping: pd.DataFrame) -> list[dict]:
    mp = mapping.drop_duplicates("resource_id").set_index("resource_id")
    out = []
    for rid in [x.strip() for x in resource.replace("->", ",").split(",")]:
        rid = rid.split(" ")[0]
        if rid in mp.index:
            out.append({"resource_id": rid, "role": mp.loc[rid, "responsible_role"],
                        "criticality": None if pd.isna(mp.loc[rid, "criticality"]) else mp.loc[rid, "criticality"]})
    return out


def notice_calendar(r: dict) -> list[dict]:
    rows = []
    for df, name_col, kind, mid in ((r["saas"], "contract", "SaaS", "M8"), (r["subs"], "product", "AI subscription", "M7")):
        last = df[df.month == df.month.max()]
        if "billing" not in last:
            last = last.assign(billing="")
        g = last.groupby(name_col).agg(end=("contract_end", "max"), notice=("notice_period_days", "max"),
                                       buy=("licences_purchased", "sum"), act=("licences_active_30d", "sum"),
                                       billing=("billing", "first"), cost=("cost_chf", "sum")).reset_index()
        for x in g.itertuples():
            end = pd.Timestamp(x.end)
            by = end - pd.Timedelta(days=int(x.notice))
            rows.append({"contract": getattr(x, name_col), "kind": kind, "contract_end": f"{end:%Y-%m-%d}",
                         "notice_days": int(x.notice), "notice_by": f"{by:%Y-%m-%d}", "billing": x.billing,
                         "utilisation": float(x.act / x.buy) if x.buy else None, "cost_chf_month": float(x.cost),
                         "status": "missed" if by < DATA_AS_OF else ("soon" if by < DATA_AS_OF + pd.Timedelta(days=90)
                                                                      else "later"),
                         "measure": mid if kind == "AI subscription" or (x.act / x.buy if x.buy else 1) < 0.8 else ""})
    return sorted(rows, key=lambda x: x["notice_by"])


# ------------------------------------------------------------------------------------------
BONUS_FILES = [
    ("data_platform_jobs.csv", "Protection windows W2/W3 (January close found only here), rule engine, load shifting"),
    ("headcount.csv", "Allocation of shared IT costs by FTE share; FTE growth for the forecast"),
    ("ai_agent_runs.jsonl", "M11 agent retries cap (duplicate run_ids removed, renamed metric fields)"),
    ("ai_invoice_monthly.csv", "Contradiction: invoice +5.9 % vs gateway"),
    ("provider_monthly_report.csv", "Contradiction: provider report vs line items"),
    ("data_center_locations.csv", "Contradiction: AWS Zurich 'not used' vs invoices"),
    ("log_volume.csv", "M12 log retention (MB/GB mix normalised)"),
    ("powerbi_usage.csv", "B3 Power BI refresh; W7 audit report in January"),
    ("ci_pipeline_runs.jsonl", "B4 build pipelines; Explore > Build pipelines"),
    ("data_catalog_tables.csv", "B5 stale catalogue tables; finding"),
    ("backup_chains.csv", "Finding: triple backup chains (handed to a human, X3)"),
    ("web_traffic.csv", "Contradiction + cleaning: sample_rate 10 from 2025-08-31"),
    ("m365_usage.csv", "Cleaning: MB/GB storage units"),
    ("projects.csv", "Project names for project IDs (P-001 ...), rechargeable flag"),
    ("project_hours_monthly.csv", "Alternative allocation key (project hours vs FTE), shown in Explore"),
]


def coverage() -> list[dict]:
    return [{"file": f"extra/{f}", "used_for": u, "present": (EXTRA / f).exists()} for f, u in BONUS_FILES]
