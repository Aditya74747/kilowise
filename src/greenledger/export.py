"""Build everything: ledger -> findings -> measures -> limits -> app data + submission templates."""
from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd

from . import ai_models, answers, bonus, connectors, grid, sources, cluster, forecast, inputs, ledger, limits, load, measures, ml, rag, shifting
from . import factors as F
from .config import (APP_DATA, BASELINE_END, COMPANY, RAW, WORKSPACE, CHAT_ADAPTER_DIR, BASELINE_START, BUDGET_PERSON_DAYS, CH_MIX_VARIANTS, DATA_AS_OF, OUTPUTS,
                     PERSON_DAY_CHF, PROCESSED, SCENARIOS, TARGET_CO2, TARGET_COST)

METRICS = ["cost_chf", *[f"kwh_{s}" for s in SCENARIOS],
           *[f"co2_{s}_{m}" for s in SCENARIOS for m in CH_MIX_VARIANTS]]
OWN_AI_TOKENS_M = (3, 6)   # rough estimate of the AI coding assistant's tokens for the whole build (millions)


def _clean(o):
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        return None if (o is None or math.isnan(o) or math.isinf(o)) else float(f"{float(o):.6g}")
    if isinstance(o, (pd.Timestamp, pd.Period)):
        return str(o)[:10]
    if isinstance(o, np.bool_):
        return bool(o)
    return o


def _sum(df):
    return {k: float(df[k].sum()) for k in METRICS}


def _eur_chf(r) -> float:
    """Average CHF per EUR over the baseline year (exchange_rates.csv), for the Grid page's wholesale prices."""
    fx = r["fx"]
    return float(fx[(fx.month >= BASELINE_START) & (fx.month <= BASELINE_END)].eur_chf.mean())


def _group(df, by, top=None):
    g = df.groupby(by, dropna=False)[METRICS].sum().reset_index().sort_values("cost_chf", ascending=False)
    if top:
        g = g.head(top)
    return g.to_dict("records")


def _by_resource(bl: pd.DataFrame) -> list[dict]:
    """One row per resource (+ source). Quantity only where the unit is uniform."""
    keys = ["category", "resource_id", "tool", "department", "region", "source"]
    rows = bl[~bl.adjustment]
    g = rows.groupby(keys, dropna=False).agg(**{k: (k, "sum") for k in METRICS}, quantity=("quantity", "sum"),
                                             unit=("unit", lambda s: s.dropna().iloc[0] if s.notna().any() else ""),
                                             n_units=("unit", "nunique")).reset_index()
    adj = bl[bl.adjustment].groupby("resource_id")[METRICS].sum()
    for rid, a in adj.iterrows():   # attach one-off normalisation to its resource
        i = g.index[g.resource_id == rid]
        if len(i):
            g.loc[i[0], METRICS] = g.loc[i[0], METRICS] + a.values
    g.loc[g.n_units > 1, ["quantity", "unit"]] = [0, "mixed"]
    g["tool"] = g["tool"].where(g.source != "saas_contracts.csv",
                                g.resource_id.map({"saas-m365": "Microsoft 365", "saas-other": "15 other SaaS contracts"}))
    g = g.groupby(keys, dropna=False).agg({**{k: "sum" for k in METRICS}, "quantity": "sum", "unit": "first"}).reset_index()
    return g.drop(columns=[]).sort_values("cost_chf", ascending=False).to_dict("records")


def _allocated_departments(bl: pd.DataFrame) -> list[dict]:
    """Shared 'Overhead' rows split by FTE share (headcount.csv), else kept as 'Overhead'."""
    hc = load.headcount()
    is_shared = bl.department.isin(["Overhead"]) | bl.department.isna() | bl.resource_id.isin(F.SHARED_SERVICES)
    direct = bl[~is_shared]
    shared = bl[is_shared]
    out = direct.groupby("department")[METRICS].sum()
    if hc is not None:
        h = hc[(hc.month >= BASELINE_START) & (hc.month <= BASELINE_END)].groupby("department").fte.mean()
        share = h / h.sum()
        tot = shared[METRICS].sum()
        for d, s in share.items():
            add = tot * s
            out.loc[d] = out.loc[d] + add if d in out.index else add
    else:
        out.loc["Overhead"] = shared[METRICS].sum()
    return out.reset_index().rename(columns={"index": "department"}).sort_values("cost_chf", ascending=False).to_dict("records")


