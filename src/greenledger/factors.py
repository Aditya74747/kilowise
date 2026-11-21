"""Conversion factors: every value is an estimate with low / mid / high, a source and a note.

Nothing here comes from the case data (the case deliberately leaves factors out).
Edit the numbers in ONE place (this file); the whole pipeline and the app follow.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Factor:
    key: str
    low: float
    mid: float
    high: float
    unit: str
    source: str
    note: str
    template_param: str | None = None  # row name in template_baseline_and_assumptions.csv
    kind: str = "assumed"  # provenance shown in the app: assumed | derived

    def get(self, scenario: str) -> float:
        return {"low": self.low, "mid": self.mid, "high": self.high}[scenario]


# --------------------------------------------------------------------------------------
# Grid mix, location-based (kg CO2e per kWh)
# --------------------------------------------------------------------------------------
GRID = {
    "CH_consumption": Factor(
        "grid_ch_consumption", 0.059, 0.094, 0.111, "kg CO2 per kWh",
        "BFE/treeze 'Energieetikette PW: Umweltkennwerte 2026' (Swiss consumer mix 2022-2024: 94 g CO2/kWh), "
        "pubdb.bfe.admin.ch/de/publication/download/12674; low: VSE 'CO2-Gehalt Strommix Schweiz' 2025 "
        "(location-based consumer mix 2024: 59 g), strom.ch/de/media/15408/download; high: BFE/treeze 2021-2023 "
        "consumer mix 111 g, pubdb.bfe.admin.ch/de/publication/download/12224 (accessed 2026-11-20)",
        "DEFAULT for Switzerland. Consumption mix incl. imports, because a data centre in Zurich physically draws "
        "from the Swiss grid incl. winter imports. 2025 likely higher (Goesgen outage, more gas imports).",
        "grid_mix_location_based_switzerland",
    ),
    "CH_production": Factor(
        "grid_ch_production", 0.025, 0.030, 0.040, "kg CO2 per kWh",
        "treeze for BAFU 'Umweltbilanz Strommix Schweiz 2018' (production mix 29.6 g CO2-eq/kWh), "
        "bafu.admin.ch/.../Umweltbilanz-Strommix-Schweiz-2018-v2.01.pdf (accessed 2026-11-20)",
        "Alternative shown as a toggle: production mix ignores imports and is about 3x lower.",
    ),
    "DE": Factor(
        "grid_de", 0.33, 0.363, 0.42, "kg CO2 per kWh",
        "Umweltbundesamt: 363 g CO2/kWh for electricity consumed in Germany in 2024, "
        "umweltbundesamt.de/themen/co2-emissionen-pro-kilowattstunde-strom-2024 (accessed 2026-11-20)",
        "Frankfurt. low: 2025 trend slightly lower; high: +15 % upstream/lifecycle share.",
        "grid_mix_location_based_germany",
    ),
    "IE": Factor(
        "grid_ie", 0.20, 0.226, 0.26, "kg CO2 per kWh",
        "EPA Ireland provisional GHG 1990-2024: power generation intensity 226 g CO2/kWh in 2024 (254 in 2023), "
        "epa.ie/publications/.../EPA-Provisional-1990-2024-GHG-Report-1716.pdf (accessed 2026-11-20)",
        "Dublin. high: +15 % for imports from GB (counted as zero in national reporting) and upstream.",
        "grid_mix_location_based_ireland",
    ),
    "EU": Factor(
        "grid_eu_mixed", 0.15, 0.22, 0.30, "kg CO2 per kWh",
        "EEA indicator 'GHG emission intensity of electricity generation' (EU-27, 2023-2024), "
        "eea.europa.eu/en/analysis/indicators/greenhouse-gas-emission-intensity-of-1 (accessed 2026-11-20). "
        "Exact 2024 value to be confirmed on the EEA chart.",
        "Used for AI providers and SaaS ('EU mixed', no location per row). Wide range on purpose.",
    ),
}

# Market-based (bonus view, never used for the targets): what the electricity CONTRACTS say.
# Switzerland: every kWh is covered by guarantees of origin (GO), so there is no residual mix; the supplier mix applies.
MARKET = Factor(
    "grid_market_ch", 0.0, 0.0175, 0.03, "kg CO2 per kWh",
    "BFE/treeze 2026: Swiss supplier mix based on guarantees of origin 2024: 17.5 g CO2/kWh, "
    "pubdb.bfe.admin.ch/de/publication/download/12674; AIB: no residual mix for Switzerland (all consumption "
    "tracked with GOs), aib-net.org/facts/european-residual-mix/2024 (accessed 2026-11-21)",
    "Zurich (hoster, Azure, AWS). low 0 = renewable GOs as confirmed for the hoster in T-1030/T-1181/T-1203/T-1227; "
    "mid = Swiss supplier mix; high = supplier mix + uncertainty.",
    "grid_mix_market_based",
)
# Outside Switzerland we have no certificate for our consumption in the data. GHG Protocol Scope 2: without a
# contractual instrument the residual mix applies, and that is DIRTIER than the location-based grid mix.
MARKET_RESIDUAL = Factor(
    "grid_market_residual_eu", 0.0, 0.452, 0.537, "kg CO2 per kWh",
    "AIB 'European Residual Mixes 2024' (published 2025-05-30): European average residual mix 452 g CO2/kWh; "
    "high = highest aggregate in the same table (537 g), aib-net.org/facts/european-residual-mix/2024 "
    "(accessed 2026-11-21). Country values (DE, IE) to be read from Table 2.",
    "Frankfurt, Dublin, AI providers and SaaS. low 0 = if the providers' public '100 % renewable matching' "
    "claims are accepted as instruments (README: matching does not mean the data centre physically runs on it).",
)

# Hourly profile of the Swiss consumption mix, relative to the daily mean (for carbon-aware load shifting).
# Shape from Electricity Maps 'Grid in review 2025 - Switzerland' (summer midday trough ~29 g, winter evening peak
# ~91 g) and UNIGE (high emissions at off-peak winter hours due to imports). Assumption, flagged in the app.
HOURLY_CH_SHAPE = [1.12, 1.12, 1.10, 1.08, 1.06, 1.04, 1.02, 0.98, 0.92, 0.86, 0.80, 0.76,
                   0.74, 0.76, 0.80, 0.86, 0.94, 1.04, 1.14, 1.20, 1.20, 1.18, 1.15, 1.13]
HOURLY_SOURCE = ("Electricity Maps 'Grid in review 2025: Switzerland' (summer midday 29 g vs winter evening peak "
                 "91 g CO2/kWh), electricitymaps.com/grid-in-review-2025/switzerland; UNIGE hourly Swiss mix, "
                 "unige.ch/sysener/services/CO2 (accessed 2026-11-21). Shape normalised to mean 1.0; assumption.")

# --------------------------------------------------------------------------------------
# Server power model (Cloud Carbon Footprint linear model)
# W per vCPU = Wmin + util * (Wmax - Wmin); memory 0.392 W/GB; x overhead multiplier
# --------------------------------------------------------------------------------------
CCF_WATTS = {  # per vCPU
    "Azure": (0.78, 3.76),
    "AWS": (0.74, 3.50),
    "Hoster": (0.78, 3.76),
}
CCF_SOURCE = (
    "Cloud Carbon Footprint methodology (Azure avg min/max 0.78/3.76 W per vCPU, AWS 0.74/3.5, "
    "memory 0.392 W/GB), cloudcarbonfootprint.org/docs/methodology (accessed 2026-11-20)"
)
MEM_W_PER_GB = 0.392
# CCF is known to be a lower bound (no disks, NICs, idle/unallocated capacity).
SERVER_OVERHEAD = Factor(
    "server_overhead_multiplier", 1.0, 1.5, 2.5, "x",
    CCF_SOURCE,
    "low = CCF as published; mid = +50 % for host parts not in CCF (disks, NICs, fans, unallocated capacity); "
    "high = 2.5x (upper end of independent per-vCPU estimates).",
)

GPU_TDP_W = 300.0  # data dictionary: "one GPU of the 300-watt class"
GPU_IDLE_W = Factor(
    "gpu_idle_w", 35.0, 50.0, 70.0, "W",
    "Assumption: datacentre GPUs of the 250-300 W class idle at roughly 10-25 % of TDP "
    "(vendor datasheets / nvidia-smi idle readings); to be measured on gpu-ml-01.",
    "Utilisation from server_metrics_weekly.gpu_avg_pct drives the rest: W = idle + util * (300 - idle).",
)

STORAGE_KWH_PER_GB_DAY = Factor(
    "storage_kwh_per_gb_day", 1.56e-5, 4.32e-5, 8.64e-5, "kWh",
    "Cloud Carbon Footprint storage coefficients (HDD 0.65 Wh/TB-h, SSD 1.2 Wh/TB-h) "
    "x replication factor, cloudcarbonfootprint.org/docs/methodology (accessed 2026-11-20)",
    "low = HDD, no replication (0.65*24/1e6); mid = SSD x 1.5 replication; high = SSD x 3 replication.",
    "energy_per_gb_storage_day",
)

NETWORK_KWH_PER_GB = Factor(
    "network_kwh_per_gb", 0.0006, 0.001, 0.006, "kWh",
    "Cloud Carbon Footprint networking coefficient 0.001 kWh/GB, cloudcarbonfootprint.org/docs/methodology",
    "Data egress and CDN volume. High end reflects older top-down studies.",
)

# --------------------------------------------------------------------------------------
# AI
# --------------------------------------------------------------------------------------
KWH_PER_1000_TOKENS_LARGE = Factor(
    "kwh_per_1000_tokens", 0.00005, 0.0002, 0.001, "kWh",
    "Google (2025): median Gemini Apps text prompt 0.24 Wh incl. idle capacity and datacentre overhead, "
    "cloud.google.com/blog/products/infrastructure/measuring-the-environmental-impact-of-ai-inference; "
    "OpenAI CEO statement 0.34 Wh per ChatGPT query (via CBS News, 2025-08-21) (accessed 2026-11-20)",
    "Gateway data average about 1,800 tokens per request; 0.2 Wh/1000 tokens gives about 0.36 Wh per request, "
    "in line with both disclosures. Applies to LARGE models, incl. datacentre overhead (no extra PUE). "
    "Cached input tokens weighted at 10 %.",
    "energy_per_1000_tokens",
)
SMALL_MODEL_SHARE = Factor(
    "small_model_energy_share", 0.10, 0.25, 0.40, "x of large model",
    "Assumption based on parameter-count ratio of 'mini' vs flagship models; check on ML.ENERGY leaderboard, "
    "ml.energy/leaderboard",
    "Energy per token of a small model as a share of a large model.",
)
CACHE_WEIGHT = 0.10

# ---- Models page (ai_models.py): energy per token from the model's size, grids for training and hosting ----
WH_PER_1K_OUT_PER_B_ACTIVE = Factor(
    "wh_per_1000_output_tokens_per_billion_active_params", 0.0015, 0.0035, 0.007, "Wh",
    "ML.ENERGY measurements on H100 (GPU only, best setting): Llama 3.1 8B 19.5 Wh and 70B 104 Wh per 1M output "
    "tokens = 0.0024 and 0.0015 Wh per 1,000 tokens per billion parameters, leadgreen.ai/index and ml.energy/leaderboard; "
    "Google 2025: full-system energy is 2.4x the active-accelerator energy (0.24 vs 0.10 Wh per median prompt), "
    "cloud.google.com/blog/products/infrastructure/measuring-the-environmental-impact-of-ai-inference (via search 2026-11-21)",
    "Energy per 1,000 OUTPUT tokens = factor x active parameters (billions). Low = GPU only, well batched; mid = x2.3 "
    "for host, idle capacity and data-centre overhead; high = poorly batched serving. Reasoning models also bill "
    "their hidden thinking as output tokens.",
)
INPUT_TOKEN_WEIGHT = Factor(
    "input_token_energy_weight", 0.05, 0.15, 0.30, "x of an output token",
    "Assumption: input tokens are processed in parallel (prefill) and cost a fraction of a generated token; "
    "order of magnitude from ML.ENERGY prefill/decode measurements, ml.energy/leaderboard",
    "Energy of one input token as a share of one output token. Cached input tokens: CACHE_WEIGHT of an input token.",
)
GRID_US = Factor(
    "grid_us_average", 0.33, 0.37, 0.42, "kg CO2 per kWh",
    "US EPA eGRID 2022, US average output emission rate about 823 lb/MWh = 0.37 kg/kWh, epa.gov/egrid "
    "(value to confirm on the eGRID summary tables)",
    "Hosting grid option on the Models page (many API models run in US data centres); gpt-oss training.",
)
GRID_CN = Factor(
    "grid_china_average", 0.53, 0.58, 0.62, "kg CO2 per kWh",
    "Ember / IEA, China electricity carbon intensity 2023 about 0.58 kg/kWh, ember-energy.org (value to confirm)",
    "Only used to estimate DeepSeek V3 training emissions on the Models page.",
)
TRAIN_GPU_KW = Factor(
    "training_gpu_kw", 0.5, 0.7, 0.7, "kW per GPU",
    "Board power (TDP) of H100 / H800 SXM GPUs, 700 W, as used by Meta in the Llama model cards",
    "Converts published GPU hours into energy for models whose makers publish hours but not emissions.",
)
TRAIN_PUE = Factor(
    "training_pue", 1.1, 1.2, 1.4, "ratio",
    "Assumption for large training clusters (hyperscale PUE 1.1-1.2, see PUE factors)",
    "Data-centre overhead on top of the GPU energy for derived training emissions.",
)

KWH_PER_SUBSCRIPTION_MESSAGE = Factor(
    "kwh_per_message", 0.0001, 0.0003, 0.003, "kWh",
    "Google 2025 (0.24 Wh per median prompt) and OpenAI (0.34 Wh per query), see energy_per_1000_tokens",
    "One chat message in ChatGPT Team / Claude Team / Copilot. High end: long-context and reasoning answers.",
    "energy_per_subscription_message",
)

SAAS_KWH_PER_ACTIVE_USER_MONTH = Factor(
    "saas_kwh_per_active_user_month", 0.1, 0.5, 2.0, "kWh",
    "Assumption (no vendor data). Order of magnitude from per-user SaaS server share; weak source, flagged.",
    "Only ACTIVE licences use energy; idle seats cost money but no electricity.",
)

# --------------------------------------------------------------------------------------
# Datacentre efficiency
# --------------------------------------------------------------------------------------
PUE = {
    "Azure": Factor("pue_azure", 1.12, 1.185, 1.45, "ratio",
                    "Microsoft: newest datacentre generation design PUE 1.12 (azure.microsoft.com blog); CCF uses 1.185 "
                    "for Azure; high = Uptime Institute 2024 Europe average 1.45", "", "pue"),
    "AWS": Factor("pue_aws", 1.10, 1.11, 1.15, "ratio",
                  "AWS sustainability fact sheets (measured, data centres operated by AWS, Jan-Dec): Switzerland "
                  "(Zurich) 1.11 in 2023, 2024 and 2025; Ireland (Dublin) 1.10 / 1.11 / 1.10; high = AWS global "
                  "average 2024 1.15. sustainability.aboutamazon.com/aws-sustainability-fact-sheets/"
                  "aws-fact-sheet-switzerland.pdf and aws-fact-sheet-ireland.pdf (accessed 2026-11-21)",
                  "Replaces the CCF default 1.135: our AWS rows are only Zurich and Dublin, both published."),
    "Hoster": Factor("pue_hoster", 1.2, 1.4, 1.56, "ratio",
                     "Assumption for a Swiss colocation hoster; high = Uptime Institute 2024 global average 1.56, "
                     "intelligence.uptimeinstitute.com (accessed 2026-11-20)", ""),
}

SHARED_SERVICES = {"support", "st-backup", "logs", "net-egress", "pbi-kap"}
ALLOCATION_RULE = (
    "1) Direct where the data names the user: AI gateway rows by department, subscriptions and SaaS by cost centre, "
    "cloud resources via mapping_departments_tools.csv. 2) Company-wide IT services that serve every department "
    "(cloud support, backup archive, logging, data egress, Power BI capacity) and any 'Overhead' (cost centre 9000) "
    "-> split by average FTE share Sep 2025-Aug 2026 (extra/headcount.csv). 3) Test account 9100 (sandbox) excluded "
    "as instructed in the AWS export. Project hours (project_hours_monthly.csv) are the alternative key for "
    "recharging project costs to customers (not used in the baseline)."
)


def region_key(region: str, ch_mix: str = "consumption") -> str:
    r = (region or "").lower()
    if "switzerland" in r or "zurich" in r:
        return "CH_production" if ch_mix == "production" else "CH_consumption"
    if "germany" in r or "frankfurt" in r:
        return "DE"
    if "ireland" in r or "dublin" in r:
        return "IE"
    return "EU"


def grid(region: str, scenario: str, ch_mix: str = "consumption") -> float:
    if ch_mix == "market":
        return market(region, scenario)
    return GRID[region_key(region, ch_mix)].get(scenario)


def market(region: str, scenario: str) -> float:
    """Market-based factor: Swiss supplier mix (GO-covered) in Switzerland, residual mix elsewhere."""
    return (MARKET if region_key(region) == "CH_consumption" else MARKET_RESIDUAL).get(scenario)


def vcpu_kw(provider: str, util_pct: float, mem_gb_per_vcpu: float, scenario: str) -> float:
    """Average kW drawn by ONE vCPU (incl. its memory share) at a given CPU utilisation, excl. PUE."""
    wmin, wmax = CCF_WATTS.get(provider, CCF_WATTS["Azure"])
    u = min(max((util_pct or 0) / 100.0, 0.0), 1.0)
    w = wmin + u * (wmax - wmin) + mem_gb_per_vcpu * MEM_W_PER_GB
    return w * SERVER_OVERHEAD.get(scenario) / 1000.0


def gpu_kw(util_pct: float, scenario: str, host_vcpu: int = 8, host_mem_gb: int = 56) -> float:
    idle = GPU_IDLE_W.get(scenario)
    u = min(max((util_pct or 0) / 100.0, 0.0), 1.0)
    gpu_w = idle + u * (GPU_TDP_W - idle)
    host_kw = host_vcpu * vcpu_kw("Azure", 5.0, host_mem_gb / host_vcpu, scenario)
    return gpu_w / 1000.0 + host_kw


ALL_FACTORS: list[Factor] = [
    *GRID.values(), MARKET, MARKET_RESIDUAL, SERVER_OVERHEAD, GPU_IDLE_W, STORAGE_KWH_PER_GB_DAY, NETWORK_KWH_PER_GB,
    KWH_PER_1000_TOKENS_LARGE, SMALL_MODEL_SHARE, KWH_PER_SUBSCRIPTION_MESSAGE, SAAS_KWH_PER_ACTIVE_USER_MONTH,
    *PUE.values(), WH_PER_1K_OUT_PER_B_ACTIVE, INPUT_TOKEN_WEIGHT, GRID_US, GRID_CN, TRAIN_GPU_KW, TRAIN_PUE,
]
