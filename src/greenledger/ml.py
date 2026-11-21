"""Predictive analysis: train several models per task, keep the best one (docs/ml_model_selection.md).

Task 1, classification (selected by F1): will a server RUN IDLE in most of the next 4 weeks?
        idle week = running more than half the week (uptime > 84 h) at < 5 % CPU: we pay for it, it does nothing.
        Features use only the current and past weeks, so the label is never visible to the model.
Task 2, regression (selected by MAE): daily cost per bucket (cloud, dp-prod, servers, AI), walk-forward validated,
        forecast to August 2029. F1 / accuracy do not apply to numbers.

Rules: time-based splits only (no shuffling); a model is kept only if it beats the simple baseline; fixed seeds;
results and fitted models are written under models/ (relative to the project). Requires the optional `ml` group.
"""
from __future__ import annotations

import hashlib
import json
import time
import warnings

from pathlib import Path

import numpy as np
import pandas as pd

from . import load
from .config import EXTRA, MODELS_DIR, RAW

MODELS = MODELS_DIR
RESULTS = MODELS / "ml_results.json"
SEED = 42
PROTECTED = {"dr-failover"}          # W5: idle by design, never a waste candidate
IDLE_CPU, RUN_H, HORIZON = 5.0, 84, 4
TRAIN_END = pd.Timestamp("2026-08-31")
FORECAST_END = pd.Timestamp("2029-08-31")
YEARS = [("2026/27", "2026-09-01", "2027-08-31"), ("2027/28", "2027-09-01", "2028-08-31"),
         ("2028/29", "2028-09-01", "2029-08-31")]
INPUTS = ["server_metrics_weekly.csv", "server_inventory.csv", "azure_costs.csv", "aws_costs.csv", "hoster_invoice.csv",
          "ai_usage.csv", "data_platform_usage.csv", "business_calendar.csv"]


def available() -> bool:
    """True if the optional `ml` group is installed. Checks without importing (importing sklearn costs ~1 s)."""
    from importlib.util import find_spec
    return all(find_spec(m) is not None for m in ("joblib", "sklearn"))


def fingerprint() -> str:
    h = hashlib.sha1()
    for f in INPUTS:
        h.update((RAW / f).read_bytes())
    for f in ("headcount.csv",):
        if (EXTRA / f).exists():
            h.update((EXTRA / f).read_bytes())
    h.update(Path(__file__).read_bytes())          # retrain when the ML code changes
    return h.hexdigest()[:16]


# ------------------------------------------------------------------------------------------
# shared helpers
# ------------------------------------------------------------------------------------------
def _candidates_clf():
    from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.neighbors import KNeighborsClassifier
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.tree import DecisionTreeClassifier
    return {   # ordered from simple to complex (tie-breaker)
        "Logistic regression": make_pipeline(StandardScaler(), LogisticRegression(max_iter=3000, class_weight="balanced")),
        "Decision tree": DecisionTreeClassifier(max_depth=5, class_weight="balanced", random_state=SEED),
        "k-nearest neighbours": make_pipeline(StandardScaler(), KNeighborsClassifier(n_neighbors=15)),
        "Random forest": RandomForestClassifier(n_estimators=300, min_samples_leaf=3, class_weight="balanced",
                                                random_state=SEED, n_jobs=1),
        "Gradient boosting": HistGradientBoostingClassifier(random_state=SEED, class_weight="balanced"),
    }


def _candidates_reg():
    from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
    from sklearn.linear_model import LinearRegression, Ridge
    from sklearn.neighbors import KNeighborsRegressor
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    return {
        "Linear trend": make_pipeline(StandardScaler(), LinearRegression()),
        "Ridge regression": make_pipeline(StandardScaler(), Ridge(alpha=10.0)),
        "k-nearest neighbours": make_pipeline(StandardScaler(), KNeighborsRegressor(n_neighbors=10)),
        "Random forest": RandomForestRegressor(n_estimators=300, min_samples_leaf=5, random_state=SEED, n_jobs=1),
        "Gradient boosting": HistGradientBoostingRegressor(random_state=SEED),
    }