def findings(r: dict, bl: pd.DataFrame) -> list[dict]:
    from .measures import _bl
    out = []
    dp = _bl(load.data_platform(load.DQLog()))
    cal = load.calendar()
    for rid, mid in (("dp-prod", "M1"), ("dp-dev", "M2")):
        d = dp[dp.resource_id == rid].merge(cal, on="date")
        wk = d.groupby(d.date.dt.to_period("W").dt.start_time).agg(runtime=("runtime_h", "sum"),
                                                                    active=("active_use_h", "sum"), n=("date", "count"))
        wk = wk[wk.n == 7]  # complete weeks only
        cost = bl[bl.resource_id == rid].cost_chf.sum()
        out.append({
            "id": f"F-{rid}", "title": f"{'Production' if rid == 'dp-prod' else 'Development'} platform runs 24/7, "
                                       f"works {d.active_use_h.sum() / d.runtime_h.sum():.0%} of the time",
            "resource_id": rid, "measure": mid, "cost_chf": cost,
            "co2_kg": bl[bl.resource_id == rid].co2_mid_consumption.sum(),
            "kpi": f"{d.active_use_h.mean():.1f} active h/day of 24",
            "detail": f"Working days: {d[d.workday == 1].active_use_h.mean():.1f} active h; weekends: "
                      f"{d[d.workday == 0].active_use_h.mean():.1f} h. Source: data_platform_usage.csv",
            "series": {"labels": [str(x)[:10] for x in wk.index], "a": wk.runtime.round(1).tolist(),
                       "b": wk.active.round(1).tolist(), "a_label": "running h/week", "b_label": "working h/week"},
        })
    met = r["metrics"]
    g = met[(met.server_id == "gpu-ml-01") & (met.week_start >= BASELINE_START) &
            (met.week_start <= BASELINE_END - pd.Timedelta(days=6))].sort_values("week_start")
    out.append({
        "id": "F-gpu", "title": "GPU server on 24/7 in Frankfurt at 9 % utilisation", "resource_id": "gpu-ml",
        "measure": "M4", "cost_chf": bl[bl.resource_id == "gpu-ml"].cost_chf.sum(),
        "co2_kg": bl[bl.resource_id == "gpu-ml"].co2_mid_consumption.sum(),
        "kpi": f"{g.gpu_avg_pct.mean():.1f} % GPU, 168 h/week",
        "detail": "Peaks of ~43 % only in the weeks of the quarterly training (T-1101). Source: server_metrics_weekly.csv",
        "series": {"labels": [str(x)[:10] for x in g.week_start], "a": g.gpu_avg_pct.round(1).tolist(),
                   "a_label": "GPU utilisation %"},
    })
    aw = r["aws"]
    vt = aw[aw.resource_id == "vm-test"].groupby(aw.date.dt.to_period("M")).quantity.mean() / 24
    out.append({
        "id": "F-test", "title": "Test environment never scaled back after the portal go-live", "resource_id": "vm-test",
        "measure": "M5", "cost_chf": bl[bl.resource_id == "vm-test"].cost_chf.sum(),
        "co2_kg": bl[bl.resource_id == "vm-test"].co2_mid_consumption.sum(), "kpi": "64 vCPU instead of 16",
        "detail": "T-1058 (Apr 2025): 'scale-back planned after go-live'. Three servers without login since 2024/25 "
                  "(poc-ki-2024, migration-alt, build-agent-old). Source: aws_costs.csv, server_inventory.csv",
        "series": {"labels": [str(x) for x in vt.index], "a": vt.round(0).tolist(), "a_label": "vCPU running"},
    })
    sub = r["subs"]
    s = sub.groupby(["month", "product"]).agg(p=("licences_purchased", "sum"), a=("licences_active_30d", "sum")).reset_index()
    last = s[s.month == s.month.max()]
    out.append({
        "id": "F-seats", "title": f"{int((last.p - last.a).sum())} AI seats paid but unused (Aug 2026)",
        "resource_id": "sub-*", "measure": "M7",
        "cost_chf": bl[bl.source == "ai_subscriptions.csv"].cost_chf.sum(), "co2_kg": 0,
        "kpi": "ChatGPT Team: 2 of 23 seats active",
        "detail": "Nine requests for ChatGPT seats were rejected because 'a subscription with the same benefit already "
                  "exists'. Source: ai_subscriptions.csv, it_tickets.csv",
        "bars": [{"label": p, "a": int(x.p), "b": int(x.a)} for p, x in last.set_index("product").iterrows()],
    })
    ai = _bl(r["ai"])
    tk = ai.groupby(["task_type", "model_class"]).cost_chf.sum().unstack(fill_value=0)
    out.append({
        "id": "F-ai", "title": "Simple AI tasks run on the most expensive models", "resource_id": "ai-*",
        "measure": "M9", "cost_chf": ai.cost_chf.sum(),
        "co2_kg": bl[bl.source == "ai_usage.csv"].co2_mid_consumption.sum(),
        "kpi": f"{tk.get('large', pd.Series(0)).sum() / tk.values.sum():.0%} of token spend on large models",
        "detail": "Marketing classification on Claude Sonnet with 0 % caching; translations and summaries on GPT-5.4. "
                  "March 2026: endless loop (T-1212) tripled the monthly bill. Source: ai_usage.csv",
        "bars": [{"label": t, "a": float(x.get("large", 0) + x.get("small", 0)), "b": float(x.get("small", 0))}
                 for t, x in tk.iterrows()],
        "bars_labels": ["total CHF/yr", "of which on small models"],
    })
    sa = r["saas"]
    lastm = sa[sa.month == sa.month.max()].groupby("contract").agg(p=("licences_purchased", "sum"),
                                                                   a=("licences_active_30d", "sum"))
    lastm["u"] = lastm.a / lastm.p
    out.append({
        "id": "F-saas", "title": "SaaS licences: 11 of 16 contracts under 80 % used", "resource_id": "saas-other",
        "measure": "M8", "cost_chf": bl[bl.source == "saas_contracts.csv"].cost_chf.sum(), "co2_kg": 0,
        "kpi": f"Survey tool {lastm.u.get('Survey tool', 0):.0%}, E-signature {lastm.u.get('E-signature', 0):.0%}",
        "detail": "Utilisation = active in last 30 days / purchased (Aug 2026, Final rows). Source: saas_contracts.csv",
        "bars": [{"label": c, "a": int(x.p), "b": int(x.a)} for c, x in lastm.sort_values("u").iterrows()],
        "bars_labels": ["purchased", "active"],
    })
    return out


