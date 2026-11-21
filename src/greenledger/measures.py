"""Decide: the package of measures with effort, savings in CHF, kWh and CO2 (location-based).

Each measure is computed from the data (no hard-coded savings). Schedules respect the
protection windows in limits.py. Ranges:
  * energy / CO2: low / mid / high factor scenarios (factors.py)
  * cost: conservative / expected / optimistic (cost_low / cost_mid / cost_high)
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd

from . import factors as F
from . import load
from .config import BASELINE_END, BASELINE_START, CH_MIX_VARIANTS, DATA_AS_OF, SCENARIOS
from .limits import on_hours, quarter_training_days, schedule_m1, schedule_m2


@dataclass
class Measure:
    id: str
    title: str
    description: str
    resource: str
    change: str
    effort_pd: float
    owner: str
    windows: list[str]
    risks: str
    assumptions: str
    category: str
    region: str
    cost: dict = field(default_factory=dict)      # low/mid/high CHF per year
    kwh: dict = field(default_factory=dict)       # low/mid/high kWh per year
    co2: dict = field(default_factory=dict)       # "<scen>_<mix>" -> kg per year
    requires: list[str] = field(default_factory=list)
    default_on: bool = True
    bonus: bool = False
    evidence: list[dict] = field(default_factory=list)  # {"kind": read|derived|assumed, "text": ...}
    decision: str = "recommend"  # recommend | human

    def to_dict(self):
        return asdict(self)


def _bl(df, col="date"):
    return df[(df[col] >= BASELINE_START) & (df[col] <= BASELINE_END)]


def _co2(kwh: dict, region: str) -> dict:
    return {f"{s}_{m}": kwh[s] * F.grid(region, s, m) for s in SCENARIOS for m in CH_MIX_VARIANTS}


def _unit_price(df, rid):
    d = _bl(df[df.resource_id == rid])
    return d.cost_chf.sum() / d.quantity.sum(), d


# ------------------------------------------------------------------------------------------
def m1_dp_prod(r, cal, jobs) -> Measure:
    dp = _bl(load.data_platform(load.DQLog()))
    prod = dp[dp.resource_id == "dp-prod"].merge(cal, on="date")
    sched = schedule_m1(cal, jobs)       # same schedule the rule engine checks against every job run
    prod["keep_h"] = prod.date.map(lambda d: on_hours(sched.get(d, [(0.0, 24.0)])))
    prod["saved_h"] = (prod.runtime_h - prod.keep_h).clip(lower=0)
    node_h = float((prod.node_count * prod.saved_h).sum())
    price, _ = _unit_price(r["azure"], "dp-prod")
    cost_mid = node_h * price
    kwh = {s: node_h * 16 * F.vcpu_kw("Azure", 5.0, 4.0, s) * F.PUE["Azure"].get(s) for s in SCENARIOS}
    share = prod.saved_h.sum() / prod.runtime_h.sum()
    return Measure(
        "M1", "Production platform: sleep outside its working windows",
        "Stop the dp-prod cluster when nobody and no fixed job needs it, and start it 30 min before the next window.",
        "dp-prod", "Auto-stop/auto-start schedule: working days on 01:30-20:00, weekends/holidays on 01:30-08:00; "
        "always on during the last 3 working days of the month and on working days in January, and from 00:00 the morning "
        "after such a day (month-end close runs until ~04:00, year-end close until ~02:00); "
        "ad-hoc queries auto-resume the cluster. From next month.",
        2.0, "Head of Consulting (owner) + Head of Finance (month-end/year-end)", ["W1", "W2", "W3"],
        "Evening ad-hoc analysis waits 5-10 min for auto-resume. Platform grows to 24 nodes from Oct 2026 (T-1261), "
        "which raises the saving. Must be approved by both heads before go-live; first month monitored daily.",
        f"{share:.0%} of runtime hours removed ({node_h:,.0f} node-h); price CHF {price:.3f}/node-h from azure_costs.csv; "
        "off-hours energy at 5 % CPU (CCF model, 16 vCPU + 64 GB per node). Conservative cost: 20 % of off-hours "
        "re-used via auto-resume.",
        "Cloud", "Switzerland (Zurich)",
        cost={"low": cost_mid * 0.8, "mid": cost_mid, "high": cost_mid},
        kwh=kwh, co2=_co2(kwh, "Switzerland (Zurich)"),
        evidence=[
            {"kind": "read", "text": f"Runs 24 h/day; active {prod[prod.workday == 1].active_use_h.mean():.1f} h on "
                                     f"working days, {prod[prod.workday == 0].active_use_h.mean():.1f} h on weekends"},
            {"kind": "derived", "text": f"{node_h:,.0f} node-hours/year outside all protection windows"},
            {"kind": "assumed", "text": "Off-hours load 5 % CPU; 20 % auto-resume in the conservative case"},
        ],
    )


def m2_dp_dev(r, cal, jobs) -> Measure:
    dp = _bl(load.data_platform(load.DQLog()))
    dev = dp[dp.resource_id == "dp-dev"].merge(cal, on="date")
    sched = schedule_m2(cal, jobs)       # W4 training 24 h; working days 08:00-18:00; weekend refresh 17:00-19:00
    dev["keep_h"] = dev.date.map(lambda d: on_hours(sched.get(d, [(0.0, 24.0)])))
    dev["saved_h"] = (dev.runtime_h - dev.keep_h).clip(lower=0)
    node_h = float((dev.node_count * dev.saved_h).sum())
    price, _ = _unit_price(r["azure"], "dp-dev")
    cost_mid = node_h * price
    kwh = {s: node_h * 16 * F.vcpu_kw("Azure", 5.0, 4.0, s) * F.PUE["Azure"].get(s) for s in SCENARIOS}
    return Measure(
        "M2", "Development cluster: auto-pause, auto-start for the training",
        "Pause dp-dev when idle and outside working hours, with an automatic start for the quarterly training.",
        "dp-dev", "Auto-termination after 30 min idle; schedule on working days 08:00-18:00; fully on days 1-3 of "
        "Jan/Apr/Jul/Oct (auto-start at 00:00, 'pre-heated' 30 min before). Move the flexible 'Test data refresh' "
        "from 17:00 to 16:00 so it ends inside the window (rule engine: 83 runs overran 18:00). From next month.",
        1.5, "Head of IT", ["W4"],
        "Developers wait a few minutes after a pause. The training start must be tested before the next quarter "
        "(1 January). Criticality 'low' in master data contradicts the training dependency: a human confirms.",
        f"{node_h:,.0f} node-h/year removed; price CHF {price:.3f}/node-h (EUR converted); "
        f"active use only {dev.active_use_h.sum() / dev.runtime_h.sum():.0%} of runtime.",
        "Cloud", "Germany (Frankfurt)",
        cost={"low": cost_mid * 0.8, "mid": cost_mid, "high": cost_mid},
        kwh=kwh, co2=_co2(kwh, "Germany (Frankfurt)"),
        evidence=[
            {"kind": "read", "text": f"Active {dev.active_use_h.sum() / dev.runtime_h.sum():.1%} of 24 h runtime"},
            {"kind": "read", "text": "T-1053: 'After that it can pause, as long as it starts automatically'"},
            {"kind": "derived", "text": f"{node_h:,.0f} node-hours/year outside working and training windows"},
        ],
    )


def m3_relocate(r, m2: Measure, base_kwh_dev: dict) -> Measure:
    pz, _ = _unit_price(r["azure"], "dp-prod")
    pf, dev = _unit_price(r["azure"], "dp-dev")
    remaining_node_h = dev.quantity.sum() * (1 - m2.cost["mid"] / (dev.cost_chf.sum()))
    cost_delta = remaining_node_h * (pf - pz)   # positive = saving
    remaining = {s: base_kwh_dev[s] - m2.kwh[s] for s in SCENARIOS}
    co2 = {f"{s}_{m}": remaining[s] * (F.grid("Germany", s, m) - F.grid("Switzerland", s, m))
           for s in SCENARIOS for m in CH_MIX_VARIANTS}
    return Measure(
        "M3", "Move the development cluster from Frankfurt to Zurich",
        "Re-create dp-dev in Azure Switzerland North next to dp-prod (ticket T-1074: technically possible).",
        "dp-dev", "Infrastructure-as-code redeploy in Zurich, copy dev data, switch endpoints; do it in May or "
        "June (outside the training window W4).",
        2.0, "Head of IT", ["W4"],
        "Migration risk (dev only, no production impact). Dev data stays in Switzerland (sovereignty plus). "
        "Do not migrate in the first week of a quarter.",
        f"CO2 = remaining dp-dev energy after M2 x (grid DE - grid CH). Price Zurich CHF {pz:.3f} vs Frankfurt "
        f"CHF {pf:.3f} per node-h (invoices): cost change CHF {cost_delta:,.0f}/year.",
        "Cloud", "Germany (Frankfurt) -> Switzerland (Zurich)",
        cost={"low": min(cost_delta, 0.0), "mid": cost_delta, "high": cost_delta},
        kwh={s: 0.0 for s in SCENARIOS}, co2=co2, requires=["M2"],
        evidence=[
            {"kind": "read", "text": "T-1074: Frankfurt only because it was cheaper; move is possible"},
            {"kind": "derived", "text": f"Invoices show ~equal price per node-hour (Δ {pf - pz:+.3f} CHF)"},
            {"kind": "assumed", "text": "Same node type available in Switzerland North at the dp-prod price"},
        ],
    )


def m4_gpu(r, cal) -> Measure:
    az = r["azure"]
    price, g = _unit_price(az, "gpu-ml")
    total_h = float(g.quantity.sum())
    qd = quarter_training_days(cal)
    train_h = 24 * len([d for d in qd if BASELINE_START <= d <= BASELINE_END])
    adhoc_h = 52 * (8 + 1)                       # one working day per week + 1 h pre-start
    keep_h = train_h + adhoc_h
    saved_h = max(total_h - keep_h, 0)
    met = r["metrics"]
    gm = _bl(met[met.server_id == "gpu-ml-01"], "week_start")
    idle_util = gm[gm.gpu_avg_pct < 20].gpu_avg_pct.mean()
    kwh = {s: saved_h * F.gpu_kw(idle_util, s) * F.PUE["Azure"].get(s) for s in SCENARIOS}
    cost_mid = saved_h * price
    return Measure(
        "M4", "GPU server only when needed",
        "Deallocate gpu-ml-01 by default and start it for the quarterly training and on request.",
        "gpu-ml", "Default state 'deallocated'; scheduled start 1 h before days 1-3 of Jan/Apr/Jul/Oct; self-service "
        "start button (max. 1 working day per week); auto-stop after 2 h idle. From next month.",
        1.0, "Head of Consulting", ["W4"],
        f"AI pilot P-004 ended 2025-06-30 and the last human login was {r['inventory'].set_index('server_id').loc['gpu-ml-01', 'last_login']:%Y-%m-%d}: "
        "ask the owner whether the server is still needed at all (would save the rest too).",
        f"{saved_h:,.0f} of {total_h:,.0f} GPU-h/year removed; kept {train_h} h training + {adhoc_h} h ad hoc; "
        f"price CHF {price:.2f}/GPU-h (EUR converted); idle GPU util {idle_util:.1f} %.",
        "Servers", "Germany (Frankfurt)",
        cost={"low": cost_mid * 0.9, "mid": cost_mid, "high": total_h * price - train_h * price},
        kwh=kwh, co2=_co2(kwh, "Germany (Frankfurt)"),
        evidence=[
            {"kind": "read", "text": f"GPU {gm.gpu_avg_pct.mean():.1f} % average, 168 h/week uptime"},
            {"kind": "read", "text": "~43 % GPU only in the 6 training weeks (T-1101)"},
            {"kind": "assumed", "text": f"Idle GPU {F.GPU_IDLE_W.mid:.0f} W of 300 W TDP (range {F.GPU_IDLE_W.low:.0f}-{F.GPU_IDLE_W.high:.0f} W)"},
        ],
    )


def _server_util(r):
    met = _bl(r["metrics"], "week_start")
    return met.groupby("server_id").cpu_avg_pct.mean()


KEEP_TEST = ["qa-regression-01", "uat-portal", "uat-shop"]


def m5_test_scale_back(r) -> Measure:
    inv = r["inventory"]
    aws_like = inv[(inv.provider == "AWS") & (inv.vcpu == 4)]
    keep = set(KEEP_TEST) | {"dr-failover"}
    removed = aws_like[~aws_like.server_id.isin(keep)]
    util = _server_util(r)
    vt = _bl(r["aws"][r["aws"].resource_id == "vm-test"])
    total_vcpu = vt.quantity.sum() / len(vt.date.unique()) / 24
    removed_vcpu = removed.vcpu.sum()
    cost_mid = vt.cost_chf.sum() * removed_vcpu / total_vcpu
    hours = 24 * 365

    def kwh_s(s):
        # removed servers: idle floor + memory disappears; their CPU work moves to the kept servers
        return sum(r_.vcpu * hours * F.vcpu_kw("AWS", 0.0, 2.0, s) for r_ in removed.itertuples()) * F.PUE["AWS"].get(s)

    kwh = {s: kwh_s(s) for s in SCENARIOS}
    zombies = removed[removed.server_id.isin(["poc-ki-2024", "migration-alt", "build-agent-old"])]
    return Measure(
        "M5", "Test environment: complete the planned scale-back",
        "Shrink vm-test from 64 to 16 vCPU as planned in T-1058 after the portal go-live, incl. 3 forgotten servers.",
        "vm-test", f"Keep {', '.join(KEEP_TEST)} and dr-failover; snapshot, then delete the other {len(removed)} servers "
        f"({', '.join(zombies.server_id)} have had no login since {zombies.last_login.max():%Y-%m}). "
        "Keep an IaC template to scale up again for release tests.",
        1.5, "Head of IT (+ project leads of P-001/P-002)", ["W5", "W8"],
        "dr-failover is explicitly excluded (W5). Release tests (W8) get a temporary scale-up by arrangement. "
        "Two zombie servers have no owner cost centre: a human confirms deletion after a 30-day snapshot.",
        f"{removed_vcpu:.0f} of {total_vcpu:.0f} vCPU removed (cost share from aws_costs.csv); energy: idle floor of removed "
        "servers only (their CPU work moves to the kept servers), CCF AWS model.",
        "Servers", "Ireland (Dublin)",
        cost={"low": cost_mid * 0.9, "mid": cost_mid, "high": cost_mid},
        kwh=kwh, co2=_co2(kwh, "Ireland (Dublin)"),
        evidence=[
            {"kind": "read", "text": "T-1058: 16 -> 64 vCPU, 'scale-back planned after go-live'; P-009 completed 2026-03-31"},
            {"kind": "read", "text": f"Removed servers average {util.reindex(removed.server_id).mean():.1f} % CPU"},
            {"kind": "derived", "text": f"{removed_vcpu:.0f} vCPU x 8,760 h no longer billed"},
        ],
    )


def m6_test_schedule(r, cal) -> Measure:
    vt = _bl(r["aws"][r["aws"].resource_id == "vm-test"])
    total_vcpu = vt.quantity.sum() / len(vt.date.unique()) / 24
    c = _bl(cal)
    on_h = 12 * int(c.workday.sum())
    off_h = 24 * len(c) - on_h
    vcpu = 4 * len(KEEP_TEST)
    cost_mid = vt.cost_chf.sum() * vcpu / total_vcpu * off_h / (24 * len(c))
    kwh = {s: vcpu * off_h * F.vcpu_kw("AWS", 2.0, 2.0, s) * F.PUE["AWS"].get(s) for s in SCENARIOS}
    return Measure(
        "M6", "Remaining test servers only during working hours",
        "Run the 3 remaining test servers on working days 07:00-19:00 and stop them at night and at weekends.",
        "vm-test", "AWS Instance Scheduler: on 07:00-19:00 on working days (business_calendar.csv); manual override "
        "for release tests. dr-failover is NOT scheduled.",
        0.5, "Head of IT", ["W5", "W8"],
        "Release tests and change freezes (W8, e.g. March 2026) switch the schedule off by arrangement.",
        f"{off_h:,} of {24 * len(c):,} hours off per server; {vcpu} vCPU; idle load 2 % CPU.",
        "Servers", "Ireland (Dublin)",
        cost={"low": cost_mid * 0.85, "mid": cost_mid, "high": cost_mid},
        kwh=kwh, co2=_co2(kwh, "Ireland (Dublin)"), requires=["M5"],
        evidence=[{"kind": "derived", "text": f"{off_h / (24 * len(c)):.0%} of hours outside working time"}],
    )


def m7_ai_seats(r) -> Measure:
    sub = r["subs"]
    aug = sub[sub.month == sub.month.max()].copy()
    fx = r["fx"].set_index("m").usd_chf[aug.month.iloc[0].to_period("M")]
    rows, saving_usd = [], 0.0
    for _, x in aug.iterrows():
        if x["product"] == "ChatGPT Team":
            target = 0      # cancel: duplicate benefit (tickets reject new seats for that reason)
        else:
            target = min(x.licences_purchased, x.licences_active_30d + 1)  # +1 buffer per department (T-1128)
        cut = x.licences_purchased - target
        saving_usd += cut * x.price_per_seat
        rows.append((x["product"], x.cost_center, x.licences_purchased, x.licences_active_30d, target))
    cost_mid = saving_usd * fx * 12
    gpt = aug[aug["product"] == "ChatGPT Team"]
    notice = (pd.Timestamp(gpt.contract_end.iloc[0]) - pd.Timedelta(days=int(gpt.notice_period_days.iloc[0])))
    return Measure(
        "M7", "AI subscriptions: cancel duplicate ChatGPT Team, trim idle seats",
        "Cancel ChatGPT Team (2 of 23 seats active) and keep Copilot/Claude seats at active users + 1 per department.",
        "sub-chatgpt, sub-copilot, sub-claude",
        f"Give notice for ChatGPT Team by {notice:%Y-%m-%d} (contract end {gpt.contract_end.iloc[0]}); move its active "
        "users to an idle Claude/Copilot seat; reduce Copilot and Claude seats at the next monthly billing.",
        1.0, "Head of Finance + department heads", [],
        "Seats are ordered per department (T-1128): each department keeps one spare seat. Copilot contract runs to "
        "2027-02-28: check whether seats can be reduced monthly. No CO2 effect: idle seats use no electricity.",
        f"August 2026 seats and list prices (Final rows only), USD->CHF {fx:.4f}, annualised.",
        "AI", "EU (mixed)",
        cost={"low": cost_mid * 0.75, "mid": cost_mid, "high": cost_mid},
        kwh={s: 0.0 for s in SCENARIOS}, co2={f"{s}_{m}": 0.0 for s in SCENARIOS for m in CH_MIX_VARIANTS},
        evidence=[
            {"kind": "read", "text": "Aug 2026: ChatGPT 2/23, Copilot 60/100, Claude 28/34 seats active"},
            {"kind": "read", "text": "9 ChatGPT seat requests rejected: 'a subscription with the same benefit already exists'"},
        ],
    )


def m8_saas(r) -> Measure:
    sa = r["saas"]
    last = sa[sa.month == sa.month.max()].copy()
    fx = r["fx"].set_index("m")
    p = last.month.iloc[0].to_period("M")
    rate = {"CHF": 1.0, "EUR": fx.eur_chf[p], "USD": fx.usd_chf[p]}
    last["util"] = last.licences_active_30d / last.licences_purchased
    cand = last[last.util < 0.8].copy()
    cand["target"] = np.ceil(cand.licences_active_30d * 1.1).clip(upper=cand.licences_purchased)
    cand["saving_chf_y"] = (cand.licences_purchased - cand.target) * cand.price_per_licence * cand.currency.map(rate) * 12
    cand["notice_by"] = pd.to_datetime(cand.contract_end) - pd.to_timedelta(cand.notice_period_days, unit="D")
    by = cand.groupby("contract").agg(saving=("saving_chf_y", "sum"), notice_by=("notice_by", "min"),
                                      end=("contract_end", "max"), util=("util", "mean")).sort_values("saving",
                                                                                                    ascending=False)
    late = by[by.notice_by < DATA_AS_OF]
    cost_mid = float(by.saving.sum())
    cost_low = float(by[by.notice_by >= DATA_AS_OF].saving.sum())
    top = ", ".join(f"{c} ({u:.0%})" for c, u in by.util.sort_values().head(4).items())
    return Measure(
        "M8", "SaaS licences: right-size at each renewal",
        "Reduce licences to active users + 10 % for every contract under 80 % utilisation, at its renewal date.",
        "saas-other", "Per contract and cost centre: give notice for the surplus licences before the notice date; "
        f"lowest utilisation: {top}.",
        1.5, "Head of Finance + contract owners", [],
        "Annual contracts can only change at renewal. "
        f"{len(late)} contracts are past their notice date ({', '.join(late.index[:3])}...): their saving starts one "
        "term later (conservative case excludes them). Video conferencing and chat tool overlap with Teams: cancel "
        "only after a human decision.",
        "Latest month (Aug 2026), Final rows, monthly FX; target = ceil(active x 1.1).",
        "SaaS", "EU (mixed)",
        cost={"low": cost_low, "mid": cost_mid, "high": cost_mid},
        kwh={s: 0.0 for s in SCENARIOS}, co2={f"{s}_{m}": 0.0 for s in SCENARIOS for m in CH_MIX_VARIANTS},
        evidence=[{"kind": "derived", "text": f"{len(by)} contracts under 80 % utilisation"}],
    ), by.reset_index()


def m9_ai_routing(r) -> Measure:
    ai = _bl(r["ai"])
    ai = ai[~((ai.resource_id == "ai-marketing") & ai.date.between("2026-03-17", "2026-03-19"))]
    sel = ai[(ai.model_class == "large") & (
        ((ai.resource_id == "ai-marketing") & (ai.task_type == "Classify")) |
        ((ai.resource_id == "ai-assistant") & ai.task_type.isin(["Summarise", "Translate"])))]
    base_cost = sel.cost_chf.sum()
    ratio = {"low": 0.40, "mid": 0.285, "high": 0.20}   # small/large price, from the data (Azure: 1.35/4.74)
    eff = (sel.tokens_in - sel.tokens_in_cache) + F.CACHE_WEIGHT * sel.tokens_in_cache + sel.tokens_out
    large_kwh = {s: eff.sum() / 1000 * F.KWH_PER_1000_TOKENS_LARGE.get(s) for s in SCENARIOS}
    kwh = {s: large_kwh[s] * (1 - F.SMALL_MODEL_SHARE.get(s)) for s in SCENARIOS}
    return Measure(
        "M9", "Right-size AI models for simple tasks",
        "Route classification, summaries and translations to a small model; keep large models for contracts, "
        "analysis and drafting.",
        "ai-marketing, ai-assistant",
        "Gateway routing rule by task_type: Classify (marketing script), Summarise and Translate -> small model "
        "(e.g. GPT-5.4 mini / Claude Haiku, or Swiss-hosted Apertus 8B as an option); enable prompt caching for "
        "the marketing script (0 % cached today). After a 1-week A/B quality check.",
        2.0, "Head of Marketing (classification) + Head of IT (assistant)", [],
        "Quality: switch only if the small model agrees with the large one on ≥ 95 % of a labelled sample. "
        "Contract review stays on a large model.",
        f"Baseline CHF {base_cost:,.0f} on these tasks (one-off loop days excluded); small/large price ratio "
        "0.285 measured on Azure OpenAI in ai_usage.csv (range 0.2-0.4); energy share of small model from factors.",
        "AI", "EU (mixed)",
        cost={"low": base_cost * (1 - ratio["low"]), "mid": base_cost * (1 - ratio["mid"]),
              "high": base_cost * (1 - ratio["high"])},
        kwh=kwh, co2=_co2(kwh, "EU (mixed)"),
        evidence=[
            {"kind": "read", "text": "Marketing classification runs on Claude Sonnet, 0 % cached input"},
            {"kind": "derived", "text": "Small model costs 28.5 % of the large one per token (Azure OpenAI, own data)"},
        ],
    )


LIST_PRICE_USD_PER_M_IN = {"Azure OpenAI GPT-5.4": 2.50, "GPT-5.4": 2.50, "Claude Sonnet 4.6": 3.00}


def m10_prompt_caching(r) -> Measure:
    ai = _bl(r["ai"])
    sel = ai[(ai.model_class == "large") & (
        ((ai.resource_id == "ai-assistant") & ~ai.task_type.isin(["Summarise", "Translate"])) |
        ai.resource_id.isin(["ai-agent", "ai-agent2"]))].copy()
    target = {"low": 0.25, "mid": 0.40, "high": 0.50}
    usd = r["fx"].set_index("m").usd_chf
    sel["usd_chf"] = sel.date.dt.to_period("M").map(usd)
    sel["p_in"] = sel.model.map(LIST_PRICE_USD_PER_M_IN).fillna(2.5)
    cur_share = sel.tokens_in_cache.sum() / sel.tokens_in.sum()
    cost, kwh = {}, {}
    for s in SCENARIOS:
        newly = (sel.tokens_in * target[s] - sel.tokens_in_cache).clip(lower=0)
        cost[s] = float((newly / 1e6 * sel.p_in * 0.9 * sel.usd_chf).sum())
        kwh[s] = float(newly.sum() / 1000 * (1 - F.CACHE_WEIGHT) * F.KWH_PER_1000_TOKENS_LARGE.get(s))
    return Measure(
        "M10", "Prompt caching for the office assistant and agents",
        f"Cache the repeated system prompts and documents so that about 40 % of input tokens are cached "
        f"(today {cur_share:.0%}).",
        "ai-assistant, ai-agent, ai-agent2",
        "Enable provider prompt caching (stable prompt prefix first, documents second) in the gateway; monitor the "
        "cache-hit rate weekly.",
        1.0, "Head of IT", [],
        "No quality impact (same model, same answer). The hit rate depends on prompt structure: target 25-50 %.",
        "Cached input billed at 10 % of the input price (README list prices: Sonnet 0.30 vs 3 USD, GPT-5.4 0.25 vs "
        "2.50 USD per 1M tokens); energy weight of cached tokens 10 %.",
        "AI", "EU (mixed)",
        cost={"low": cost["low"], "mid": cost["mid"], "high": cost["high"]},
        kwh=kwh, co2=_co2(kwh, "EU (mixed)"),
        evidence=[{"kind": "read", "text": f"Cached share today: {cur_share:.1%} of input tokens"}],
    )


# ---- bonus measures (use extra/ sources; default off) -------------------------------------
def b1_logs(r) -> Measure | None:
    from .config import EXTRA
    p = EXTRA / "log_volume.csv"
    if not p.exists():
        return None
    lv = pd.read_csv(p, encoding="utf-8-sig", parse_dates=["date"])
    lv["gb"] = np.where(lv.unit == "MB", lv.log_gb / 1000, lv.log_gb)
    g = _bl(lv).groupby("service").agg(gb_day=("gb", "mean"), ret=("retention_days", "max"))
    g["stored"] = g.gb_day * g.ret
    new = g.copy()
    new.loc[["app-portal", "app-api"], "ret"] = 90
    share = 1 - (new.gb_day * new.ret).sum() / g.stored.sum()
    ho = _bl(r["hoster"][r["hoster"].resource_id == "logs"])
    base_cost = ho.cost_chf.sum()
    base_kwh = {s: ho.quantity.sum() * F.STORAGE_KWH_PER_GB_DAY.get(s) * F.PUE["Hoster"].get(s) for s in SCENARIOS}
    kwh = {s: base_kwh[s] * share for s in SCENARIOS}
    return Measure(
        "M12", "Log retention 365 -> 90 days for app logs",
        "Keep application logs of app-portal and app-api for 90 days instead of 365; audit and auth logs unchanged.",
        "logs", "Change retention policy at the hoster; archive monthly summaries.", 0.5, "Head of IT", [],
        "Check security/compliance needs first; db-audit and auth stay at 365 days.",
        f"Stored log volume falls by {share:.0%} (extra/log_volume.csv); hoster log cost scales with GB-days.",
        "Cloud", "Switzerland (Zurich)", cost={"low": base_cost * share * 0.8, "mid": base_cost * share,
                                              "high": base_cost * share},
        kwh=kwh, co2=_co2(kwh, "Switzerland (Zurich)"), default_on=True, bonus=True,
        evidence=[{"kind": "derived", "text": f"app-portal + app-api = {g.loc[['app-portal', 'app-api']].stored.sum() / g.stored.sum():.0%} of stored logs"}],
    )


def b2_agents(r) -> Measure | None:
    from .config import EXTRA
    p = EXTRA / "ai_agent_runs.jsonl"
    if not p.exists():
        return None
    ag = load.read_jsonl(p).drop_duplicates("run_id")
    ag["start"] = pd.to_datetime(ag.start)
    ag = ag[(ag.start >= BASELINE_START) & (ag.start <= BASELINE_END)]
    ag = ag[ag.agent != "report-agent"]
    att = ag.retries + 1
    keep = np.minimum(att, 4) / att
    share = 1 - (ag["usage.tokens_in"] * keep).sum() / ag["usage.tokens_in"].sum()
    ai = _bl(r["ai"])
    sel = ai[ai.resource_id.isin(["ai-agent", "ai-agent2"])]
    eff = (sel.tokens_in - sel.tokens_in_cache) + F.CACHE_WEIGHT * sel.tokens_in_cache + sel.tokens_out
    kwh = {s: eff.sum() / 1000 * F.KWH_PER_1000_TOKENS_LARGE.get(s) * share for s in SCENARIOS}
    c = sel.cost_chf.sum() * share
    return Measure(
        "M11", "AI agents: cap retries at 3",
        "Stop agent runs after 3 retries and escalate to a human instead of looping (runs with up to 56 retries).",
        "ai-agent, ai-agent2", "Agent framework setting max_retries=3 + alert on aborted runs.", 0.5, "Head of IT", [],
        "Some runs may end as 'escalated' instead of 'resolved'.",
        f"{share:.0%} of agent input tokens are spent on retries beyond the 3rd (extra/ai_agent_runs.jsonl).",
        "AI", "EU (mixed)", cost={"low": c * 0.8, "mid": c, "high": c}, kwh=kwh, co2=_co2(kwh, "EU (mixed)"),
        default_on=True, bonus=True,
        evidence=[{"kind": "read", "text": f"{int((ag.retries >= 20).sum())} runs with 20+ retries"}],
    )


def b3_powerbi(r) -> Measure | None:
    from .config import EXTRA
    p = EXTRA / "powerbi_usage.csv"
    if not p.exists():
        return None
    pb = _bl(pd.read_csv(p, encoding="utf-8-sig", parse_dates=["date"]))
    g = pb.groupby("resource_id").agg(views=("view_count", "sum"), refmin=("refresh_duration_min", "sum"))
    low = g[(g.views < 50) & (g.index != "pbi-07")]
    share = low.refmin.sum() / g.refmin.sum()
    cap = _bl(r["azure"][r["azure"].resource_id == "pbi-kap"])
    base = cap.cost_chf.sum()
    kwh_base = {s: cap.quantity.sum() * 24 * 8 * F.vcpu_kw("Azure", 30, 3.1, s) * F.PUE["Azure"].get(s) for s in SCENARIOS}
    kwh = {s: kwh_base[s] * 0.5 for s in SCENARIOS}
    return Measure(
        "B3", "Power BI: refresh rarely used reports weekly, downsize capacity",
        f"{len(low)} reports opened fewer than 50 times a year cause {share:.0%} of refresh minutes; refresh them "
        "weekly and move to the next smaller capacity.",
        "pbi-kap", "Refresh schedule per report; capacity SKU one size down after 1 month of monitoring.", 1.5,
        "Head of IT + report owners", ["W7"],
        "pbi-07 (audit, W7) and regulatory reports excluded. Saving only materialises if the smaller capacity "
        "is enough (conservative case: 0).",
        "Capacity price halves one SKU down (assumption); energy halves with half the v-cores.",
        "Cloud", "Switzerland (Zurich)", cost={"low": 0.0, "mid": base * 0.5, "high": base * 0.5}, kwh=kwh,
        co2=_co2(kwh, "Switzerland (Zurich)"), default_on=False, bonus=True,
        evidence=[{"kind": "derived", "text": f"{share:.0%} of refresh minutes for reports with < 50 views/year"}],
    )


# ------------------------------------------------------------------------------------------
def build(r: dict, led: pd.DataFrame) -> dict:
    cal = load.calendar()
    jobs = load.jobs()
    bl = led[(led.month >= "2025-09") & (led.month <= "2026-08")]
    base_kwh_dev = {s: bl[bl.resource_id == "dp-dev"][f"kwh_{s}"].sum() for s in SCENARIOS}
    m2 = m2_dp_dev(r, cal, jobs)
    m8, saas_detail = m8_saas(r)
    ms = [m1_dp_prod(r, cal, jobs), m2, m3_relocate(r, m2, base_kwh_dev), m4_gpu(r, cal), m5_test_scale_back(r),
          m6_test_schedule(r, cal), m7_ai_seats(r), m8, m9_ai_routing(r), m10_prompt_caching(r)]
    for b in (b2_agents(r), b1_logs(r), b3_powerbi(r)):
        if b is not None:
            ms.append(b)
    return {"measures": ms, "saas_detail": saas_detail}


# Short labels for charts and switches in the app (the full title stays in templates and details).
SHORT = {"M1": "Production sleeps at night", "M2": "Dev cluster pauses", "M3": "Dev cluster to Zurich",
         "M4": "GPU on demand", "M5": "Smaller test setup", "M6": "Test servers office hours",
         "M7": "Fewer AI seats", "M8": "Right-size SaaS", "M9": "Small AI models", "M10": "Prompt caching",
         "M11": "Cap agent retries", "M12": "Shorter log retention", "B3": "Lighter Power BI",
         "B4": "Lean build pipelines", "B5": "Archive stale tables"}

NOT_RECOMMENDED = [
    {"id": "X1", "title": "Switch the production platform off every night and every weekend",
     "why": "Blocked: nightly ETL 02:00-06:00 and PBI refresh until 07:30 run every day incl. weekends (W3); "
            "month-end close until 04:00 (W1); year-end close every January evening (W2).",
     "instead": "M1 sleeps only outside these windows.", "owner": "Head of Consulting + Head of Finance"},
    {"id": "X2", "title": "Delete the idle dr-failover server (0.4 % CPU)",
     "why": "Blocked: emergency fallback required by management (T-1094, W5).", "instead": "Excluded from M5/M6.",
     "owner": "Management"},
    {"id": "X3", "title": "Delete or shorten the backup archive",
     "why": "Blocked: 10-year legal retention (T-1039); deletion already rejected (T-1195).",
     "instead": "Bonus: consolidate the triple backup chains only after a human review of restore tests.",
     "owner": "Head of IT"},
    {"id": "X4", "title": "Retire the legacy receivables report pbi-07 (hardly used)",
     "why": "Blocked: internal audit needs it in January (T-1167, W7).", "instead": "Excluded from B3.",
     "owner": "Head of Finance"},
    {"id": "X5", "title": "Cancel the video-conferencing and chat SaaS tools (overlap with Teams)",
     "why": "Human decision: user preferences, customer calls and contract terms unknown.",
     "instead": "Only right-sized in M8; full cancellation put to the Head of Finance.", "owner": "Head of Finance"},
    {"id": "X6", "title": "Move the test environment from Dublin to Zurich",
     "why": "Not worth it now: after M5/M6 only 12 vCPU run part-time; AWS Zurich costs ~18 % more (README list "
            "prices 0.1265 vs 0.107 USD/h).", "instead": "Revisit at the next contract review.", "owner": "Head of IT"},
    {"id": "X7", "title": "Run a Swiss open model (Apertus) on our own idle GPU",
     "why": "Would keep the Frankfurt GPU on 24/7 (dirty grid, 9 % utilisation) and cancel M4. A hosted Swiss "
            "endpoint is the better option.", "instead": "Option inside M9 via a Swiss-hosted API.",
     "owner": "Head of IT"},
]
