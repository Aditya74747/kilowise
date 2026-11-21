"""Model catalogue for the Models page: size, capabilities, API price, training CO2 and energy per token of
open and closed language models, compared on the company's own token workload.

Every value carries where it comes from:
  published  stated by the maker (model card, paper, official pricing page)
  host       price of a hosting provider for an open model (no official API)
  estimate   not disclosed by the maker; a published third-party estimate or a size class, always with a range
  derived    computed here from published inputs (the calculation is shown in the app)
Prices were read on 2026-11-21 (USD per 1M tokens, standard tier, short context). They change often.

Energy per token is not disclosed for most models. It is estimated from the ACTIVE parameters (the share of the
model that works on each token) with factors.WH_PER_1K_OUT_PER_B_ACTIVE, measured on open models (ML.ENERGY), and
cross-checked with Google's and Mistral's per-prompt disclosures. Training emissions are one-off and shared by every
user of a model; they do not count in the company's location-based CO2 (see CLAUDE.md, design decisions).
"""
from __future__ import annotations

from . import factors as F

# Sources (short keys used in the catalogue; the app lists them in full)
SRC = {
    "anthropic": "Anthropic API pricing, platform.claude.com/docs/en/about-claude/pricing (read 2026-11-21)",
    "openai": "OpenAI API pricing, developers.openai.com/api/docs/pricing (read 2026-11-21)",
    "google": "Gemini API pricing, aistudio.google.com/docs/pricing (read 2026-11-21; Flash prices rise on 2027-01-01)",
    "mistral": "Mistral API pricing, mistral.ai/pricing/api (via search 2026-11-21)",
    "together": "Together AI serverless prices, docs.together.ai and benchlm.ai/hosts/together (via search 2026-11-21)",
    "deepseek": "DeepSeek API launch price for V3 (Dec 2024), simonwillison.net/2024/Dec/26/deepseek-v3; check current rates",
    "publicai": "Public AI prices for Apertus, artificialanalysis.ai/models/apertus-70b-instruct/providers (via search 2026-11-21)",
    "medec": "Ben Abacha et al. 2024, MEDEC (arXiv 2412.19260): estimates GPT-4o ~200B, Claude 3.5 Sonnet ~175B, "
             "GPT-4o-mini ~8B parameters; not confirmed by the makers",
    "meta31": "Meta Llama 3.1 model card: training GPU hours and location-based tCO2eq per size "
              "(8B 420, 70B 2,040, 405B 8,930; total 11,390)",
    "meta4": "Meta Llama 4 model card: Scout 5.0M H100 hours, 1,354 t; Maverick 2.38M H100 hours, 645 t (location-based)",
    "mistral_lca": "Mistral AI, 'Our contribution to a global environmental standard for AI' (2025-07): Mistral Large 2 "
                   "lifecycle 20.4 ktCO2e (training and 18 months of use), 1.14 gCO2e per 400-token answer",
    "gptoss": "OpenAI gpt-oss model card (arXiv 2508.10925): 116.8B total, 5.1B active; about 2.1M H100 hours",
    "dsv3": "DeepSeek-V3 technical report: 671B total, 37B active, 2.788M H800 GPU hours",
    "apertus": "Swiss AI Apertus report (arXiv 2509.14233) and Apertus 1.5 (arXiv 2610.15542): about 5 GWh for "
               "pretraining on CSCS Alps (hydropower); 1,800+ languages",
    "mistral3": "Mistral 3 announcement (Dec 2025): Mistral Large 3, sparse mixture of experts, 41B active of 675B",
    "own": "This project: Qwen2.5-1.5B-Instruct + LoRA, fine-tuning measured with nvidia-smi (models/chat-lora/metrics.json)",
}

# Size classes for closed models (active parameters in billions, low / mid / high). The makers do not publish sizes.
SIZE_CLASS = {
    "frontier": (150, 300, 600),
    "mid": (60, 150, 250),
    "small": (8, 20, 40),
    "tiny": (2, 5, 10),
}


def _m(id, name, maker, open_, tier, total_b, active, size_kind, size_src, mods, reasoning, ctx_k, price, price_src,
       price_kind, training, note="", uses=(), local=False, langs=""):
    lo, mid, hi = active if isinstance(active, tuple) else (active, active, active)
    p_in, p_cache, p_out = price if price else (None, None, None)
    return {"id": id, "name": name, "maker": maker, "open": open_, "tier": tier, "params_total_b": total_b,
            "active_b": {"low": lo, "mid": mid, "high": hi}, "size_kind": size_kind, "size_source": size_src,
            "modalities": mods, "reasoning": reasoning, "context_k": ctx_k,
            "price_in": p_in, "price_cached": p_cache, "price_out": p_out, "price_source": price_src, "price_kind": price_kind,
            "training": training, "note": note, "uses": list(uses), "local": local, "languages": langs}