def bonus_findings(bl: pd.DataFrame, ci: dict | None, cat: dict | None, bk: dict | None) -> list[dict]:
    out = []
    res = lambda rid, k: float(bl[bl.resource_id == rid][k].sum())  # noqa: E731
    if ci:
        out.append({
            "id": "F-ci", "title": f"{ci['idle_nightly']} nightly builds ran with no new commits",
            "resource_id": "cicd", "measure": "B4", "cost_chf": res("cicd", "cost_chf"),
            "co2_kg": res("cicd", "co2_mid_consumption"),
            "kpi": f"{ci['reruns']:,} full re-runs, {ci['errors']:,} failed runs",
            "detail": f"All {ci['runs']:,} pipeline runs use Dublin runners. Idle nightly builds and full re-runs are "
                      f"{(ci['idle_nightly_cpu_h'] + ci['rerun_cpu_h']) / ci['cpu_h']:.0%} of CPU hours. "
                      "Source: extra/ci_pipeline_runs.jsonl, aws_costs.csv",
            "bars": [{"label": x["label"], "a": x["a"], "b": x["b"]} for x in ci["by_pipeline"]],
            "bars_labels": ["CPU-h per year", "of which idle nightly or re-run"],
        })
    if cat:
        out.append({
            "id": "F-catalog", "title": f"{cat['stale']} data tables not read for over a year",
            "resource_id": "dp-storage", "measure": "B5", "cost_chf": res("dp-storage", "cost_chf"),
            "co2_kg": res("dp-storage", "co2_mid_consumption"),
            "kpi": f"{cat['stale_tb']:.1f} of {cat['size_tb']:.1f} TB stale",
            "detail": f"{cat['unclear_retention']} of them have an empty retention flag, so a human decides. "
                      "Source: extra/data_catalog_tables.csv",
            "bars": cat["bars"], "bars_labels": ["GB in schema", "of which stale"],
        })
    if bk:
        out.append({
            "id": "F-backup", "title": f"{bk['triple']} data sources are backed up three times",
            "resource_id": "st-backup", "measure": None, "cost_chf": res("st-backup", "cost_chf"),
            "co2_kg": res("st-backup", "co2_mid_consumption"),
            "kpi": f"{bk['extra_tb']:.1f} TB in 2nd/3rd chains",
            "detail": f"{bk['no_restore_test_12m']} chains without a restore test in the last 12 months. 10-year "
                      "retention applies (W6), so consolidating is handed to a human (X3). Source: extra/backup_chains.csv",
            "bars": bk["bars"], "bars_labels": ["GB in all chains", "largest single chain"],
        })
    return out


