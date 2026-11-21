"""Clustering: groups of servers with similar usage, and outliers with an explanation.

k-means (numpy, k-means++ seeding, fixed seed, best of 30 starts) on standardised usage features from the
monitoring time series and the inventory. Cluster names are derived from the centroids, not hand-assigned.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import BASELINE_END, BASELINE_START, DATA_AS_OF

FEATURES = {
    "cpu_avg": "average CPU %", "cpu_max": "peak CPU %", "ram_avg": "average RAM %",
    "uptime": "share of hours running", "login_days": "days since last human login", "vcpu": "vCPU",
}
EXPLAIN = {
    "dr-failover": "Idle by design: emergency fallback that must stay on (T-1094, W5). Not waste.",
    "gpu-ml-01": "GPU server: CPU idle, GPU busy only in the training weeks (M4).",
    "poc-ki-2024": "Proof of concept from 2024, no login since: removed in M5 after a snapshot.",
    "migration-alt": "Old migration server, no owner cost centre: removed in M5 after a human confirms.",
    "build-agent-old": "Replaced build agent, no login since: removed in M5.",
}


def _kmeans(x: np.ndarray, k: int, seed: int = 7, starts: int = 30):
    rng = np.random.default_rng(seed)
    best = None
    for _ in range(starts):
        c = [x[rng.integers(len(x))]]
        for _ in range(1, k):
            d = np.min(((x[:, None, :] - np.array(c)[None]) ** 2).sum(-1), axis=1)
            c.append(x[rng.choice(len(x), p=d / d.sum())])
        c = np.array(c)
        for _ in range(100):
            lab = ((x[:, None, :] - c[None]) ** 2).sum(-1).argmin(1)
            new = np.array([x[lab == j].mean(0) if (lab == j).any() else c[j] for j in range(k)])
            if np.allclose(new, c):
                break
            c = new
        inertia = ((x - c[lab]) ** 2).sum()
        if best is None or inertia < best[0]:
            best = (inertia, lab, c)
    return best[1], best[2]


def _name(cz: pd.Series) -> str:
    if cz.login_days > 0.8 and cz.cpu_avg < 0:
        return "Forgotten: no login for a long time, little load"
    if cz.cpu_avg > 0.6:
        return "Busy: high CPU load"
    if cz.uptime < -0.5:
        return "Part-time: not always running"
    if cz.vcpu > 0.8:
        return "Large but lightly used"
    return "Steady, lightly used"


def servers(r: dict, k: int = 4) -> dict:
    inv, met = r["inventory"].copy(), r["metrics"]
    m = met[(met.week_start >= BASELINE_START) & (met.week_start <= BASELINE_END)]
    g = m.groupby("server_id").agg(cpu_avg=("cpu_avg_pct", "mean"), cpu_max=("cpu_max_pct", "mean"),
                                   ram_avg=("ram_avg_pct", "mean"), uptime=("uptime_h", "mean"))
    g["uptime"] = g.uptime / 168
    inv = inv.set_index("server_id")
    g = g.join(inv[["vcpu", "last_login", "type", "provider", "region", "criticality", "environment"]], how="inner")
    g["login_days"] = (DATA_AS_OF - g.last_login).dt.days.clip(lower=0)
    feats = list(FEATURES)
    x = g[feats].astype(float).copy()
    x["login_days"] = np.log1p(x.login_days)
    x["vcpu"] = np.log2(x.vcpu)
    z = (x - x.mean()) / x.std(ddof=0).replace(0, 1)
    lab, cen = _kmeans(z.values, k)
    g["cluster"] = lab
    cz = pd.DataFrame(cen, columns=feats)
    names = {j: _name(cz.loc[j]) for j in range(k)}
    # make names unique
    seen = {}
    for j, n in list(names.items()):
        seen[n] = seen.get(n, 0) + 1
        if seen[n] > 1:
            names[j] = f"{n} ({seen[n]})"
    dist = np.sqrt(((z.values - cen[lab]) ** 2).sum(1))
    g["dist"] = dist
    thr = dist.mean() + 2 * dist.std()
    outliers = []
    for sid, row in g[g.dist > thr].sort_values("dist", ascending=False).iterrows():
        dev = (z.loc[sid] - cz.loc[row.cluster]).abs().sort_values(ascending=False)
        top = dev.index[0]
        outliers.append({
            "server_id": sid, "cluster": names[row.cluster], "feature": FEATURES[top],
            "value": float(g.loc[sid, top]), "cluster_typical": float(g[g.cluster == row.cluster][top].median()),
            "why": EXPLAIN.get(sid, f"{FEATURES[top]} is {g.loc[sid, top]:.1f} vs typical "
                                    f"{g[g.cluster == row.cluster][top].median():.1f} in its group"),
        })
    clusters = []
    for j in range(k):
        s = g[g.cluster == j]
        clusters.append({"id": int(j), "name": names[j], "n": int(len(s)), "vcpu": int(s.vcpu.sum()),
                         "cpu_avg": float(s.cpu_avg.mean()), "uptime": float(s.uptime.mean()),
                         "login_days": float(s.login_days.median()), "types": s.type.value_counts().to_dict(),
                         "members": s.index.tolist()})
    points = [{"id": sid, "cluster": int(row.cluster), "cpu_avg": float(row.cpu_avg), "cpu_max": float(row.cpu_max),
               "login_days": int(row.login_days), "uptime": float(row.uptime), "vcpu": int(row.vcpu),
               "type": row.type, "outlier": bool(row.dist > thr), "note": EXPLAIN.get(sid, "")} for sid, row in g.iterrows()]
    return {"k": k, "features": FEATURES, "clusters": clusters, "outliers": outliers, "points": points,
            "method": "k-means, k=4, standardised features (log of login age and vCPU), best of 30 seeded starts; "
                      "outlier = distance to own centroid > mean + 2 sd"}
