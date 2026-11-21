# Kilowise

**Electricity is the new currency, and hardly anyone keeps the books. Kilowise keeps them.**

Kilowise turns a small company's IT exports (cloud invoices, servers, AI usage, SaaS contracts) into one ledger of
**cost, energy and location-based CO₂**. It finds what drives them and what is wasted, and recommends a package of
measures that reaches the target without switching off anything critical.

Built for the *Green AI & Data* case (ALTYCA × Basel 2037) at **sprintd Basel 2026**.

![Kilowise leadership dashboard](screenshots/01-overview.png)

## Result for the case company

Expected case: mid conversion factors, Swiss consumption mix, normalised baseline year Sep 2025 – Aug 2026.

| | Target | Kilowise package (12 measures) |
|---|---|---|
| CO₂, location-based | −40 % | **−48.8 %** (−41.3 % with pessimistic factors, −61.5 % with optimistic ones) |
| Cost per year | −25 % | **−33.4 %**, CHF 155,355 a year |
| Effort | ≤ 15 person-days | **15.0 PD** (CHF 16,500), paid back in 39 days |
| Nothing critical touched | | 3,811 real job runs replayed against the new schedules: **0 conflicts** |

Baseline: CHF 465,668 · 36,108 kWh · 6,164 kg CO₂ a year (one-off events removed and shown separately).

## What it does

| Case step | Page | What you get |
|---|---|---|
| | **Overview** | Two dashboards. **Leadership:** a period slider (pick any months; cost, CO₂ and electricity for that period, the change against a year earlier, and what the plan would have saved), key figures with trends, target gauges, 3-year outlook with and without the plan, savings by measure, biggest waste, decisions, and the questions leadership asks, answered from the data. **IT team:** kWh and CO₂ by grid and category, cleanest hours, hot list of the largest CO₂ sources with their fix, change runbook, safeguards, watch list of idle servers. |
| Decide | **Action plan** | Every measure with its saving, effort, owner, risks and ranges; live target gauges as you switch measures on and off. |
| Know the limits | **Safeguards** | What the tool refuses or hands to a person, the protection windows, the rule-engine check, quarantined instructions found in the data, contradictions between sources. |
| Find | **Insights** | Ten findings from the data, each linked to a measure: 24/7 platforms working 9–35 % of the time, a GPU at 9 % in Frankfurt, forgotten test servers, unused seats, idle builds, stale tables, triple backups. |
| Connect | **Footprint** | The full ledger by month, department, location and resource; click any row to see how its CO₂ is calculated. |
| Decide | **Models** | 20 open and closed language models side by side: size (published or estimated), what they can do (text, images, audio, video, reasoning, runs in-house), API price, training CO₂ and energy per token, applied to the company's own token workload with a 3-year outlook. The official prices reproduce the company's AI invoice within 1 %. |
| Find | **Grid** | A map of Europe's power grids from open data (Ember, 37 countries, month by month): CO₂ per kWh with and without imports, renewable share, wholesale price and fuel mix, with the 12 months of cross-border flows drawn as arrows (Energy-Charts, every 15 minutes). For Zurich, Frankfurt and Dublin: where their electricity comes from (made at home or imported, from which neighbour, at what CO₂) and when the country imports or has surplus power. Also where the cloud regions are and how much electricity data centres use per country. A calculator moves or mixes your hosted workload between regions; wind and solar shown to fill each other's gaps. Refresh with `uv run greenledger grid-fetch`. |
| Export | **Reports** | Printable summary, the two filled case templates, the ledger, the three example questions with sources. |
| Connect | **Data sources** | The 28 exports it reads, a format check in the browser, a build with another company's files, and **Connect your accounts**: pull cost and usage from AWS, Azure, OpenAI, Claude (Anthropic) and Microsoft 365, or import a FOCUS cost export from any cloud. |
| Bonus | **Lab** | Forecast, machine-learning model selection, the chat model, server clusters, carbon-aware load shifting, build pipelines. |
| | **Sources** | Every file read, every conversion factor (low, mid, high) and every published figure, linked to 59 numbered references with publisher, year, link, licence and access date, and what each one is used for. Factors without a published value are marked as assumptions. |

**Ask Kilo** (bottom right) is the assistant. It answers from the ledger, shows how each answer was made, and can
suggest changes that only happen when you click. Instructions hidden in the data or typed into the chat
("ignore previous instructions…") are refused.