# ------------------------------------------------------------------------------------------
# Task 1: idle-server classifier
# ------------------------------------------------------------------------------------------
def server_weeks(r: dict) -> pd.DataFrame:
    inv = r["inventory"][["server_id", "vcpu", "ram_gb", "type", "provider", "environment"]]
    m = r["metrics"].merge(inv, on="server_id", how="left").sort_values(["server_id", "week_start"]).reset_index(drop=True)
    m["gpu_avg_pct"] = m.gpu_avg_pct.fillna(0.0)
    m["network_gb"] = m.network_gb.fillna(0.0)
    m["idle"] = ((m.cpu_avg_pct < IDLE_CPU) & (m.uptime_h > RUN_H)).astype(int)
    g = m.groupby("server_id")
    for c in ("cpu_avg_pct", "cpu_max_pct", "uptime_h", "idle"):
        m[f"{c}_r4"] = g[c].transform(lambda s: s.rolling(4, min_periods=1).mean())
    prev = g.cpu_avg_pct.transform(lambda s: s.shift(4).rolling(4, min_periods=1).mean())
    m["cpu_trend"] = (m.cpu_avg_pct_r4 - prev).fillna(0.0)
    woy = m.week_start.dt.isocalendar().week.astype(float)
    m["woy_sin"], m["woy_cos"] = np.sin(2 * np.pi * woy / 52), np.cos(2 * np.pi * woy / 52)
    fut = g.idle.transform(lambda s: s.rolling(HORIZON, min_periods=HORIZON).mean().shift(-HORIZON))
    m["label"] = np.where(fut.isna(), np.nan, (fut >= 0.5).astype(float))
    return m


# No week-of-year features: one year of history cannot teach seasonality (models overfit 2025's March tests).
NUM_FEATS = ["cpu_avg_pct", "cpu_max_pct", "ram_avg_pct", "uptime_h", "network_gb", "gpu_avg_pct", "cpu_avg_pct_r4",
             "cpu_max_pct_r4", "uptime_h_r4", "idle", "idle_r4", "cpu_trend", "vcpu", "ram_gb"]
CAT_FEATS = ["type", "provider", "environment"]


def _X(df: pd.DataFrame, cols: list[str] | None = None) -> pd.DataFrame:
    x = pd.concat([df[NUM_FEATS].astype(float), pd.get_dummies(df[CAT_FEATS].fillna("na"), dtype=float)], axis=1)
    return x.reindex(columns=cols, fill_value=0.0) if cols is not None else x


def _clf_scores(y, p) -> dict:
    from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score
    return {"f1": float(f1_score(y, p, zero_division=0)), "accuracy": float(accuracy_score(y, p)),
            "precision": float(precision_score(y, p, zero_division=0)), "recall": float(recall_score(y, p, zero_division=0))}


