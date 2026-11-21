"""Carbon-aware load shifting for the flexible jobs in extra/data_platform_jobs.csv.

Two effects, kept apart on purpose:
1. Packing: a flexible job that runs while the cluster would otherwise sleep (M1/M2 schedules) forces a wake-up.
   Moving it into hours the cluster is on anyway avoids that (checked by the rule engine).
2. Timing: inside the on-hours, start the job in the hour with the lowest grid intensity (hourly shape).
   Only the job's own extra load counts (the cluster is running anyway), so this effect is small, and we say so.
"""
from __future__ import annotations

import numpy as np

from . import factors as F
from . import load
from .config import BASELINE_END, BASELINE_START
from .limits import _h, schedule_m1, schedule_m2

REGION = {"dp-prod": "Switzerland (Zurich)", "dp-dev": "Germany (Frankfurt)"}
ALLOWED = {   # allowed start hours per flexibility rule (start, latest end)
    "flexible: within 24 h": (0, 24), "flexible: within the week": (0, 24),
    "flexible: working day 08:00 to 18:00": (8, 18), "flexible: before the next working day": (16, 24),   # after the developers' day
}


def _intensity(start: float, dur: float) -> float:
    hrs = [int(h) % 24 for h in np.arange(start, start + max(dur, 0.25), 0.25)]
    return float(np.mean([F.HOURLY_CH_SHAPE[h] for h in hrs]))


def build() -> dict | None:
    jobs = load.jobs()
    if jobs is None:
        return None
    cal = load.calendar()
    dp = load.data_platform(load.DQLog())
    nodes = dp[(dp.date >= BASELINE_START) & (dp.date <= BASELINE_END)].groupby("resource_id").node_count.mean()
    sched = {"dp-prod": schedule_m1(cal, jobs), "dp-dev": schedule_m2(cal, jobs)}
    j = jobs[(jobs.date >= BASELINE_START) & (jobs.date <= BASELINE_END) & jobs.resource_id.isin(sched)]
    flex = j[j.time_window.str.startswith("flexible") & (j.job_name != "Quarterly model training")]
    rows = []
    for (rid, job), g in flex.groupby(["resource_id", "job_name"]):
        tw = g.time_window.iloc[0]
        lo, hi = ALLOWED.get(tw, (0, 24))
        dur = float(g.duration_h.mean())
        cur = _h(g.start_time.mode()[0])
        # incremental energy of the job: nodes x 16 vCPU from idle (5 %) to busy (60 %), x PUE
        kw = nodes.get(rid, 8) * 16 * (F.vcpu_kw("Azure", 60, 4.0, "mid") - F.vcpu_kw("Azure", 5, 4.0, "mid"))
        kwh = kw * dur * len(g) * F.PUE["Azure"].mid
        grid = F.grid(REGION[rid], "mid")
        # best start: inside the allowed window AND inside the cluster's on-hours on a typical working day
        wd = next(d for d in sorted(sched[rid]) if d.weekday() == 2 and d.month == 3)
        on = sched[rid][wd]
        cands = [s / 2 for s in range(0, 48) if lo <= s / 2 and s / 2 + dur <= hi
                 and any(a <= s / 2 and s / 2 + dur <= b for a, b in on)]
        best = min(cands, key=lambda s: _intensity(s, dur)) if cands else cur
        now_i, best_i = _intensity(cur, dur), _intensity(best, dur)
        outside = int(sum(not any(a <= _h(x.start_time) and _h(x.start_time) + x.duration_h <= b
                                  for a, b in sched[rid].get(x.date, [])) for x in g.itertuples()))
        rows.append({
            "job": job, "resource_id": rid, "time_window": tw, "runs": int(len(g)), "duration_h": dur,
            "start_now": g.start_time.mode()[0], "start_best": f"{int(best):02d}:{int(best % 1 * 60):02d}",
            "kwh": float(kwh), "co2_now": float(kwh * grid * now_i), "co2_best": float(kwh * grid * best_i),
            "runs_outside_schedule": outside,
        })
    rows.sort(key=lambda x: x["co2_now"] - x["co2_best"], reverse=True)
    tot_now = sum(x["co2_now"] for x in rows)
    tot_best = sum(x["co2_best"] for x in rows)
    return {
        "jobs": rows, "hourly_shape": F.HOURLY_CH_SHAPE, "hourly_source": F.HOURLY_SOURCE,
        "grid_mid": {"Zurich": F.GRID["CH_consumption"].mid, "Frankfurt": F.GRID["DE"].mid},
        "co2_now": tot_now, "co2_best": tot_best,
        "note": "Timing inside the on-hours saves only the job's own extra load, a few kg per year. The real lever "
                "is packing: flexible jobs run while the cluster is on anyway, so M1/M2 never need extra wake-ups. "
                "Test data refresh starts at 16:00 instead of 17:00 so it ends inside M2's 18:00 window.",
    }