def _trained(t, kind, src, calc=""):
    return {"t_co2": t, "kind": kind, "source": src, "calc": calc}


def _derived_training(gpu_hours_m: float, grid: F.Factor, where: str) -> dict:
    mwh = gpu_hours_m * 1e6 * F.TRAIN_GPU_KW.mid * F.TRAIN_PUE.mid / 1000
    t = mwh * grid.mid
    return {"t_co2": round(t), "kind": "derived", "source": "",
            "calc": f"{gpu_hours_m:g}M GPU hours × {F.TRAIN_GPU_KW.mid} kW × PUE {F.TRAIN_PUE.mid} = {mwh:,.0f} MWh "
                    f"× {grid.mid} kg/kWh ({where}) = {t:,.0f} t"}


def catalogue() -> list[dict]:
    T, NA = "text", None
    nd = lambda src="": _trained(None, "not disclosed", src)
    ds = _derived_training(2.788, F.GRID_CN, "China grid"); ds["source"] = SRC["dsv3"]
    oss = _derived_training(2.1, F.GRID_US, "US grid"); oss["source"] = SRC["gptoss"]
    ap_mwh = 5000
    ap = {"t_co2": round(ap_mwh * F.GRID["CH_consumption"].mid), "kind": "derived", "source": SRC["apertus"],
          "calc": f"about {ap_mwh:,} MWh × {F.GRID['CH_consumption'].mid} kg/kWh (Swiss consumption mix) = "
                  f"{ap_mwh * F.GRID['CH_consumption'].mid:,.0f} t location-based; near zero market-based (hydropower)"}
    return [
        # ---- closed, frontier and mid ----------------------------------------------------------------------------
        _m("claude-opus-5.5", "Claude Opus 5.5", "Anthropic", False, "Frontier", NA, SIZE_CLASS["frontier"], "estimate",
           "Size class estimate; Anthropic does not publish sizes", [T, "image"], True, 1000, (4, 0.20, 20),
           SRC["anthropic"], "published", nd()),
        _m("claude-sonnet-5.5", "Claude Sonnet 5.5", "Anthropic", False, "Mid", NA, SIZE_CLASS["mid"], "estimate",
           SRC["medec"], [T, "image"], True, 1000, (2, 0.10, 10), SRC["anthropic"], "published", nd()),
        _m("claude-sonnet-4.6", "Claude Sonnet 4.6", "Anthropic", False, "Mid", NA, SIZE_CLASS["mid"], "estimate",
           SRC["medec"], [T, "image"], True, 1000, (3, 0.30, 15), SRC["anthropic"], "published", nd(),
           uses=("Claude Sonnet 4.6",)),
        _m("claude-haiku-5.5", "Claude Haiku 5.5", "Anthropic", False, "Small", NA, SIZE_CLASS["small"], "estimate",
           "Size class estimate", [T, "image"], False, NA, (0.10, 0.01, 0.50), SRC["anthropic"], "published", nd(),
           note="Price for prompts up to 100,000 tokens"),
        _m("gpt-5.5", "GPT-5.5", "OpenAI", False, "Frontier", NA, SIZE_CLASS["frontier"], "estimate",
           "Size class estimate; OpenAI does not publish sizes", [T, "image"], True, 272, (5, 0.50, 30),
           SRC["openai"], "published", nd(), note="Context: price shown for prompts up to 272,000 tokens"),
        _m("gpt-5.4", "GPT-5.4", "OpenAI", False, "Mid", NA, SIZE_CLASS["mid"], "estimate", SRC["medec"],
           [T, "image"], True, 272, (2.5, 0.25, 15), SRC["openai"], "published", nd(),
           uses=("GPT-5.4", "Azure OpenAI GPT-5.4")),
        _m("gpt-5.4-mini", "GPT-5.4 mini", "OpenAI", False, "Small", NA, SIZE_CLASS["small"], "estimate", SRC["medec"],
           [T, "image"], True, 272, (0.75, 0.075, 4.5), SRC["openai"], "published", nd(),
           uses=("GPT-5.4 mini", "Azure OpenAI GPT-5.4 mini")),
        _m("gpt-5-nano", "GPT-5 nano", "OpenAI", False, "Tiny", NA, SIZE_CLASS["tiny"], "estimate", "Size class estimate",
           [T, "image"], True, 272, (0.05, 0.005, 0.40), SRC["openai"], "published", nd()),
        _m("gemini-3.8-flash", "Gemini 3.8 Flash", "Google", False, "Mid", NA, (15, 40, 100), "estimate",
           "Size class estimate; Google does not publish sizes", [T, "image", "audio", "video"], True, 1000,
           (0.75, 0.075, 3.75), SRC["google"], "published", nd(), note="Introductory price until 2026-12-31, then double"),
        _m("gemini-3.5-flash-lite", "Gemini 3.5 Flash-Lite", "Google", False, "Small", NA, (5, 10, 25), "estimate",
           "Size class estimate", [T, "image", "audio", "video"], False, 1000, (0.30, 0.03, 2.50), SRC["google"],
           "published", nd()),
        # ---- open weights ------------------------------------------------------------------------------------------
        _m("mistral-large-3", "Mistral Large 3", "Mistral AI", True, "Frontier", 675, 41, "published", SRC["mistral3"],
           [T, "image"], False, 256, (0.5, None, 1.5), SRC["mistral"], "published",
           _trained(None, "not disclosed", SRC["mistral_lca"],
                    "Not disclosed for Large 3. Its predecessor Large 2: 20,400 t over its life (training and 18 months of use)."),
           note="Open weights (Apache 2.0); also runs in the EU"),
        _m("deepseek-v3", "DeepSeek V3", "DeepSeek", True, "Frontier", 671, 37, "published", SRC["dsv3"], [T], False, 128,
           (0.27, 0.07, 1.10), SRC["deepseek"], "published", ds, note="Launch price; the API runs in China"),
        _m("llama-3.1-405b", "Llama 3.1 405B", "Meta", True, "Frontier", 405, 405, "published", SRC["meta31"], [T], False,
           128, (3.5, None, 3.5), SRC["together"], "host", _trained(8930, "published", SRC["meta31"])),
        _m("llama-4-maverick", "Llama 4 Maverick", "Meta", True, "Mid", 400, 17, "published", SRC["meta4"], [T, "image"],
           False, 1000, None, "", "", _trained(645, "published", SRC["meta4"]), note="Hosted price not checked"),
        _m("llama-3.3-70b", "Llama 3.3 70B", "Meta", True, "Mid", 70, 70, "published", SRC["meta31"], [T], False, 128,
           (1.04, None, 1.04), SRC["together"], "host",
           _trained(2040, "published", SRC["meta31"], "Training of the Llama 3.1 70B base model, which 3.3 builds on")),
        _m("gpt-oss-120b", "gpt-oss-120b", "OpenAI", True, "Mid", 116.8, 5.1, "published", SRC["gptoss"], [T], True, 128,
           (0.15, None, 0.60), SRC["together"], "host", oss, note="Open weights (Apache 2.0); fits on one 80 GB GPU"),
        _m("apertus-70b", "Apertus 70B", "Swiss AI (EPFL, ETH, CSCS)", True, "Mid", 70, 70, "published", SRC["apertus"],
           [T], False, 65, (0.82, None, 2.92), SRC["publicai"], "host", ap, local=True,
           langs="1,800+ languages incl. Swiss German and Romansh", note="Swiss open model, fully open training data"),
        _m("apertus-8b", "Apertus 8B", "Swiss AI (EPFL, ETH, CSCS)", True, "Small", 8, 8, "published", SRC["apertus"],
           [T], False, 65, (0.10, None, 0.20), SRC["publicai"], "host",
           _trained(None, "not disclosed", SRC["apertus"], "Not broken out from the Apertus project total"), local=True,
           langs="1,800+ languages incl. Swiss German and Romansh"),
        _m("llama-3.1-8b", "Llama 3.1 8B", "Meta", True, "Small", 8, 8, "published", SRC["meta31"], [T], False, 128,
           (0.18, None, 0.18), SRC["together"], "host", _trained(420, "published", SRC["meta31"]), local=True),
        _m("qwen2.5-1.5b-kilo", "Qwen2.5 1.5B + LoRA (Kilo)", "Alibaba, fine-tuned by us", True, "Tiny", 1.5, 1.5,
           "published", SRC["own"], [T], False, 32, (0, 0, 0), SRC["own"], "own",
           _trained(0.0000035, "published", SRC["own"], "Our fine-tuning only: 0.037 kWh measured, about 3.5 g CO2; base model training not disclosed"),
           local=True, note="Runs on our own laptop; no API price, electricity only"),
    ]


