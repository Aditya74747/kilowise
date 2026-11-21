# Predictive analysis: train several models, keep the best

Status: **built** (`src/greenledger/ml.py`, `uv run greenledger train`, app: Explore › ML models). The driver-based
forecast in `forecast.py` stays; the ML forecast is shown next to it as a dashed line.

## Results (data as of 2026-09-06, seed 42, ~7 s training)

**Classifier (selected by F1 on validation Mar–May 2026):** the kept model is the **baseline "idle this week stays
idle"** (val F1 0.825, test F1 0.859). Best ML model: gradient boosting, val F1 0.772. None beat the baseline, so the
rule is kept. This is the expected, robust answer for a series where idle state is very persistent. The watch list
flags exactly the servers M4/M5 already target (gpu-ml-01, build-agent-old, migration-alt, poc-ki-2024, test-01..03).

**Forecaster (selected by walk-forward MAE, 3 × 91 days):**

| Bucket | Kept model | MAE CHF/day (kept vs seasonal naive) | 2026/27 forecast |
|---|---|---|---|
| Cloud services | k-nearest neighbours | 57.8 vs 87.7 | CHF ~123k |
| Production platform (per node × nodes) | gradient boosting | 4.3 vs 48.4 | CHF ~114k (24 nodes) |
| Servers | gradient boosting | 4.8 vs 33.1 | CHF ~72k |
| AI API | gradient boosting | 13.8 vs 48.8 | CHF ~48k |

## Lessons from building it (keep these rules)

1. **No week-of-year / month features**: with < 2 years of data they are confounded with one-off steps (dp-prod ran
   20 nodes only in Jan–Aug 2026, so models learned "Sep–Dec is cheap"; test servers were busy in March 2025 only).
2. **Classifier population = always-on servers.** Part-time sandbox servers appear only after the training period;
   including them made every model flag them (population shift, F1 dropped to ~0.25).
3. **Model dp-prod per node** and multiply by the planned node count: trees cannot extrapolate to 24 nodes.
4. **No FTE feature in the daily forecaster**: it duplicates the time trend (collinear) and got a negative weight.
5. **Freeze the time trend** for the 3-year horizon: validation only covers 91 days ahead.
6. **Credits and empty days are excluded** from the training series (real money, but not recurring usage).

## Important: pick the metric that fits the task

| Task type | Example | Metric to select the model | Why |
|---|---|---|---|
| **Classification** (yes/no, category) | Is this server idle/waste? Will this job overrun its window? Will a SaaS contract fall below 80 % use? | **F1** (macro F1 for several classes); accuracy as a secondary metric | Classes are unbalanced (few waste servers), so accuracy alone looks good even for a useless model; F1 punishes that |
| **Regression / forecast** (a number) | Monthly cost, kWh, CO₂ for the next 12–36 months | **MAE** and **MAPE** (lower is better) | F1 and accuracy are not defined for numbers |

Never shuffle time-series data. Always validate on a **later** period than the one used for training.

## Task 1: waste classifier (selected by F1)

- **Unit:** server-week (`server_metrics_weekly.csv` + `server_inventory.csv`), optionally resource-day for cloud.
- **Features:** cpu avg/max, ram avg, uptime share, days since last login, vCPU, type, environment, weekday share
  of load, trend over the last 4 weeks.
- **Label:** `waste = 1` if the server is removed, scheduled or paused by an accepted measure (M4, M5, M6) or matches
  the rule "CPU < 5 % and no login for 90 days", **except** protected servers (dr-failover, W5). Labels come from
  code, so they are reproducible. Report the label rule next to the score.
- **Candidates:** logistic regression, decision tree, random forest, gradient boosting (scikit-learn
  `HistGradientBoostingClassifier`), k-nearest neighbours; plus the rule baseline above.
- **Validation:** train on weeks up to Feb 2026, validate Mar–May 2026, test Jun–Aug 2026 (time split).
  Tune on validation, report the final F1 on test once.
- **Selection:** highest validation F1; ties → simpler model. Keep it only if it beats the rule baseline.

## Task 2: cost / energy / CO₂ forecast (selected by MAE / MAPE)

- **Series:** daily cost per bucket (cloud, dp-prod, servers, AI, subscriptions, SaaS) from the ledger;
  monthly totals for reporting.
- **Features:** trend, month, weekday, working day (`business_calendar.csv`), quarter-start training days,
  node count (dp-prod), FTE (`headcount.csv`), known steps (T-1172, T-1261, price changes) as flags.
- **Candidates:** seasonal-naive baseline (same period last year), linear trend, ridge regression with calendar
  features, random forest, gradient boosting, and Holt-Winters (exponential smoothing) where the series is long enough.
- **Validation:** rolling-origin (walk-forward) cross-validation, at least 3 folds of 3 months each.
- **Selection:** lowest mean MAE across folds per bucket (MAPE shown as well). Keep a model only if it beats the
  seasonal-naive baseline, otherwise keep the baseline and say so.
- **Ranges:** prediction intervals from the fold residuals (10th–90th percentile) → low / mid / high.
- **Note:** 22 months of data are short. Expect simple models to win; that is a valid, honest result.

## Outputs (same for both tasks)

- `models/<task>/best_model.joblib`: the winning fitted model (relative path, see portability.md).
- `models/<task>/leaderboard.json`: every candidate with its metric per fold, training time, parameters, the selected
  model and the reason it was chosen. Shown in the app (Explore › Forecast / Clusters) as a small leaderboard table.
- Fixed random seeds (`random_state=42`) so results are the same on every machine.
- Dependency group `ml` (scikit-learn, joblib), installed by default (`[tool.uv] default-groups`). The core build
  still runs without it (`uv sync --no-group ml`): the ML step is skipped with a clear message. Holt-Winters
  (statsmodels) was not added: with < 2 years of daily data it has no full second season to learn from.

## Where it plugs in

- `src/greenledger/ml.py`: `train_classifier()`, `train_forecaster()`, `train()`, `combine_forecast()`.
- `uv run greenledger train` forces a retrain; `build` calls `ml.train(force=False)`, which retrains only when the
  input data or `ml.py` change (fingerprint stored in `models/ml_results.json`).
- `export.build_all()` puts the results into the app data as `ml`, and combines the ML buckets with the
  driver-based subscriptions/SaaS into `ml.forecast_total` (cost, kWh, CO₂).
- App: Explore › ML models (leaderboards, watch list) and the dashed ML line in Explore › Forecast.

## Acceptance checks (add to `tests/`)

- The leaderboard contains at least 4 candidates plus the baseline for each task.
- The selected model is the best by its metric; F1 for classification, MAE for forecasting.
- dr-failover is never predicted as waste (protected).
- Re-running `train` gives the same scores (seeded).

Implemented in `tests/test_ml.py` (skipped automatically if the `ml` group is not installed).