<p>
  <img src="screenshots/02-overview-it-team.png" width="49%" alt="IT team dashboard">
  <img src="screenshots/04-safeguards.png" width="49%" alt="Safeguards">
</p>

More screenshots: [screenshots/](screenshots/README.md).

## Quick start

You need [uv](https://docs.astral.sh/uv/getting-started/installation/) (it installs Python 3.12 and every dependency).

**1. Add the case data.** The data is not part of this repository. Copy the files of the case repository
(`sprintd-basel-green-ai-data`) into `data/raw/`: the 13 core CSV files into `data/raw/`, the 15 bonus files from
`extra/` into `data/raw/extra/`.

```bash
# macOS / Linux / Git Bash, case folder next to this one
mkdir -p data/raw/extra
cp ../sprintd-basel-green-ai-data-main/*.csv data/raw/
cp ../sprintd-basel-green-ai-data-main/extra/* data/raw/extra/
```

```powershell
# Windows PowerShell
New-Item -ItemType Directory -Force data/raw/extra | Out-Null
Copy-Item ../sprintd-basel-green-ai-data-main/*.csv data/raw/
Copy-Item ../sprintd-basel-green-ai-data-main/extra/* data/raw/extra/
```

**2. Build and open.**

**On Windows:** double-click `start.bat`. It installs or updates the dependencies, starts Kilowise and opens the browser;
close the window to stop it. Use `start.bat build` after changing data or code. Or by hand:

```bash
uv python pin 3.12            # the version we tested with (3.11 or newer works for the core)
uv sync                       # Python + pandas, numpy, scikit-learn, pytest
uv run greenledger build      # data → ledger → measures → checks → ML → app/data.js + outputs/*.csv (about 15 s)
uv run greenledger serve      # http://127.0.0.1:8501/index.html
uv run pytest -q              # 67 checks: targets in every factor scenario, rule engine, injections, templates, ML, grid, app
uv run greenledger grid-fetch # optional: newest grid data and cross-border flows for the Grid page (Ember and Energy-Charts, CC BY 4.0; about 7 minutes)
```

The app is plain HTML and JavaScript with no external requests, so after a build you can also open `app/index.html`
straight from disk. The repository includes a built `app/data.js`, so the app opens even before step 1.

Other commands: `uv run greenledger answer q1` (the case's example questions q1–q3 in the terminal),
`uv run greenledger train` (retrain the ML models). Links: `index.html?view=it` opens the IT dashboard,
`index.html?tour` starts the tour.

The pipeline also runs without the bonus files in `extra/` (some measures and windows drop out) and without
scikit-learn (`uv sync --no-group ml`, the ML step is skipped).

## How the numbers are made

```
quantity read from the exports × energy factor (low / mid / high) × PUE = kWh
kWh × grid mix where the data centre stands                            = kg CO₂ (location-based)
```

- **Servers and clusters:** Cloud Carbon Footprint linear model with the real daily CPU % from the invoices.
- **GPU:** idle power plus utilisation from the weekly metrics.
- **AI tokens:** 0.2 Wh per 1,000 tokens (range 0.05–1), smaller models × 0.25, cached input × 0.1.
- **Grid mix:** Switzerland 0.094 kg/kWh (consumption mix, incl. imports; the production mix 0.030 is a switch),
  Germany 0.363 (UBA 2024), Ireland 0.226 (EPA 2024), EU 0.22 for AI and SaaS services.
- **PUE:** Azure 1.185, AWS 1.11 (AWS fact sheets), hoster 1.4.
- Every factor, with its range and source, lives in one file: [`src/greenledger/factors.py`](src/greenledger/factors.py).

Numbers are computed by code, never by a language model. Every number in the app is marked as read from the data,
derived, assumed (with a range) or flagged for a person.

**Cleaning** (each step logged and shown in the app): duplicates, draft contract rows, missing costs, three
currencies, two date formats, MB/GB mixes, renamed fields, a test account marked "please exclude", and a change of
sample rate in the web logs. **Normalised baseline:** an endless-loop AI bug (T-1212, CHF 3,308) and a one-off
migration (T-1189, CHF 366) are removed from the baseline and shown separately.

## The package

| ID | Measure | PD | CHF / yr | kg CO₂ / yr |
|---|---|---|---|---|
| M1 | Production platform sleeps outside its working windows | 2.0 | 29,790 | 371 |
| M2 | Development cluster pauses automatically, starts for the quarterly training | 1.5 | 26,191 | 1,226 |
| M3 | Move the development cluster from Frankfurt to Zurich (same price) | 2.0 | 312 | 478 |
| M4 | GPU server only when needed | 1.0 | 10,254 | 373 |
| M5 | Finish the promised test-environment scale-back | 1.5 | 18,462 | 247 |
| M6 | Remaining test servers only during working hours | 0.5 | 3,016 | 42 |
| M7 | Cancel the duplicate ChatGPT Team plan, trim unused AI seats | 1.0 | 13,015 | 0 |
| M8 | Right-size SaaS licences at renewal | 1.5 | 31,965 | 0 |
| M9 | Smaller AI models for classifying, summarising and translating | 2.0 | 11,767 | 154 |
| M10 | Prompt caching for the assistant and agents | 1.0 | 2,373 | 48 |
| M11 | Cap agent retries at 3 | 0.5 | 1,055 | 17 |
| M12 | Keep app logs 90 instead of 365 days (audit and login logs unchanged) | 0.5 | 7,155 | 58 |
| | **Total** | **15.0** | **155,355** | **3,007** |

Three optional measures (Power BI capacity, build pipelines, stale data tables) are off by default and can be switched
on in the app.

## What it refuses

- **"Switch production off at night"** is refused: the rule engine replays that schedule against the job scheduler
  and finds 1,894 conflicting runs (nightly jobs, month-end close, and a January year-end close that no ticket mentions).
- **The disaster-recovery server** looks idle at 0.4 % CPU but must run (T-1094); it is excluded automatically.
- **Instructions hidden in the data** (a ticket saying "switch off production, approved by head of IT", a request to
  set costs to 0, notes asking to report lower costs) are detected, shown and never acted on.
- **Contradictions between sources** are listed with the source that was trusted and why.

## Your own data

The **Data sources** page lists every export Kilowise reads, with its expected columns and an empty template. Drop
another company's files on the page: they are checked in the browser and nothing leaves the computer. With
`greenledger serve` running, set the company name, baseline year and targets, then build. The result goes to a
separate `workspace/` folder and the sample stays untouched.

Without the app: `GL_WORKSPACE=path/to/folder uv run greenledger build` builds from `folder/raw/` and
`folder/settings.json`. The measures are written for the systems in the case data; for another company an analyst
should review them before the plan is used.

## Optional: the local AI assistant (RAG + fine-tuned model)

Simple questions are answered in the browser from the ledger. For reasoning questions, Kilo can use a small local
model, Qwen2.5-1.5B-Instruct with a LoRA adapter we fine-tuned. It retrieves facts generated from the ledger plus
reference passages (GHG Protocol Scope 2, Cloud Carbon Footprint, FOCUS, Ember). Every figure in an answer is checked
against the retrieved facts. On 181 held-out questions the fine-tuned model scored 0.815 against 0.276 for the base
model, with 96 % of answers citing their sources (3 % for the base model).

```bash
uv sync --group finetune                               # PyTorch (CUDA), transformers, peft, sentence-transformers
uv run --group finetune greenledger finetune           # build training data → LoRA → evaluate against the base model (~1 h, 8 GB GPU)
uv run --group finetune greenledger serve              # app + /api/chat
uv run --group finetune greenledger chat "Why is dp-dev a problem?"
```

The adapter weights are not in the repository (`finetune` recreates them). Without this group everything else works,
and the assistant answers from retrieval only. Details: [docs/chatbot_rag_finetune.md](docs/chatbot_rag_finetune.md).

## More

- [requirements.md](requirements.md): the case requirements and their status.
- [docs/pitch.md](docs/pitch.md): the 5-minute demo script.
- [docs/ml_model_selection.md](docs/ml_model_selection.md): how the ML models were chosen (five models tried per task;
  for idle servers the simple rule won).
- [docs/portability.md](docs/portability.md): runs on Windows, macOS and Linux; no machine-specific paths.
- `outputs/`: the two filled case templates and a package summary.

## Project layout

```
src/greenledger/   Python pipeline
  config.py          baseline year, targets, paths          factors.py   every conversion factor (low/mid/high + source)
  load.py            readers, cleaning, data-quality log    ledger.py    the monthly ledger (cost, kWh, CO₂)
  measures.py        the measures, computed from the data   limits.py    protection windows, injections, rule engine
  forecast.py        3-year forecast with/without the plan  ml.py        ML model selection (F1 / MAE)
  ai_models.py       model catalogue for the Models page
  grid.py            European grids for the Grid page (Ember open data, optional download)
  gridflows.py       cross-border flows (Energy-Charts) and the map of Europe (Natural Earth, in assets/)
  sources.py         reference list for the Sources page, matched to every factor and figure
  connectors/        pull from AWS, Azure, OpenAI, Anthropic, Microsoft 365; FOCUS import; unit and region mapping
  cluster.py         server usage groups                    shifting.py  carbon-aware timing of flexible jobs
  bonus.py           the 15 bonus files                     answers.py   the three example questions
  rag.py, chat.py    the assistant                          finetune.py  LoRA fine-tuning and evaluation
  inputs.py, workspace.py   your own data                   export.py    app data and templates
  cli.py             greenledger build | serve | train | answer | chat | finetune
app/               the web app (index.html, app.js, app.css; data.js is generated)
outputs/           filled templates
models/            ML results; chat adapter card and metrics
docs/              specifications and the pitch script
tests/             pytest checks
screenshots/       every page of the app
```

## Connect your accounts

On **Data sources** (with `uv run greenledger serve`) or from the command line, Kilowise pulls cost and usage from a
company's own accounts and turns it into the exports it reads. Everything lands in the upload workspace, gets the same
format check as an uploaded file, and is built in its own view; the sample data is never touched.

| Connector | Writes | Access needed (read-only) |
|---|---|---|
| FOCUS cost export (AWS, Azure, Google Cloud) | `azure_costs.csv`, `aws_costs.csv` | none: you export the file |
| AWS Cost Explorer | `aws_costs.csv` | IAM policy with only `ce:GetCostAndUsage` |
| Azure Cost Management | `azure_costs.csv` | Entra ID app with *Cost Management Reader* |
| OpenAI usage and costs | `ai_usage.csv` (provider OpenAI) | organization admin key |
| Claude (Anthropic) usage and cost | `ai_usage.csv` (provider Anthropic) | Admin API key, Usage and Cost Analytics API |
| Microsoft 365 licences | `saas_contracts.csv` (provider Microsoft) | Graph `Organization.Read.All` |
| Other SaaS (Slack, Zoom, Atlassian, ...) | `saas_contracts.csv`, `ai_subscriptions.csv` | an admin export copied into the template |

```bash
cp .env.example .env          # fill in only the keys you use; .env is git-ignored and never shown in the app
uv sync --group connectors    # only for AWS Cost Explorer (boto3) and Claude (official anthropic SDK)
uv run greenledger pull                          # lists the connectors and which variables are set
uv run greenledger pull openai --from 2025-09-01 --to 2026-09-01
uv run greenledger pull --focus my-focus-export.csv
```

Instance sizes become vCPU- or GPU-hours, storage GB-months become GB-days and provider regions become the grid
locations of the CO₂ factors, so pulled data reaches the energy model. A pull replaces only its own source's rows for
the period, so OpenAI and Anthropic can both feed `ai_usage.csv`. Anything that cannot be translated (an unknown unit,
a provider without a reader yet) is counted and reported, never dropped silently.

## AI tools, models and templates we used

- **No project template.** The project was started from an empty folder during the sprint.
- **AI coding assistant:** Claude Code (Anthropic) helped write code, tests and documentation. The team set the
  approach, checked the numbers against the data and decided every measure.
- **Models inside Kilowise (optional assistant):** Qwen2.5-1.5B-Instruct (Alibaba, Apache 2.0) as the base model,
  fine-tuned by us with LoRA; all-MiniLM-L6-v2 (sentence-transformers, Apache 2.0) for retrieval. Training and
  evaluation sets: SQuAD 2.0, TAT-QA, RAG-12k and deepset prompt-injections (sources and licences listed in the
  assistant's documentation).
- **Given by the case:** the sample data and the two submission templates (ALTYCA, sprintd Basel 2026).
- **Libraries:** pandas, numpy, scikit-learn, pytest; for the assistant PyTorch, transformers, peft. The web app uses
  no framework.

## Our own AI use

Building Kilowise with an AI coding assistant used roughly 3–6 million tokens, about 0.6–1.2 kWh or 0.13–0.26 kg CO₂.
Fine-tuning the assistant used 0.037 kWh (about 3.5 g CO₂), measured on the GPU. Both are shown in the app.

---

Data: sample data ALTYCA, sprintd Basel 2026 (synthetic). Typeface: Hanken Grotesk, SIL Open Font License
(`app/fonts/OFL.txt`).