def train_classifier(r: dict) -> dict:
    import joblib
    m = server_weeks(r)
    # Population: always-on servers (ran > 84 h/week on average over the last 4 weeks). Part-time servers are off
    # most of the week, so "running idle" does not apply; including them caused a population shift (the sandbox
    # dev servers appear only after the training period) that made every model flag them.
    cand = m.uptime_h_r4 > RUN_H
    lab = m[cand & m.label.notna() & ~m.server_id.isin(PROTECTED)].copy()
    lab["label"] = lab.label.astype(int)
    tr = lab[lab.week_start <= "2026-01-26"]                                     # labels end ~2026-02-23
    va = lab[(lab.week_start >= "2026-03-02") & (lab.week_start <= "2026-05-04")]
    te = lab[lab.week_start >= "2026-06-01"]
    cols = list(_X(lab).columns)
    baselines = {
        "Baseline: persistence (idle this week)": lambda d: d.idle.values,
        "Baseline: rule (idle in ≥ 2 of the last 4 weeks)": lambda d: (d.idle_r4 >= 0.5).astype(int).values,
    }
    board = []
    for name, f in baselines.items():
        board.append({"model": name, "kind": "baseline", "val": _clf_scores(va.label, f(va)),
                      "test": _clf_scores(te.label, f(te)), "fit_s": 0.0})
    fitted = {}
    for name, est in _candidates_clf().items():
        t0 = time.perf_counter()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            est.fit(_X(tr, cols), tr.label)
        fitted[name] = est
        board.append({"model": name, "kind": "ml", "val": _clf_scores(va.label, est.predict(_X(va, cols))),
                      "fit_s": round(time.perf_counter() - t0, 3)})
    order = {b["model"]: i for i, b in enumerate(board)}
    best = max(board, key=lambda b: (round(b["val"]["f1"], 4), -order[b["model"]]))
    best_base = max((b for b in board if b["kind"] == "baseline"), key=lambda b: b["val"]["f1"])
    keep_ml = best["kind"] == "ml" and best["val"]["f1"] > best_base["val"]["f1"]
    chosen = best if keep_ml else best_base
    if keep_ml:   # refit on train + validation, report the untouched test period once
        from sklearn.base import clone
        est = clone(_candidates_clf()[chosen["model"]])
        trva = pd.concat([tr, va])
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            est.fit(_X(trva, cols), trva.label)
        chosen["test"] = _clf_scores(te.label, est.predict(_X(te, cols)))
        final = clone(_candidates_clf()[chosen["model"]])
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            final.fit(_X(lab, cols), lab.label)                                   # production model: all labels
        (MODELS / "classifier").mkdir(parents=True, exist_ok=True)
        joblib.dump({"model": final, "columns": cols}, MODELS / "classifier" / "best_model.joblib")
    if not keep_ml:   # record the chosen rule, so models/classifier always holds the selection
        (MODELS / "classifier").mkdir(parents=True, exist_ok=True)
        joblib.dump({"model": None, "baseline": chosen["model"], "columns": cols},
                    MODELS / "classifier" / "best_model.joblib")
    for b in board:
        b["selected"] = b["model"] == chosen["model"]
    # watch list: latest week of every server -> probability of running idle in the next 4 weeks
    last = m[m.week_start == m.week_start.max()].copy()
    if keep_ml:
        prob = final.predict_proba(_X(last, cols))[:, 1]
    else:
        prob = (baselines[chosen["model"]](last)).astype(float)
    last["prob"] = prob
    last.loc[last.server_id.isin(PROTECTED) | (last.uptime_h_r4 <= RUN_H), "prob"] = 0.0
    watch = [{"server_id": x.server_id, "type": x.type, "vcpu": int(x.vcpu), "cpu_avg_pct": float(x.cpu_avg_pct),
              "uptime_h": float(x.uptime_h), "prob": float(x.prob), "flag": bool(x.prob >= 0.5),
              "note": ("protected (W5, T-1094): never flagged" if x.server_id in PROTECTED else
                       "part-time server (not always on): not a candidate" if x.uptime_h_r4 <= RUN_H else "")}
             for x in last.sort_values("prob", ascending=False).itertuples()]
    importance = []
    if keep_ml and hasattr(final, "feature_importances_"):
        imp = pd.Series(final.feature_importances_, index=cols).sort_values(ascending=False).head(8)
        importance = [{"feature": k, "importance": float(v)} for k, v in imp.items()]
    return {
        "task": "Will an always-on server run idle (running > 84 h/week at < 5 % CPU) in most of the next 4 weeks?",
        "population": "always-on servers (uptime > 84 h/week over the last 4 weeks); dr-failover excluded (W5)",
        "metric": "F1 (positive class = idle), accuracy secondary",
        "split": {"train": f"{tr.week_start.min():%Y-%m-%d} – {tr.week_start.max():%Y-%m-%d} ({len(tr)} server-weeks)",
                  "validation": f"{va.week_start.min():%Y-%m-%d} – {va.week_start.max():%Y-%m-%d} ({len(va)})",
                  "test": f"{te.week_start.min():%Y-%m-%d} – {te.week_start.max():%Y-%m-%d} ({len(te)})"},
        "positive_share": float(lab.label.mean()), "leaderboard": board, "selected": chosen["model"],
        "kept_ml": keep_ml,
        "reason": (f"Highest validation F1 ({chosen['val']['f1']:.3f}) and better than the best baseline "
                   f"({best_base['val']['f1']:.3f})." if keep_ml else
                   f"No model beat the baseline on validation F1 ({best_base['val']['f1']:.3f}); the baseline is kept."),
        "importance": importance, "watch_list": watch, "excluded": sorted(PROTECTED),
        "latest_week": f"{m.week_start.max():%Y-%m-%d}",
    }