RENT_USD_PER_GPU_H = 2.0   # rental price DeepSeek itself used for its cost figure; applied to other published GPU hours


def training_runs() -> list[dict]:
    """Where well-known models were trained, with training CO2 and cost. kind per value:
    published (the maker), estimate (third party, often a range), derived (computed here), None = not disclosed."""
    def run(model, maker, year, open_, site, country, hardware, grid_g, mwh, co2, cost, note, sources):
        return {"model": model, "maker": maker, "year": year, "open": open_, "site": site, "country": country,
                "hardware": hardware, "grid_g": grid_g, "mwh": mwh, "co2": co2, "cost": cost, "note": note, "sources": sources}

    def val(lo, hi=None, kind="published", label=""):
        return {"low": lo, "high": hi if hi is not None else lo, "kind": kind, "label": label}

    rent = lambda h_m: round(h_m * RENT_USD_PER_GPU_H, 1)
    ds = _derived_training(2.788, F.GRID_CN, "China grid")
    oss = _derived_training(2.1, F.GRID_US, "US grid")
    l4_h = 7.38
    return [
        run("GPT-3 (175B)", "OpenAI", 2020, False, "Microsoft Azure supercomputer", "United States", "NVIDIA V100",
            429, 1287, val(552, label="Patterson et al. 2021"), None,
            "Same size as BLOOM, about 22 times the CO2: the grid made the difference.",
            ["Patterson et al. 2021, 'Carbon Emissions and Large Neural Network Training', arXiv 2104.10350"]),
        run("GPT-4", "OpenAI", 2022, False, "Microsoft Azure, West Des Moines, Iowa (as reported)", "United States",
            "NVIDIA A100 (reported)", None, None, val(1000, 15000, "estimate", "third-party estimates, not disclosed"),
            val(40, 78, "estimate", "Epoch AI about $40M, Stanford AI Index about $78M (final run)"),
            "Microsoft's Iowa campus drew 11.5 million gallons of water in July 2022, weeks before training finished (AP).",
            ["Stanford AI Index 2024 (Epoch AI data)", "AP via thestreet.com (Iowa, water)",
             "Estimates collected in medium.com/data-science/the-carbon-footprint-of-gpt-4 and arXiv 2601.06174"]),
        run("GPT-5.5", "OpenAI", 2026, False, "Stargate flagship site, Abilene, Texas (Oracle Cloud)", "United States",
            "NVIDIA GB200", None, None, None, None,
            "OpenAI states the model was trained at Abilene; energy, emissions and cost are not disclosed.",
            ["openai.com/index/building-the-compute-infrastructure-for-the-intelligence-age"]),
        run("gpt-oss-120b", "OpenAI", 2025, True, "Not disclosed", "United States (assumed)", "NVIDIA H100 (2.1M GPU hours)",
            round(F.GRID_US.mid * 1000), round(2.1e6 * F.TRAIN_GPU_KW.mid * F.TRAIN_PUE.mid / 1000),
            val(oss["t_co2"], kind="derived", label=oss["calc"]),
            val(rent(2.1), kind="derived", label=f"2.1M GPU hours × ${RENT_USD_PER_GPU_H:g} rental"),
            "Open weights; small enough to run on one 80 GB GPU.", [SRC["gptoss"]]),
        run("Llama 3.1 405B", "Meta", 2024, True, "Meta's custom-built GPU cluster and production infrastructure",
            "United States", "NVIDIA H100 (30.84M GPU hours)", None, None,
            val(8930, label="location-based; 0 t market-based (renewable energy contracts)"),
            val(53, 170, "estimate", "Epoch AI about $53M, Stanford AI Index about $170M"),
            "Meta reports both views: 8,930 t location-based and 0 t market-based.", [SRC["meta31"], "Stanford AI Index 2025"]),
        run("Llama 4 Scout + Maverick", "Meta", 2025, True, "Meta GPU clusters", "United States",
            f"NVIDIA H100 ({l4_h}M GPU hours)", None, None, val(1999, label="location-based; 0 t market-based"),
            val(rent(l4_h), kind="derived", label=f"{l4_h}M GPU hours × ${RENT_USD_PER_GPU_H:g} rental"),
            "Mixture of experts: 17B active parameters, so cheaper to train and to run than a dense 400B model.", [SRC["meta4"]]),
        run("DeepSeek V3", "DeepSeek", 2024, True, "2,048-GPU cluster of DeepSeek / High-Flyer (city not disclosed)",
            "China", "NVIDIA H800 (2.788M GPU hours)", round(F.GRID_CN.mid * 1000), round(2.788e6 * F.TRAIN_GPU_KW.mid * F.TRAIN_PUE.mid / 1000),
            val(ds["t_co2"], kind="derived", label=ds["calc"]),
            val(5.576, label="DeepSeek: final run at $2 per GPU hour; SemiAnalysis puts total hardware spend near $1.6B"),
            "The $5.6M covers the final run only, not research and failed runs.",
            [SRC["dsv3"], "theregister.com/2025/09/19/deepseek_cost_train", "newsletter.semianalysis.com/p/deepseek-debates"]),
        run("BLOOM (176B)", "BigScience / Hugging Face", 2022, True, "Jean Zay supercomputer (IDRIS), near Paris", "France",
            "NVIDIA A100", 57, 433, val(24.7, 50.5, "published", "24.7 t electricity only; 50.5 t incl. manufacturing and idle"),
            None, "Low-carbon nuclear grid (57 g/kWh): the cleanest large training run on record.",
            ["Luccioni et al. 2023, 'Estimating the Carbon Footprint of BLOOM', JMLR 24, jmlr.org/papers/v24/23-0069.html"]),
        run("Apertus 70B", "Swiss AI (EPFL, ETH, CSCS)", 2025, True, "CSCS Alps supercomputer, Lugano", "Switzerland",
            "NVIDIA GH200 (about 6M GPU hours)", round(F.GRID["CH_consumption"].mid * 1000), 5000,
            val(470, kind="derived", label="5,000 MWh × Swiss consumption mix; near zero market-based (hydropower)"),
            val(rent(6.0), kind="derived", label=f"6M GPU hours × ${RENT_USD_PER_GPU_H:g} rental; in practice public research compute"),
            "Lake-water cooling and hydropower; fully open training data.", [SRC["apertus"]]),
        run("Mistral Large 2", "Mistral AI", 2024, True, "Not disclosed (Mistral now trains at Eclairion, Essonne, France)",
            "France / EU", "NVIDIA GPUs", None, None,
            val(20400, kind="published", label="life cycle: training and 18 months of use"), None,
            "The only maker with a full life-cycle study (Carbone 4, ADEME): 1.14 g CO2e per 400-token answer.",
            [SRC["mistral_lca"], "datacenterdynamics.com (Eclairion hosts the Mistral AI cluster)"]),
        run("Gemini Ultra", "Google", 2023, False, "TPU SuperPods in several Google data centres (sites not disclosed)",
            "United States and others", "Google TPU v4", None, None, None,
            val(30, 191, "estimate", "Epoch AI about $30M, Stanford AI Index about $191M"),
            "Trained across several data centres at once; Google matches its electricity with clean energy contracts.",
            ["Gemini technical report (via datacenterdynamics.com)", "Stanford AI Index 2024"]),
        run("Claude (recent models)", "Anthropic", 2025, False, "AWS Project Rainier: Indiana, Pennsylvania, Mississippi; also Google TPUs",
            "United States", "AWS Trainium2 (about 500,000 chips)", None, None, None, None,
            "Rainier mainly serves answers; training runs use part of it, often at night. Model costs and emissions are not disclosed "
            "(the $11B is the whole campus).",
            ["aboutamazon.com (Project Rainier)", "semafor.com/article/10/29/2025"]),
    ]


