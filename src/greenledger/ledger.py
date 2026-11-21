"""Connect: one ledger for cloud, servers, AI and SaaS with cost, energy and CO2 (location-based).

Output grain: month x resource (x department for AI and SaaS). Every row carries
cost_chf, kwh_{low,mid,high} and co2_{low,mid,high}_{consumption,production} (kg).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import factors as F
from . import load
from .config import CH_MIX_VARIANTS, SCENARIOS

CC_DEPT = {4000: "Consulting", 4100: "Sales", 4200: "Finance", 4300: "Marketing", 4400: "HR",
           4500: "IT", 4900: "Management", 9000: "Overhead", 9100: "Test account"}

CATEGORY = {
    "vm-app": "Servers", "vm-test": "Servers", "db-fin": "Servers", "gpu-ml": "Servers",
}


def _category(resource_id: str, source: str) -> str:
    if source in ("ai_usage.csv", "ai_subscriptions.csv"):
        return "AI"
    if source == "saas_contracts.csv":
        return "SaaS"
    return CATEGORY.get(resource_id, "Cloud")


def _vcpu_kw_vec(provider: str, util_pct, mem_gb_per_vcpu: float, scen: str):
    """Vectorised factors.vcpu_kw (same formula, same operation order), for one provider."""
    wmin, wmax = F.CCF_WATTS.get(provider, F.CCF_WATTS["Azure"])
    u = np.clip(np.asarray(util_pct, dtype=float) / 100.0, 0.0, 1.0)
    w = wmin + u * (wmax - wmin) + mem_gb_per_vcpu * F.MEM_W_PER_GB
    return w * F.SERVER_OVERHEAD.get(scen) / 1000.0


def _energy_azure_aws(df: pd.DataFrame, gpu_util: pd.Series, scen: str) -> pd.Series:
    """kWh per row incl. PUE (vectorised; one pass per provider)."""
    out = pd.Series(0.0, index=df.index)
    unit = df["unit"].to_numpy()
    q_all = df["quantity"].to_numpy(dtype=float)
    cpu_all = df["cpu_pct"].fillna(30.0).to_numpy(dtype=float)
    # GPU rows: utilisation of the week the row falls in (Monday), 9 % if that week is not monitored
    d = df["date"]
    wk = (d - pd.to_timedelta(d.dt.day_of_week, unit="D")).dt.normalize()
    util = pd.Series(np.where(wk.isin(gpu_util.index), wk.map(gpu_util), 9.0), index=df.index)
    gpu_kw = util.map(lambda u: F.gpu_kw(u, scen)).to_numpy(dtype=float)
    for prov in df["provider"].unique():
        m = (df["provider"] == prov).to_numpy()
        q, cpu, un = q_all[m], cpu_all[m], unit[m]
        kwh = np.select(
            [un == "vCPU-hour", un == "vCore-hour", un == "node-hour", un == "GPU-hour",
             un == "capacity-day",  # Power BI capacity: assumption 8 v-cores, 25 GB (F64/P1 class)
             un == "GB-day", un == "GB",
             un == "runner-minute"],  # assumption: 2 vCPU runner at 50 % CPU
            [q * _vcpu_kw_vec(prov, cpu, 2.0, scen),
             q * _vcpu_kw_vec(prov, cpu, 5.1, scen),
             q * 16 * _vcpu_kw_vec(prov, cpu, 4.0, scen),
             q * gpu_kw[m],
             q * 24 * 8 * _vcpu_kw_vec(prov, 30.0, 3.1, scen),
             q * F.STORAGE_KWH_PER_GB_DAY.get(scen),
             q * F.NETWORK_KWH_PER_GB.get(scen),
             q / 60 * 2 * _vcpu_kw_vec(prov, 50.0, 4.0, scen)],
            default=0.0)  # 'month' (support fee) has no energy
        out[m] = kwh * F.PUE[prov].get(scen)
    return out


def _co2_columns(df: pd.DataFrame) -> pd.DataFrame:
    for scen in SCENARIOS:
        for mix in CH_MIX_VARIANTS:
            g = df["region"].map(lambda reg: F.grid(reg, scen, mix))
            df[f"co2_{scen}_{mix}"] = df[f"kwh_{scen}"] * g
    return df


def build(log: load.DQLog | None = None) -> dict:
    log = log or load.DQLog()
    fx = load.exchange_rates()
    mp = load.mapping().set_index("resource_id")
    inv, met = load.servers()
    gpu_util = met[met.server_id == "gpu-ml-01"].set_index("week_start")["gpu_avg_pct"]

    rows = []

    # ---- Azure + AWS + Hoster (daily rows) -------------------------------------------------
    az = load.azure(fx, log)
    aw = load.aws(fx, log)
    ho = load.hoster(log)
    cloud = pd.concat([
        az[["date", "resource_id", "service", "region", "quantity", "unit", "cost_chf", "cpu_pct", "provider",
            "source", "cost_imputed"]],
        aw[["date", "resource_id", "service", "region", "quantity", "unit", "cost_chf", "cpu_pct", "provider",
            "source", "cost_imputed"]],
        ho[["date", "resource_id", "service", "region", "quantity", "unit", "cost_chf", "provider", "source",
            "cost_imputed"]].assign(cpu_pct=np.nan),
    ], ignore_index=True)
    for scen in SCENARIOS:
        az_aws = cloud["provider"].isin(["Azure", "AWS"])
        cloud.loc[az_aws, f"kwh_{scen}"] = _energy_azure_aws(cloud[az_aws], gpu_util, scen)
        h = ~az_aws
        f_storage = F.STORAGE_KWH_PER_GB_DAY.get(scen)
        f_net = F.NETWORK_KWH_PER_GB.get(scen)
        cloud.loc[h, f"kwh_{scen}"] = np.where(cloud.loc[h, "unit"] == "GB-day", cloud.loc[h, "quantity"] * f_storage,
                                               cloud.loc[h, "quantity"] * f_net) * F.PUE["Hoster"].get(scen)
    cloud["month"] = cloud["date"].dt.to_period("M")
    cloud["tool"] = cloud["resource_id"].map(mp["tool"])
    cloud["department"] = cloud["resource_id"].map(mp["department"])
    cloud["cost_center"] = cloud["resource_id"].map(mp["cost_center"])
    agg = {"quantity": "sum", "cost_chf": "sum", **{f"kwh_{s}": "sum" for s in SCENARIOS},
           "cpu_pct": "mean", "cost_imputed": "sum"}
    cm = cloud.groupby(["month", "source", "provider", "resource_id", "tool", "department", "cost_center", "region",
                        "service", "unit"], dropna=False).agg(agg).reset_index()
    rows.append(cm)

    # ---- AI usage (gateway) ---------------------------------------------------------------
    ai = load.ai_usage(log)
    eff_tokens = (ai.tokens_in - ai.tokens_in_cache) + F.CACHE_WEIGHT * ai.tokens_in_cache + ai.tokens_out
    for scen in SCENARIOS:
        share = np.where(ai.model_class == "small", F.SMALL_MODEL_SHARE.get(scen), 1.0)
        ai[f"kwh_{scen}"] = eff_tokens / 1000 * F.KWH_PER_1000_TOKENS_LARGE.get(scen) * share
    ai["month"] = ai["date"].dt.to_period("M")
    ai["cost_center"] = ai["department"].map({v: k for k, v in CC_DEPT.items()})
    am = ai.groupby(["month", "resource_id", "tool", "department", "cost_center"]).agg(
        quantity=("requests", "sum"), cost_chf=("cost_chf", "sum"),
        **{f"kwh_{s}": (f"kwh_{s}", "sum") for s in SCENARIOS}).reset_index()
    am = am.assign(source="ai_usage.csv", provider="AI provider (API)", region="EU (mixed)", service="AI API",
                   unit="requests")
    rows.append(am)

    # ---- AI subscriptions ------------------------------------------------------------------
    sub = load.ai_subscriptions(fx, log)
    sub_rid = {"ChatGPT Team": "sub-chatgpt", "Microsoft Copilot": "sub-copilot", "Claude Team": "sub-claude"}
    for scen in SCENARIOS:
        sub[f"kwh_{scen}"] = sub["messages_30d"] * F.KWH_PER_SUBSCRIPTION_MESSAGE.get(scen)
    sm = pd.DataFrame({
        "month": sub["month"].dt.to_period("M"), "resource_id": sub["product"].map(sub_rid), "tool": sub["product"],
        "department": sub["cost_center"].map(CC_DEPT), "cost_center": sub["cost_center"],
        "quantity": sub["licences_purchased"], "cost_chf": sub["cost_chf"],
        **{f"kwh_{s}": sub[f"kwh_{s}"] for s in SCENARIOS},
    }).assign(source="ai_subscriptions.csv", provider="AI subscription", region="EU (mixed)",
              service="AI subscription", unit="seats")
    rows.append(sm)

    # ---- SaaS ------------------------------------------------------------------------------
    sa = load.saas(fx, log)
    for scen in SCENARIOS:
        sa[f"kwh_{scen}"] = sa["licences_active_30d"] * F.SAAS_KWH_PER_ACTIVE_USER_MONTH.get(scen)
    sam = pd.DataFrame({
        "month": sa["month"].dt.to_period("M"),
        "resource_id": np.where(sa["contract"].eq("Microsoft 365"), "saas-m365", "saas-other"),
        "tool": sa["contract"], "department": sa["cost_center"].map(CC_DEPT), "cost_center": sa["cost_center"],
        "quantity": sa["licences_purchased"], "cost_chf": sa["cost_chf"],
        **{f"kwh_{s}": sa[f"kwh_{s}"] for s in SCENARIOS},
    }).assign(source="saas_contracts.csv", provider="SaaS vendor", region="EU (mixed)", service="SaaS",
              unit="licences")
    rows.append(sam)

    led = pd.concat(rows, ignore_index=True)
    led["category"] = [_category(r, s) for r, s in zip(led.resource_id, led.source)]
    led["grid_key"] = led["region"].map(F.region_key)
    led = _co2_columns(led)
    led["adjustment"] = False

    # ---- One-off normalisation (shown, not hidden) ----------------------------------------
    adj = []
    # (1) ai-marketing endless loop, ticket T-1212 (2026-03-17..19): excess over March median day
    mk = ai[ai.resource_id == "ai-marketing"]
    daily = mk.groupby("date")[["cost_chf", *[f"kwh_{s}" for s in SCENARIOS]]].sum()
    march = daily[(daily.index >= "2026-03-01") & (daily.index <= "2026-03-31")]
    bug_days = march.loc["2026-03-17":"2026-03-19"]
    normal = march.drop(bug_days.index).median()
    excess = (bug_days - normal).sum()
    adj.append({"month": pd.Period("2026-03", "M"), "resource_id": "ai-marketing", "tool": "Marketing text analysis",
                "department": "Marketing", "cost_center": 4300, "source": "normalisation (T-1212)",
                "provider": "AI provider (API)", "region": "EU (mixed)", "service": "one-off excess removed",
                "unit": "", "quantity": 0, "cost_chf": -excess["cost_chf"],
                **{f"kwh_{s}": -excess[f"kwh_{s}"] for s in SCENARIOS}})
    log.add("ai_usage.csv", "endless-loop bug 2026-03-17..19 (ticket T-1212)", len(bug_days),
            f"excess CHF {excess['cost_chf']:.0f} removed from normalised baseline", "warn")
    # (2) one-off data egress migration, ticket T-1189 (January 2026)
    eg = cloud[cloud.resource_id == "net-egress"].set_index("date").sort_index()
    eg_daily = eg.groupby(level=0)[["cost_chf", "quantity", *[f"kwh_{s}" for s in SCENARIOS]]].sum()
    med = eg_daily["quantity"].median()
    spike = eg_daily[eg_daily["quantity"] > 4 * med]
    if len(spike):
        ex = (spike - eg_daily.median()).clip(lower=0).sum()
        adj.append({"month": spike.index[0].to_period("M"), "resource_id": "net-egress", "tool": "Data egress",
                    "department": "IT", "cost_center": 4500, "source": "normalisation (T-1189)", "provider": "AWS",
                    "region": "Switzerland (Zurich)", "service": "one-off excess removed", "unit": "", "quantity": 0,
                    "cost_chf": -ex["cost_chf"], **{f"kwh_{s}": -ex[f"kwh_{s}"] for s in SCENARIOS}})
        log.add("aws_costs.csv", "one-off migration egress (ticket T-1189)", len(spike),
                f"excess CHF {ex['cost_chf']:.0f} removed from normalised baseline", "warn")
    adjf = pd.DataFrame(adj)
    adjf["category"] = [_category(r, "x") if r != "ai-marketing" else "AI" for r in adjf.resource_id]
    adjf["grid_key"] = adjf["region"].map(F.region_key)
    adjf = _co2_columns(adjf)
    adjf["adjustment"] = True
    led = pd.concat([led, adjf], ignore_index=True)
    led["month"] = led["month"].astype(str)

    return {
        "ledger": led, "dq": log, "fx": fx, "azure": az, "aws": aw, "hoster": ho, "ai": ai, "subs": sub,
        "saas": sa, "inventory": inv, "metrics": met, "mapping": mp.reset_index(),
    }