# ------------------------------------------------------------------------------------------
# Task 2: daily cost forecaster per bucket
# ------------------------------------------------------------------------------------------
SERVERS = {"vm-app", "vm-test", "db-fin", "gpu-ml"}
BUCKETS = ["cloud", "dp-prod", "servers", "ai"]
PER_NODE = {"dp-prod"}    # billed per node-hour: model cost per node, multiply by the (planned) node count


def daily_costs(r: dict) -> pd.DataFrame:
    az = r["azure"]
    az = az[az.ChargeType != "Credit"] if "ChargeType" in az else az     # one-off credits: real, but not recurring
    c = pd.concat([az[["date", "resource_id", "cost_chf", "quantity"]],
                   r["aws"][["date", "resource_id", "cost_chf", "quantity"]],
                   r["hoster"][["date", "resource_id", "cost_chf", "quantity"]]])
    c["bucket"] = np.where(c.resource_id == "dp-prod", "dp-prod", np.where(c.resource_id.isin(SERVERS), "servers", "cloud"))
    eg = c[c.resource_id == "net-egress"].groupby("date").quantity.sum()
    spike = set(eg[eg > 4 * eg.median()].index)                                 # T-1189 one-off migration
    a = r["ai"][["date", "cost_chf"]].assign(bucket="ai")
    d = pd.concat([c[["date", "bucket", "cost_chf"]], a]).groupby(["date", "bucket"]).cost_chf.sum().unstack(fill_value=0.0)
    d = d.reindex(pd.date_range(d.index.min(), TRAIN_END, freq="D"), fill_value=0.0)[BUCKETS]
    d = d.where(d != 0)                                                          # a day without any row = missing
    d.loc[d.index.isin(spike), "cloud"] = np.nan
    d.loc["2026-03-17":"2026-03-19", "ai"] = np.nan                             # T-1212 endless loop
    return d


def _features(idx: pd.DatetimeIndex, start: pd.Timestamp, ctx: dict) -> pd.DataFrame:
    f = pd.DataFrame(index=idx)
    f["t"] = (idx - start).days.astype(float)
    for k in range(7):
        f[f"dow{k}"] = (idx.dayofweek == k).astype(float)
    # No month-of-year features: with < 2 years of data, month is confounded with one-off steps (e.g. dp-prod ran
    # 20 nodes only Jan-Aug 2026, so models learned "Sep-Dec is cheap").
    wd = ctx["workday"].reindex(idx)
    f["workday"] = wd.fillna(pd.Series((idx.dayofweek < 5).astype(float), index=idx)).astype(float)
    f["training_day"] = ((idx.month.isin([1, 4, 7, 10])) & (idx.day <= 3)).astype(float)
    f["nodes"] = ctx["nodes"].reindex(idx).ffill().fillna(ctx["nodes"].iloc[0])
    f.loc[f.index >= "2026-10-01", "nodes"] = 24.0                              # T-1261
    # No FTE feature: it rises almost linearly, i.e. it duplicates the time trend (collinear), and a linear model
    # then gives it a meaningless negative weight. FTE growth is handled by the driver-based forecast.
    f["vm_test_64"] = (idx >= "2025-04-01").astype(float)                       # T-1058 step
    return f


def _context() -> dict:
    cal = load.calendar().set_index("date").workday.astype(float)
    dp = load.data_platform(load.DQLog())
    nodes = dp[dp.resource_id == "dp-prod"].set_index("date").node_count.astype(float).sort_index()
    hc = load.headcount()
    if hc is not None:
        t = hc.groupby("month").fte.sum().sort_index()
        yrs = (t.index[-1] - t.index[0]).days / 365.25
        cagr = (t.iloc[-1] / t.iloc[0]) ** (1 / yrs) - 1

        def fte(idx):
            s = t.reindex(t.index.union(idx)).interpolate("time").reindex(idx)
            after = idx > t.index[-1]
            yrs_after = (idx[after] - t.index[-1]).days / 365.25
            s[after] = t.iloc[-1] * (1 + cagr) ** yrs_after
            return s.bfill().values
    else:
        def fte(idx):
            return np.full(len(idx), 112.0)
    return {"workday": cal, "nodes": nodes, "fte": fte}


