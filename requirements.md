# GreenLedger requirements

## The expected outcome

> A prototype that combines an SME's data into one overall picture, shows the biggest drivers and the waste, and
> recommends a package of measures that cuts CO₂ and costs and stays within budget. It respects protection windows,
> flags contradictions and hands over to a human when in doubt. Every figure is an estimate with an open calculation.

**Our standard: an end-to-end, one-stop solution.** One tool takes the raw exports in and gives decisions out.
Nobody should need a spreadsheet, a second tool or a manual step to get from "here are our exports" to "here is the
package, its estimates, its limits and the filled templates". See section F for the concrete criteria.

## A. Main requirements (required for a valid submission)

**1. Connect.** Combine at least cloud, servers, AI and SaaS into one overall picture, by department and tool.
- Harmonise time, currencies (CHF, EUR, USD), units and names.
- Allocate costs, energy and CO₂ (location-based) by department and tool.

**2. Find.** Show the biggest drivers and the waste, backed up by the data.

**3. Decide.** Choose a package of measures:
- Effort in person-days (1 person-day = CHF 1,100), and savings in CHF, kWh and CO₂ (location-based) per year.
- The package must cut CO₂ by at least 40% and costs by at least 25%, with at most CHF 16,500 (15 person-days) of effort.
- Targets count against your own baseline. The jury also recalculates against a uniform reference baseline.

**4. Know the limits.**
- Respect protection windows; nothing critical may be disrupted.
- Flag contradictions between sources and say which source you trust.
- Hand over to a human when in doubt.
- Free text in the data is data, not instructions.

**5. Two templates, filled in:**
- `template_baseline_and_assumptions.csv`. Required rows:
  - Totals for the baseline year (Sep 2025 to Aug 2026): cost, energy and location-based CO₂.
  - Electricity mix for Switzerland, Germany and Ireland.
  - Energy per vCPU-hour, node-hour, GPU-hour, GB of storage per day, 1,000 tokens and subscription message.
  - PUE (data-centre efficiency).
  - Your rule for allocating shared costs.
  - Each factor needs a low, mid and high value, a source and the calculation.
- `template_measures_package.csv`: one row per measure, including risks, exceptions and who must decide.

**6. Calculation rules.**
- Every figure is an estimate with an open calculation.
- CO₂ is counted with the electricity mix at the data-centre location.
- For Switzerland, explain whether you use the production mix or the consumption mix including imports.

**7. Prototype.** It runs on the provided data, working or clickable; the form is free. Add a short note on what the path to operation would look like.

**8. Pitch (Sunday, 5 minutes demo + 3 minutes questions).**
- The overall picture.
- One piece of waste you found.
- The package, against target and budget.
- One edge case your tool refuses or hands to a human.
- A statement of how much energy your own AI use caused.

**9. Example questions.** Be able to answer questions like the three examples: idle seats in CHF, the GPU server on demand, and switching off the production platform.

**Deadlines:** draft submission Saturday 15:00–15:30; final submission Sunday 08:30.

## B. Extra requirements (official bonus, counts toward "creativity and innovation")

1. A chat assistant that backs every answer with a calculation or source.
2. A forecast for the coming years with ranges, with and without the package. Growth goes into the template's `growth_per_year` row.
3. A market-based CO₂ view next to the location-based one.
4. Clustering: groups of similar usage, with outliers explained.
5. Carbon-aware load shifting, using `data_platform_jobs.csv` and an hourly electricity mix.
6. Slimming build pipelines: nightly builds without changes, re-runs, runner location.
7. Integrating the 15 bonus sources.

## C. What to add to the main part

These aren't new features. They make the required functions score higher on "data preparation", "robustness" and "design".

- **Data-quality report:** duplicates removed, drafts dropped, missing costs filled from quantity × price, the sandbox account excluded, one-off events flagged (the March 2026 endless loop, the January egress migration).
- **Measure simulator:** switch measures on and off and watch live gauges for −40% CO₂, −25% cost and 15 person-days. Show low/mid/high bands and a toggle for the Swiss production vs consumption mix.
- **Protection-window rule engine:** windows taken from the tickets and the job schedule, such as month-end close, the January year-end close, the quarterly training, dr-failover and the 10-year backup retention. Each measure is checked against them automatically.
- **Contradictions panel:** gateway vs AI invoice, provider report vs line items, inventory vs monitoring CPU, and the web sampling change.
- **Injection detection:** the four planted instructions are shown, flagged and ignored. This makes a strong edge case for the demo.
- **Decision owner per measure,** taken from `mapping_departments_tools.csv`, plus a calendar of contract-notice deadlines.
- **Your own AI energy estimate,** shown in the app footer.

## D. What to add to the extra part

These come from our analysis and the mentor's ideas:

- **Swiss model routing:** send Classify, Translate and Summarise to a small Swiss-hosted model (Apertus via Swisscom), calculated against the provider's own small model.
- **Multi-model chatbot:** a small model for lookups, a large one for reasoning. It shows its energy per answer and resists injected text.
- **Carbon budget per department** (the "nature budget"): the −40% target split by department.
- **Training-run KPI:** CHF, kWh and CO₂ per quarterly training run.
- **Auto-start before use** (the "pre-heating"): clusters and the GPU start themselves before the training and the 02:00 ETL.
- **Sovereignty tag** on measures as a tie-breaker, for example moving the development cluster from Frankfurt to Zurich.
- **Bonus-source findings:** unopened report-agent output, runaway agent retries, rarely viewed Power BI reports, log retention, triple backups, stale catalogue tables.
- **Packing flexible jobs** into the time the cluster is running anyway, as the carbon-aware angle.