def workload(r: dict) -> dict:
    """The company's API token workload in the baseline year (per month), and its growth per year."""
    ai = r["ai"]
    bl = ai[(ai.date >= "2025-09-01") & (ai.date <= "2026-08-31")]
    bug = (ai.resource_id == "ai-marketing") & (ai.date >= "2026-03-17") & (ai.date <= "2026-03-19")   # T-1212
    clean = bl[~bug.loc[bl.index]]
    per_month = lambda d: {k: float(d[c].sum() / 12) for k, c in
                           (("tokens_in", "tokens_in"), ("tokens_cached", "tokens_in_cache"), ("tokens_out", "tokens_out"))}
    tot = lambda d: float(d.tokens_in.sum() + d.tokens_out.sum())
    ai_ok = ai[~bug]
    a = ai_ok[(ai_ok.date >= "2024-11-01") & (ai_ok.date <= "2025-08-31")]
    b = ai_ok[(ai_ok.date >= "2025-11-01") & (ai_ok.date <= "2026-08-31")]
    growth = tot(b) / tot(a) - 1 if tot(a) else 0.0
    fx = r["fx"]
    usd_chf = float(fx[(fx.month >= "2025-09-01") & (fx.month <= "2026-08-31")].usd_chf.mean())
    by_model = []
    for model, d in clean.groupby("model"):
        by_model.append({"model": model, **per_month(d), "cost_chf": float(d.cost_chf.sum() / 12)})
    simple = clean[clean.task_type.isin(["Classify", "Summarise", "Translate"])]
    return {"per_month": per_month(clean), "cost_chf_month": float(clean.cost_chf.sum() / 12), "by_model": by_model,
            "simple_share": float(tot(simple) / tot(clean)) if tot(clean) else 0.0,
            "growth": growth, "damping": 0.5, "usd_chf": usd_chf,
            "growth_source": "ai_usage.csv: tokens Nov-Aug year on year, endless-loop days T-1212 excluded; "
                             "year 2 grows at half, year 3 at a quarter of the rate (as in the forecast)"}