def _finetune_summary() -> dict | None:
    """Result of `greenledger finetune` (models/chat-lora/metrics.json), shown in the app; None if never run."""
    p = CHAT_ADAPTER_DIR / "metrics.json"
    if not p.exists():
        return None
    m = json.loads(p.read_text(encoding="utf-8"))
    keys = ("exact_number_accuracy", "citation_rate", "abstention_rate", "refusal_rate_model_only", "score", "n")
    tr = m.get("training", {})
    return {"base_model": m.get("base_model"), "method": m.get("method"), "kept": m.get("kept"),
            "reason": m.get("reason"), "base": {k: m["base"].get(k) for k in keys},
            "fine_tuned": {k: m["fine_tuned"].get(k) for k in keys}, "energy": m.get("energy"),
            "examples": tr.get("examples"), "steps": tr.get("steps"), "epochs": tr.get("epochs"),
            "data": m.get("data"), "gpu": m.get("gpu"),
            "samples": [{"q": a["q"], "base": a["out"], "tuned": b["out"]}
                        for a, b in zip(m["examples"]["base"], m["examples"]["fine_tuned"])][:6]}


def build_all() -> dict:
    log = load.DQLog()
    r = ledger.build(log)
    led = r["ledger"]
    bl_all = led[(led.month >= "2025-09") & (led.month <= "2026-08")]
    bl = bl_all  # normalised baseline = actual + adjustment rows
    actual = bl_all[~bl_all.adjustment]
    ms = measures.build(r, led)
    ci_info, b4 = bonus.ci_analysis(r, led, log)
    cat_info, b5 = bonus.catalog(led)
    ms["measures"] += [m for m in (b4, b5) if m is not None]
    mlist = [m.to_dict() for m in ms["measures"]]
    for m in mlist:
        m["responsible"] = bonus.responsible(m["resource"], r["mapping"])
        m["short"] = measures.SHORT.get(m["id"], m["title"])
    win = limits.windows(r)
    checks = limits.check_measures(r)
    con = limits.contradictions(r)
    web = bonus.web_traffic(log)
    if web:
        con.append({k: web[k] for k in ("topic", "a", "b", "trusted", "impact")})
    bonus.m365_units(log)
    inj = limits.detect_injections(r)
    m4 = next(m for m in mlist if m["id"] == "M4")
    led_months = led[~led.adjustment].groupby(["month", "category"])[METRICS].sum().reset_index()
    bk = bonus.backups()
    fc = forecast.build(r, led, mlist)
    ml_res = ml.train(r, force=False)          # retrains only if data or ML code changed; skipped without `ml` group
    ml_view = None
    if ml_res:
        ml_view = {"classifier": ml_res["classifier"], "forecaster": ml_res["forecaster"],
                   "forecast_total": ml.combine_forecast(ml_res, fc), "seed": ml_res["seed"],
                   "train_seconds": ml_res.get("train_seconds")}
    tok = OWN_AI_TOKENS_M
    own_kwh = {s: tok[i] * 1000 * F.KWH_PER_1000_TOKENS_LARGE.mid for i, s in enumerate(("low", "high"))}

    data = {
        "meta": {
            "title": "Kilowise", "company": COMPANY, "source": "workspace" if WORKSPACE else "sample",
            "baseline": f"{BASELINE_START:%Y-%m-%d} to {BASELINE_END:%Y-%m-%d}", "data_as_of": f"{DATA_AS_OF:%Y-%m-%d}",
            "targets": {"co2": TARGET_CO2, "cost": TARGET_COST, "budget_pd": BUDGET_PERSON_DAYS,
                        "pd_chf": PERSON_DAY_CHF},
            "own_ai_use": {
                "tokens_m": list(tok), "kwh": [own_kwh["low"], own_kwh["high"]],
                "co2_kg": [own_kwh["low"] * F.GRID["EU"].mid, own_kwh["high"] * F.GRID["EU"].mid],
                "note": f"Built with an AI coding assistant: about {tok[0]}-{tok[1]} million tokens x "
                        f"{F.KWH_PER_1000_TOKENS_LARGE.mid * 1000} Wh per 1,000 tokens (range "
                        f"{F.KWH_PER_1000_TOKENS_LARGE.low * 1000}-{F.KWH_PER_1000_TOKENS_LARGE.high * 1000}) x EU mix "
                        f"{F.GRID['EU'].mid} kg/kWh."},
        },
        "baseline": {"normalised": _sum(bl), "actual": _sum(actual),
                     "adjustments": bl_all[bl_all.adjustment][["source", "resource_id", "cost_chf"]].to_dict("records")},
        "by_category": _group(bl, "category"),
        "by_department_direct": _group(bl, "department"),
        "by_department_allocated": _allocated_departments(bl),
        "by_resource": _by_resource(bl),
        "by_region": _group(bl, "grid_key"),
        "dept_category": bl.groupby(["department", "category"])["cost_chf"].sum().reset_index().to_dict("records"),
        "monthly": led_months.to_dict("records"),
        # same, with the one-off normalisation rows (T-1212, T-1189) netted in their month: sums to the normalised baseline
        "monthly_normalised": led.groupby(["month", "category"])[METRICS].sum().reset_index().to_dict("records"),
        "findings": findings(r, bl) + bonus_findings(bl, ci_info, cat_info, bk),
        "measures": mlist,
        "not_recommended": measures.NOT_RECOMMENDED,
        "windows": win, "contradictions": con, "injections": inj, "rule_checks": checks,
        "forecast": fc, "ml": ml_view, "clusters": cluster.servers(r), "shifting": shifting.build(),
        "ci": ci_info, "catalog": cat_info, "backups": bk,
        "notice_calendar": bonus.notice_calendar(r), "bonus_files": bonus.coverage(),
        "allocation_keys": bonus.project_hours_share(),
        "dq": log.frame().to_dict("records"),
        "factors": [{"key": f.key, "low": f.low, "mid": f.mid, "high": f.high, "unit": f.unit, "source": f.source,
                     "note": f.note} for f in F.ALL_FACTORS],
        "answers": [answers.q1_idle_seats(r), answers.q2_gpu(r, m4), answers.q3_prod(win)],
        "ai_models": ai_models.build(r),   # Models page: catalogue, workload, price check
        "grid": grid.build(_group(bl, "grid_key"), _eur_chf(r)),   # Grid page: European grids (Ember), optional files
        "saas_detail": ms["saas_detail"].to_dict("records"),
    }
    data["inputs"] = inputs.status(RAW, data["dq"])   # which exports were read, their format check and cleaning
    data["sources"] = sources.build(data)              # Sources page: inputs, factors and references
    data["connectors"] = connectors.catalog()            # Data sources: accounts that can be connected (no machine state)
    ft = _finetune_summary()
    if ft:
        data["meta"]["own_ai_use"]["finetune"] = ft["energy"]
    data = _clean(data)
    data["chat"] = _clean({**rag.build_index(data), "finetune": ft})   # RAG index always in sync with the numbers

    PROCESSED.mkdir(parents=True, exist_ok=True)
    OUTPUTS.mkdir(parents=True, exist_ok=True)
    led.to_csv(PROCESSED / "ledger_monthly.csv", index=False)
    (PROCESSED / "app_data.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    APP_DATA.mkdir(parents=True, exist_ok=True)
    (APP_DATA / "data.js").write_text("window.GL_DATA = " + json.dumps(data, ensure_ascii=False) + ";\n", encoding="utf-8")
    write_templates(data, mlist)
    dl = APP_DATA / "downloads"
    dl.mkdir(exist_ok=True)
    import shutil
    for f in ("template_baseline_and_assumptions.csv", "template_measures_package.csv"):
        shutil.copy(OUTPUTS / f, dl / f)
    shutil.copy(PROCESSED / "ledger_monthly.csv", dl / "ledger_monthly.csv")
    inputs.write_templates(dl / "inputs")         # empty column templates for another company's exports
    if not WORKSPACE:
        stamp_index()
    return data


def stamp_index() -> None:
    """Version the app's file links (app.css?v=..) by content hash, so a browser never shows an old copy after a change."""
    import hashlib
    import re
    from .config import APP
    idx = APP / "index.html"
    if not idx.exists():
        return
    html = idx.read_text(encoding="utf-8")

    def ver(m):
        f = APP / m.group(2)
        h = hashlib.sha1(f.read_bytes()).hexdigest()[:10] if f.exists() else "0"
        return f'{m.group(1)}="{m.group(2)}?v={h}"'
    new = re.sub(r'(href|src)="(app\.css|app\.js|data\.js)(?:\?v=[0-9a-f]+)?"', ver, html)
    if new != html:
        idx.write_text(new, encoding="utf-8")


# ------------------------------------------------------------------------------------------
def rule_txt(mid: str, checks: list[dict]) -> str:
    c = next((x for x in checks if x["measure"] == mid), None)
    if not c:
        return ""
    n = sum(x["checked"] for x in c["checks"] if x["kind"] == "protected")
    return f"Rule engine: schedule checked against {n:,} protected job runs/days, {c['conflicts']} conflicts. "


def write_templates(data: dict, mlist: list[dict]) -> None:
    b = data["baseline"]["normalised"]
    pd_ = PERSON_DAY_CHF
    on = [m for m in mlist if m["default_on"]]
    sav_c = sum(m["cost"]["mid"] for m in on)
    sav_co2 = sum(m["co2"]["mid_consumption"] for m in on)

    def v(x, d=6):
        return "" if x is None else (f"{x:.{d}g}" if isinstance(x, float) else x)

    vcpu = {s: F.vcpu_kw("Azure", 30, 2.0, s) for s in SCENARIOS}
    node = {s: 16 * F.vcpu_kw("Azure", 35, 4.0, s) for s in SCENARIOS}
    gpu = {s: F.gpu_kw(9.0, s) for s in SCENARIOS}
    rows = [
        ["total_cost_baseline_year_chf", "Must", "", round(b["cost_chf"]), "", "CHF per year",
         "azure_costs.csv, aws_costs.csv, hoster_invoice.csv, ai_usage.csv, ai_subscriptions.csv, saas_contracts.csv; "
         "exchange_rates.csv (data as of 2026-09-06)",
         f"Sum Sep 2025-Aug 2026 after cleaning (duplicates removed, Draft rows dropped, missing costs = qty x median unit "
         f"price, sandbox test account excluded). Normalised: one-off endless-loop AI bug (T-1212) and migration egress "
         f"(T-1189) removed (actual incl. one-offs: CHF {data['baseline']['actual']['cost_chf']:,.0f}). "
         "AI invoice is 5.9 % above the gateway (see contradictions)."],
        ["total_energy_baseline_year_kwh", "Must", round(b["kwh_low"]), round(b["kwh_mid"]), round(b["kwh_high"]),
         "kWh per year", "Own model, factors below", "Per row: quantity x energy factor (CCF linear CPU model with "
         "utilisation from the data, GPU model, storage, network, tokens, messages, active SaaS users) x PUE."],
        ["total_co2_location_based_baseline_year_kg", "Must", round(b["co2_low_consumption"]),
         round(b["co2_mid_consumption"]), round(b["co2_high_consumption"]), "kg CO2 per year",
         "Grid factors below", f"kWh x grid mix at the data-centre location (Zurich: consumption mix; with production "
         f"mix: {b['co2_mid_production']:,.0f} kg). AI and SaaS: EU mix."],
        ["total_co2_market_based_baseline_year_kg", "Bonus", round(b["co2_low_market"]), round(b["co2_mid_market"]),
         round(b["co2_high_market"]), "kg CO2 per year", F.MARKET.source + "; " + F.MARKET_RESIDUAL.source,
         "Same kWh as above x market-based factor: Zurich (hoster, Azure, AWS) Swiss supplier mix, all Swiss "
         "consumption is covered by guarantees of origin (hoster confirmed in T-1030/T-1181/T-1203/T-1227); "
         "Frankfurt, Dublin, AI and SaaS: European residual mix, because the data holds no certificate for our "
         "consumption there (GHG Protocol Scope 2). low = providers' renewable-matching claims accepted (0). "
         "Shown for information; targets are location-based."],
    ]
    for key, gk in (("grid_mix_location_based_switzerland", "CH_consumption"), ("grid_mix_location_based_germany", "DE"),
                    ("grid_mix_location_based_ireland", "IE")):
        f = F.GRID[gk]
        note = f.note + (f" Alternative production mix: {F.GRID['CH_production'].mid} kg/kWh "
                         f"({F.GRID['CH_production'].source})." if gk == "CH_consumption" else "")
        rows.append([key, "Must", f.low, f.mid, f.high, "kg CO2 per kWh", f.source, note])
    rows.append(["grid_mix_market_based", "Bonus", F.MARKET.low, F.MARKET.mid, F.MARKET.high, "kg CO2 per kWh",
                 F.MARKET.source, F.MARKET.note + f" Outside Switzerland: residual mix {F.MARKET_RESIDUAL.low}/"
                 f"{F.MARKET_RESIDUAL.mid}/{F.MARKET_RESIDUAL.high} ({F.MARKET_RESIDUAL.source})."])
    rows += [
        ["energy_per_vcpu_hour", "Must", v(vcpu["low"]), v(vcpu["mid"]), v(vcpu["high"]), "kWh", F.CCF_SOURCE,
         "At 30 % CPU incl. 2 GB RAM per vCPU, excl. PUE: (0.78 + 0.3 x (3.76-0.78) + 2 x 0.392) W x overhead "
         "(1.0 / 1.5 / 2.5). The pipeline uses the actual daily CPU % per resource."],
        ["energy_per_node_hour", "Must", v(node["low"]), v(node["mid"]), v(node["high"]), "kWh", F.CCF_SOURCE,
         "Node = 16 vCPU + 64 GB (data dictionary), at 35 % CPU, excl. PUE. Pipeline uses daily AvgCpuPercent."],
        ["energy_per_gpu_hour", "Must", v(gpu["low"]), v(gpu["mid"]), v(gpu["high"]), "kWh",
         F.GPU_IDLE_W.source + "; " + F.CCF_SOURCE,
         "At the observed 9 % GPU utilisation: idle W + 9 % x (300 W - idle) + host 8 vCPU/56 GB, excl. PUE. "
         "At full load: about 0.33-0.37 kWh."],
        ["energy_per_gb_storage_day", "Must", v(F.STORAGE_KWH_PER_GB_DAY.low), v(F.STORAGE_KWH_PER_GB_DAY.mid),
         v(F.STORAGE_KWH_PER_GB_DAY.high), "kWh", F.STORAGE_KWH_PER_GB_DAY.source, F.STORAGE_KWH_PER_GB_DAY.note],
        ["energy_per_1000_tokens", "Must", v(F.KWH_PER_1000_TOKENS_LARGE.low), v(F.KWH_PER_1000_TOKENS_LARGE.mid),
         v(F.KWH_PER_1000_TOKENS_LARGE.high), "kWh", F.KWH_PER_1000_TOKENS_LARGE.source,
         F.KWH_PER_1000_TOKENS_LARGE.note + f" Small models: x {F.SMALL_MODEL_SHARE.mid} "
                                            f"({F.SMALL_MODEL_SHARE.low}-{F.SMALL_MODEL_SHARE.high})."],
        ["energy_per_subscription_message", "Must", v(F.KWH_PER_SUBSCRIPTION_MESSAGE.low),
         v(F.KWH_PER_SUBSCRIPTION_MESSAGE.mid), v(F.KWH_PER_SUBSCRIPTION_MESSAGE.high), "kWh",
         F.KWH_PER_SUBSCRIPTION_MESSAGE.source, F.KWH_PER_SUBSCRIPTION_MESSAGE.note],
        ["pue", "Must", F.PUE["Azure"].low, F.PUE["Azure"].mid, 1.56, "ratio",
         F.PUE["Azure"].source + "; " + F.PUE["Hoster"].source,
         "Applied per provider: Azure 1.185, AWS 1.135, Swiss hoster 1.4 (mid). Provider figures are design/fleet "
         "averages and not audited per region, so the high end uses the Uptime industry average. AI per-token factor "
         "already includes datacentre overhead."],
        ["growth_per_year", "Bonus", *[round(data["forecast"]["growth_per_year"][s] * 100, 1) for s in SCENARIOS],
         "percent", "; ".join(f"{d['driver']}: {d['source']}" for d in data["forecast"]["drivers"][:7]),
         "Cost growth per year without the package (CAGR over 3 years), built bottom-up: " +
         "; ".join(f"{d['driver']} {d['value']} ({d['applies_to']})" for d in data["forecast"]["drivers"]) +
         f". Forecast {data['forecast']['years'][-1]} mid: CHF "
         f"{data['forecast']['series']['cost']['without_mid'][-1]:,.0f} without vs "
         f"{data['forecast']['series']['cost']['with_mid'][-1]:,.0f} with the package."],
        ["allocation_rule_shared_costs", "Must", "", F.ALLOCATION_RULE, "", "text", "headcount.csv, "
         "project_hours_monthly.csv, mapping_departments_tools.csv", "FTE share = average FTE per department Sep 2025-Aug 2026."],
    ]
    cols = ["parameter", "must_or_bonus", "value_low", "value_mid", "value_high", "unit", "source",
            "calculation_or_assumption"]
    pd.DataFrame(rows, columns=cols).to_csv(OUTPUTS / "template_baseline_and_assumptions.csv", index=False,
                                            encoding="utf-8-sig")

    mrows = []
    for m in on:
        win_txt = "; ".join(f"{w['id']} {w['name']} ({w['when']})" for w in data["windows"] if w["id"] in m["windows"])
        mrows.append({
            "measure_id": m["id"], "description": m["description"], "resource_or_source": m["resource"],
            "change": m["change"], "effort_person_days": m["effort_pd"],
            "savings_cost_chf_per_year": round(m["cost"]["mid"]),
            "savings_energy_kwh_per_year": round(m["kwh"]["mid"]),
            "savings_co2_kg_location_based": round(m["co2"]["mid_consumption"]),
            "savings_co2_kg_market_based": round(m["co2"]["mid_market"]),
            "risks_and_exceptions": (f"Protection windows respected: {win_txt}. " if win_txt else "")
                                    + rule_txt(m["id"], data["rule_checks"]) + m["risks"]
                                    + f" Decision by: {m['owner']}"
                                    + (" (responsible per mapping: " + ", ".join(sorted({x['role'] for x in m['responsible']}))
                                       + ")" if m.get("responsible") else "") + ".",
            "assumptions_and_sources": m["assumptions"] + (
                f" Ranges: CHF {m['cost']['low']:,.0f}-{m['cost']['high']:,.0f}; "
                f"kg CO2 {m['co2']['low_consumption']:,.0f}-{m['co2']['high_consumption']:,.0f} (low/high factors)."),
        })
    pd.DataFrame(mrows).to_csv(OUTPUTS / "template_measures_package.csv", index=False, encoding="utf-8-sig")
    eff = sum(m["effort_pd"] for m in on)
    (OUTPUTS / "package_summary.txt").write_text(
        f"Package: {len(on)} measures, {eff} person-days = CHF {eff * pd_:,.0f} (budget CHF {BUDGET_PERSON_DAYS * pd_:,.0f})\n"
        f"Cost: CHF {sav_c:,.0f} of {b['cost_chf']:,.0f} = {sav_c / b['cost_chf']:.1%} (target {TARGET_COST:.0%})\n"
        f"CO2 location-based (mid, CH consumption mix): {sav_co2:,.0f} of {b['co2_mid_consumption']:,.0f} kg "
        f"= {sav_co2 / b['co2_mid_consumption']:.1%} (target {TARGET_CO2:.0%})\n", encoding="utf-8")