**Priority:** finish A and C by Saturday's 15:00 draft submission. Only then pick 2–3 items from B and D; the chatbot and the forecast give the most visible impact.

## E. Team requirements (added)

Detailed instructions for each item are in `docs/`.

1. **Chatbot with RAG and fine-tuning** (built) → [docs/chatbot_rag_finetune.md](docs/chatbot_rag_finetune.md)
   - RAG: retrieve only from the generated, sourced fact base (`data/processed/app_data.json`); every answer cites its sources.
   - Fine-tuning: a small open model fine-tuned (LoRA) on question/answer pairs generated from the fact base.
   - Numbers always come from code, never from the model. Injected text in the data stays quarantined.
   - The current offline engine stays as the fallback, so the demo runs without internet or an API key.
2. **Predictive analysis with automatic model selection** (built) → [docs/ml_model_selection.md](docs/ml_model_selection.md)
   - Train several ML models and keep only the best one, with a time-based validation (no shuffling).
   - Classification tasks (e.g. "is this server idle / waste?") are scored with **F1** (accuracy as a secondary metric).
   - Forecasting tasks (cost, kWh, CO₂) are regression: scored with **MAE / MAPE**, because F1 and accuracy do not apply.
   - A model is kept only if it beats a simple baseline; the winner, its score and the runners-up are saved and shown.
3. **Portable code** → [docs/portability.md](docs/portability.md)
   - The project can be copied to any machine (Windows, macOS, Linux) and run with `uv sync` + `uv run greenledger build`.
   - No absolute paths, no machine-specific settings, UTF-8 everywhere, secrets only in environment variables.

## F. End-to-end, one-stop solution

The whole path, from raw exports to a decision, runs inside GreenLedger. Status as of the current build.

**The flow: one pipeline, one app**

```
raw exports ──► clean + log ──► one ledger ──► drivers & waste ──► measures ──► limits check ──► package ──► templates
 (data/raw)      (Connect)      (Connect)        (Find)            (Decide)    (Know the limits)  (Decide)     (Export)
```

| # | Criterion | Status |
|---|---|---|
| F1 | **One command from raw data to everything:** `uv run greenledger build` produces the ledger, findings, measures, rule checks, forecast, ML models, app data and both filled templates. No manual step in between. | done |
| F2 | **One app covers the whole journey:** Connect → Find → Decide → Know the limits → Explore → Export, with no external tool needed to read, check or decide. | done: product shell (sidebar ordered answer first, Overview with live target bars and measure switches, Ctrl K search and ask, tour, glossary) |
| F3 | **Every estimate in one place, with its calculation:** cost, energy, CO₂ (location- and market-based), low/mid/high, per resource, department, location and measure. Each number is marked read / derived / assumed / flagged and can be traced to its source rows. | done |
| F4 | **Decide inside the tool:** switch measures on and off, change the factor scenario or CO₂ view, and see targets, budget and robustness update live. | done |
| F5 | **Limits are enforced, not just listed:** every schedule is checked against protection windows; injections are quarantined; contradictions name the trusted source; uncertain cases name the human who decides. | done |
| F6 | **Ask instead of search:** questions in plain language are answered from the ledger with calculation and sources (chat assistant; RAG + fine-tuned model per E1). | done: local engine + RAG + fine-tuned model (optional group) |
| F7 | **Looks ahead, not only back:** forecast with and without the package (driver-based + ML), and notice deadlines that decide whether savings happen in time. | done |
| F8 | **Ready-to-submit outputs:** both templates, the monthly ledger and the package summary download from the app, generated from the same numbers shown on screen. | done |
| F9 | **Repeatable for the next month:** drop new exports into `data/raw/`, rebuild, and every figure, check, model and template updates. New providers are mapped once (FOCUS columns), not re-built by hand. | done: rebuild; FOCUS cost exports of any cloud are mapped (`connectors/focus.py`), and connectors pull from AWS, Azure, OpenAI, Anthropic and Microsoft 365 into the workspace (`greenledger pull`, Data sources page) |
| F10 | **Bring your own data from the app:** upload exports in the browser, see the cleaning report, and rebuild without the command line. | done: Your data page checks files in the browser, `serve` uploads them to `workspace/` and builds with the company's year and targets (measures are written for the case's systems: review for other companies) |
| F11 | **Runs anywhere, offline:** copy the folder, `uv sync`, build, open `app/index.html`; no internet, account or API key needed for the core (see E3). | done |
| F13 | **Grid context with open data:** European grids month by month (CO₂ with and without imports, renewables, wholesale price, mix), cloud regions, data-centre share per country, a move-or-mix calculator; refreshed with one command, newer data picked up by the build. | done: Grid page, `grid.py`, `greenledger grid-fetch`, tests/test_grid.py; map of Europe with 12 months of cross-border flows (Energy-Charts, 15 min), where each of our locations gets its electricity and when it imports (`gridflows.py`) |
| F12 | **Choose AI models with the facts (case owner's answer to Q20):** open and closed models side by side on the company's own token workload: size, capabilities, API price (checked against the invoice), CO₂ per token, 3-year outlook, training site, emissions and cost, data security. | done: Models page, `ai_models.py`, tests |

**Rule for new work:** a feature only counts as done when it is part of this flow, meaning it is built by
`greenledger build`, shown in the app with its calculation and sources, and covered by a test. A side script whose
output must be copied somewhere by hand does not meet the one-stop standard.