def price_check(cat: list[dict], wl: dict) -> list[dict]:
    """Do the official prices explain the AI invoice? Formula cost vs ai_usage.csv cost, per model in use."""
    out = []
    for m in cat:
        rows = [x for x in wl["by_model"] if x["model"] in m["uses"]]
        if not rows or m["price_in"] is None:
            continue
        tin, tca, tout, paid = (sum(x[k] for x in rows) for k in ("tokens_in", "tokens_cached", "tokens_out", "cost_chf"))
        calc = ((tin - tca) * m["price_in"] + tca * (m["price_cached"] or m["price_in"]) + tout * m["price_out"]) / 1e6 * wl["usd_chf"]
        out.append({"id": m["id"], "name": m["name"], "formula_chf_month": calc, "invoice_chf_month": paid,
                    "ratio": calc / paid if paid else None})
    return out


def build(r: dict) -> dict:
    cat = catalogue()
    wl = workload(r)
    return {
        "models": cat, "training_runs": training_runs(), "rent_usd_per_gpu_h": RENT_USD_PER_GPU_H, "workload": wl, "price_check": price_check(cat, wl), "size_class": SIZE_CLASS, "sources": SRC,
        "energy": {"per_b_active": {s: F.WH_PER_1K_OUT_PER_B_ACTIVE.get(s) for s in ("low", "mid", "high")},
                   "input_weight": {s: F.INPUT_TOKEN_WEIGHT.get(s) for s in ("low", "mid", "high")},
                   "cache_weight": F.CACHE_WEIGHT, "source": F.WH_PER_1K_OUT_PER_B_ACTIVE.source,
                   "note": F.WH_PER_1K_OUT_PER_B_ACTIVE.note},
        "grids": {"EU": {"label": "EU (mixed)", **{s: F.GRID["EU"].get(s) for s in ("low", "mid", "high")}},
                  "US": {"label": "United States", **{s: F.GRID_US.get(s) for s in ("low", "mid", "high")}},
                  "CH": {"label": "Switzerland", **{s: F.GRID["CH_consumption"].get(s) for s in ("low", "mid", "high")}},
                  "DE": {"label": "Germany", **{s: F.GRID["DE"].get(s) for s in ("low", "mid", "high")}}},
        "anchors": [
            {"what": "Google Gemini, median text prompt (2025)", "value": "0.24 Wh, 0.03 g CO₂e",
             "source": "cloud.google.com/blog/products/infrastructure/measuring-the-environmental-impact-of-ai-inference"},
            {"what": "Mistral Large 2 in Le Chat, one 400-token answer", "value": "1.14 g CO₂e (life cycle)", "source": SRC["mistral_lca"]},
            {"what": "Llama 3.1 8B / 70B on H100 (GPU only, best setting)", "value": "19.5 / 104 Wh per 1M output tokens",
             "source": "leadgreen.ai/index (ML.ENERGY measurements)"},
        ],
        "flat_factor_wh_per_1k": F.KWH_PER_1000_TOKENS_LARGE.mid * 1000,
    }