def _seasonal_naive(hist: pd.Series, idx: pd.DatetimeIndex) -> np.ndarray:
    """Same weekday one year (364 days) earlier; repeats the last observed year into the future."""
    h = hist.dropna()
    out = []
    for d in idx:
        src = d - pd.Timedelta(days=364)
        while src > h.index[-1]:
            src -= pd.Timedelta(days=364)
        while src not in h.index and src > h.index[0]:
            src -= pd.Timedelta(days=7)
        out.append(h.get(src, h.iloc[-7:].mean()))
    return np.array(out, dtype=float)


def _reg_scores(y, p) -> dict:
    y, p = np.asarray(y, float), np.asarray(p, float)
    ok = np.abs(y) > 0.01 * np.abs(y).mean()
    return {"mae": float(np.mean(np.abs(y - p))), "mape": float(np.mean(np.abs(y[ok] - p[ok]) / np.abs(y[ok]))),
            "total_err": float(p.sum() / y.sum() - 1)}


def train_forecaster(r: dict) -> dict:
    import joblib
    from sklearn.base import clone
    d = daily_costs(r)
    ctx = _context()
    start = d.index[0]
    X_all = _features(d.index, start, ctx)
    folds = [(TRAIN_END - pd.Timedelta(days=91 * k - 1), TRAIN_END - pd.Timedelta(days=91 * (k - 1))) for k in (3, 2, 1)]
    out = {}
    future = pd.date_range(TRAIN_END + pd.Timedelta(days=1), FORECAST_END, freq="D")
    X_fut = _features(future, start, ctx)
    # Long horizon: freeze the time trend at the last observed day. Validation covers 91 days ahead; stretching a
    # fitted trend 3 years is not validated (a linear model made dp-prod shrink while it grows to 24 nodes).
    # Growth then comes from the structural features (nodes, calendar); the driver-based forecast carries trends.
    X_fut["t"] = X_all["t"].max()
    for b in BUCKETS:
        scale_hist = X_all["nodes"] if b in PER_NODE else pd.Series(1.0, index=X_all.index)
        scale_fut = X_fut["nodes"] if b in PER_NODE else pd.Series(1.0, index=X_fut.index)
        y = d[b] / scale_hist
        board = {"Baseline: seasonal naive (same weekday last year)": {"kind": "baseline", "folds": []}}
        for name in _candidates_reg():
            board[name] = {"kind": "ml", "folds": []}
        for lo, hi in folds:
            trm = (y.index < lo) & y.notna()
            tem = (y.index >= lo) & (y.index <= hi) & y.notna()
            yt, sc = y[tem], scale_hist[tem]
            board["Baseline: seasonal naive (same weekday last year)"]["folds"].append(
                _reg_scores(yt * sc, _seasonal_naive(d[b][d[b].index < lo], yt.index)))   # naive on raw CHF
            for name, est in _candidates_reg().items():
                e = clone(est)
                e.fit(X_all[trm], y[trm])
                board[name]["folds"].append(_reg_scores(yt * sc, e.predict(X_all[tem]) * sc))
        rows = []
        for name, v in board.items():
            f = v["folds"]
            rows.append({"model": name, "kind": v["kind"], "mae": float(np.mean([x["mae"] for x in f])),
                         "mape": float(np.mean([x["mape"] for x in f])),
                         "total_err": [x["total_err"] for x in f], "folds": f})
        base = rows[0]
        best = min(rows, key=lambda x: round(x["mae"], 2))
        chosen = best if best["kind"] == "ml" and best["mae"] < base["mae"] else base
        for x in rows:
            x["selected"] = x["model"] == chosen["model"]
        fitm = y.notna()
        if chosen["kind"] == "ml":
            final = clone(_candidates_reg()[chosen["model"]])
            final.fit(X_all[fitm], y[fitm])
            pred = (pd.Series(final.predict(X_fut), index=future) * scale_fut).clip(lower=0)
            (MODELS / "forecast").mkdir(parents=True, exist_ok=True)
            joblib.dump({"model": final, "columns": list(X_all.columns)}, MODELS / "forecast" / f"{b}.joblib")
        else:
            pred = pd.Series(_seasonal_naive(d[b], future), index=future)
        err = chosen["total_err"]
        w = max(max(abs(e) for e in err), 0.05)                                  # relative band from fold totals
        years = []
        for i, (lab, a, z) in enumerate(YEARS, 1):
            mid = float(pred[a:z].sum())
            years.append({"year": lab, "mid": mid, "low": mid * (1 - w * np.sqrt(i)), "high": mid * (1 + w * np.sqrt(i))})
        bl = float(d[b]["2025-09-01":"2026-08-31"].fillna(d[b].median()).sum())
        out[b] = {"leaderboard": rows, "selected": chosen["model"], "kept_ml": chosen["kind"] == "ml",
                  "baseline_year": bl, "years": years,
                  "reason": (f"Lowest walk-forward MAE (CHF {chosen['mae']:,.0f}/day) and better than seasonal naive "
                             f"(CHF {base['mae']:,.0f}/day)." if chosen["kind"] == "ml" else
                             f"No model beat seasonal naive (MAE CHF {base['mae']:,.0f}/day); seasonal naive kept."),
                  "per_node": b in PER_NODE}
    return {"task": "Daily cost per bucket, forecast to August 2029",
            "metric": "MAE (CHF per day), MAPE secondary; walk-forward, 3 folds of 91 days",
            "folds": [f"{lo:%Y-%m-%d} – {hi:%Y-%m-%d}" for lo, hi in folds],
            "note": "Validation: 91 days ahead. For the 3-year forecast the time trend is frozen at the last observed "
                    "day; growth comes from known drivers in the features (24 nodes from Oct 2026, calendar). "
                    "Subscriptions and SaaS are monthly with known price steps: they keep the driver-based forecast.",
            "buckets": out}


# ------------------------------------------------------------------------------------------
def train(r: dict | None = None, force: bool = True) -> dict | None:
    if not available():
        print("ML step skipped: install the optional group with `uv sync --group ml`.")
        return None
    fp = fingerprint()
    if not force and RESULTS.exists():
        res = json.loads(RESULTS.read_text(encoding="utf-8"))
        if res.get("fingerprint") == fp:
            return res
    if r is None:
        from . import ledger
        r = ledger.build()
    t0 = time.perf_counter()
    MODELS.mkdir(parents=True, exist_ok=True)
    res = {"fingerprint": fp, "seed": SEED, "classifier": train_classifier(r), "forecaster": train_forecaster(r)}
    res["train_seconds"] = round(time.perf_counter() - t0, 1)
    RESULTS.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return res


def combine_forecast(ml: dict, fc: dict) -> dict:
    """ML buckets + driver-based subscriptions/SaaS -> cost, kWh, CO2 per year (kWh/CO2 via baseline intensity)."""
    bb = fc["by_bucket"]
    out = {}
    for k in ("cost", "kwh", "co2"):
        s = {"baseline": fc["series"][k]["baseline"], "mid": [0.0] * 3, "low": [0.0] * 3, "high": [0.0] * 3}
        for b, v in bb.items():
            if b in ml["forecaster"]["buckets"]:
                ys = ml["forecaster"]["buckets"][b]["years"]
                inten = v[k]["baseline"] / v["cost"]["baseline"] if v["cost"]["baseline"] else 0.0
                for i, y in enumerate(ys):
                    for q in ("mid", "low", "high"):
                        s[q][i] += y[q] * inten
            else:
                for i in range(3):
                    for q in ("mid", "low", "high"):
                        s[q][i] += v[k][f"without_{q}"][i]
        out[k] = s
    return out
