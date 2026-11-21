"""Cross-border electricity flows and the map of Europe for the Grid page.

Flows: Energy-Charts (Fraunhofer ISE) API /v2/cbpf, physical flows per border every 15 minutes (from ENTSO-E),
CC BY 4.0, attribution energy-charts.info. `greenledger grid-fetch` downloads the last 12 full months per country and
keeps only aggregates (the raw files would be about 150 MB):
  cross_border_flows_monthly.csv   country, neighbour, month: gross import / export GWh, and the NET import / export
                                   attributed to that neighbour (in each 15 minutes the country's net import is split
                                   over the neighbours sending at that moment; transit through the country cancels out)
  cross_border_net_import_by_hour.csv  country, month, hour: average net import in GW (negative = net export)

Map: Natural Earth 1:50m admin-0 countries (public domain, naturalearthdata.com), projected once with the Lambert
azimuthal equal-area projection centred on Europe (as EPSG:3035), simplified, and stored as SVG paths in
assets/europe_map.json, which is committed: the map needs no download.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import time
import urllib.request
from collections import defaultdict
from pathlib import Path

import pandas as pd

from .config import ROOT

ASSET_MAP = ROOT / "src" / "greenledger" / "assets" / "europe_map.json"
FLOWS_MONTHLY = "cross_border_flows_monthly.csv"
FLOWS_HOURLY = "cross_border_net_import_by_hour.csv"
API = "https://api.energy-charts.info/v2/cbpf"
NE_URL = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_admin_0_countries.geojson"
NE_FILE = "ne_50m_admin_0_countries.geojson"
FLOW_SOURCE = ("Energy-Charts (Fraunhofer ISE), cross-border physical flows every 15 minutes, data from ENTSO-E; "
               "CC BY 4.0, attribution energy-charts.info (api.energy-charts.info/v2/cbpf)")
MAP_SOURCE = "Natural Earth 1:50m admin-0 countries, public domain (naturalearthdata.com)"

# Energy-Charts country codes with flow data, and the ISO3 codes used everywhere else.
CB_COUNTRIES = {"ch": "CHE", "at": "AUT", "ba": "BIH", "be": "BEL", "bg": "BGR", "cz": "CZE", "de": "DEU", "dk": "DNK",
                "ee": "EST", "es": "ESP", "fi": "FIN", "fr": "FRA", "gr": "GRC", "hr": "HRV", "hu": "HUN", "ie": "IRL",
                "it": "ITA", "lt": "LTU", "lu": "LUX", "lv": "LVA", "me": "MNE", "mk": "MKD", "nl": "NLD", "no": "NOR",
                "pl": "POL", "pt": "PRT", "ro": "ROU", "rs": "SRB", "se": "SWE", "si": "SVN", "sk": "SVK", "ua": "UKR",
                "uk": "GBR", "xk": "XKX"}
# neighbour series ids of the API -> ISO3 (non-European neighbours keep their own code)
NB_ISO = {"austria": "AUT", "belgium": "BEL", "bosnia_herzegovina": "BIH", "bosnia_and_herzegovina": "BIH", "bulgaria": "BGR",
          "croatia": "HRV", "czech_republic": "CZE", "czechia": "CZE", "denmark": "DNK", "estonia": "EST", "finland": "FIN",
          "france": "FRA", "germany": "DEU", "greece": "GRC", "hungary": "HUN", "ireland": "IRL", "italy": "ITA",
          "latvia": "LVA", "lithuania": "LTU", "luxembourg": "LUX", "montenegro": "MNE", "north_macedonia": "MKD",
          "netherlands": "NLD", "norway": "NOR", "poland": "POL", "portugal": "PRT", "romania": "ROU", "serbia": "SRB",
          "slovakia": "SVK", "slovenia": "SVN", "spain": "ESP", "sweden": "SWE", "switzerland": "CHE", "ukraine": "UKR",
          "united_kingdom": "GBR", "great_britain": "GBR", "uk": "GBR", "kosovo": "XKX", "albania": "ALB", "moldova": "MDA",
          "turkey": "TUR", "türkiye": "TUR", "russia": "RUS", "belarus": "BLR", "morocco": "MAR", "malta": "MLT",
          "northern_ireland": "GBR", "georgia": "GEO", "armenia": "ARM", "azerbaijan": "AZE"}


def last_12_months(today: dt.date | None = None) -> tuple[str, str]:
    t = today or dt.date.today()
    end = t.replace(day=1) - dt.timedelta(days=1)                     # last day of the previous month
    y, m = end.year, end.month - 11
    while m <= 0:
        m, y = m + 12, y - 1
    return dt.date(y, m, 1).isoformat(), end.isoformat()


def aggregate(payload: dict, iso: str) -> tuple[list[dict], list[dict]]:
    """15-minute flows of one country -> monthly gross and attributed net flows per neighbour, and net import by hour."""
    step_h = (payload.get("interval_minutes") or 15) / 60
    ids = [s["id"] for s in payload["series"] if s["id"] != "sum"]
    gross_i, gross_e, net_i, net_e = (defaultdict(float) for _ in range(4))
    hour_sum, hour_n = defaultdict(float), defaultdict(int)
    for row in payload["data"]:
        ts, vals = row["timestamp"], row["values"]
        month, hour = ts[:7], int(ts[11:13])
        flows = {k: vals.get(k) for k in ids if vals.get(k) is not None}
        if not flows:
            continue
        s = sum(flows.values())
        pos = sum(v for v in flows.values() if v > 0)
        neg = sum(-v for v in flows.values() if v < 0)
        for k, v in flows.items():
            if v > 0:
                gross_i[(k, month)] += v * step_h
                if s > 0:
                    net_i[(k, month)] += s * v / pos * step_h
            elif v < 0:
                gross_e[(k, month)] += -v * step_h
                if s < 0:
                    net_e[(k, month)] += -s * -v / neg * step_h
        hour_sum[(month, hour)] += s
        hour_n[(month, hour)] += 1
    keys = sorted(set(gross_i) | set(gross_e) | set(net_i) | set(net_e))
    names = {s["id"]: s.get("name", s["id"]) for s in payload["series"]}
    monthly = [{"country": iso, "neighbour": NB_ISO.get(k, k.upper()[:3]), "neighbour_name": names.get(k, k), "month": m,
                "import_gwh": round(gross_i[(k, m)], 2), "export_gwh": round(gross_e[(k, m)], 2),
                "net_import_gwh": round(net_i[(k, m)], 2), "net_export_gwh": round(net_e[(k, m)], 2)} for k, m in keys]
    hourly = [{"country": iso, "month": m, "hour": h, "net_import_gw": round(hour_sum[(m, h)] / hour_n[(m, h)], 4)}
              for (m, h) in sorted(hour_sum)]
    return monthly, hourly


def _get_json(url: str, timeout: int, tries: int = 6) -> dict:
    """GET with the API's rate limit respected: wait as long as Retry-After says, then try again."""
    import urllib.error
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "kilowise-grid-fetch"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code != 429 or i == tries - 1:
                raise
            time.sleep(float(e.headers.get("Retry-After") or 2) + i)
    raise OSError("rate limited")


def fetch_flows(dest: Path, timeout: int = 300, today: dt.date | None = None) -> list[str]:
    start, end = last_12_months(today)
    monthly, hourly, out, failed = [], [], [], []
    for code, iso in CB_COUNTRIES.items():
        url = f"{API}?country={code}&start={start}&end={end}"
        try:
            payload = _get_json(url, timeout)
            mo, ho = aggregate(payload, iso)
            monthly += mo
            hourly += ho
        except (OSError, ValueError, KeyError) as e:
            failed.append(f"{code} ({e.__class__.__name__})")
        time.sleep(1.2)   # the API allows about one request a second
    if not monthly:
        return [f"flows: nothing downloaded ({', '.join(failed[:3])}); kept the old files"]
    pd.DataFrame(monthly).to_csv(dest / FLOWS_MONTHLY, index=False, encoding="utf-8")
    pd.DataFrame(hourly).to_csv(dest / FLOWS_HOURLY, index=False, encoding="utf-8")
    out.append(f"flows {start} to {end}: {len(CB_COUNTRIES) - len(failed)} countries, {len(monthly)} border-months"
               + (f"; missing {', '.join(failed)}" if failed else ""))
    return out


# ---------------------------------------------------------------- map --------------------------------------------
LON0, LAT0 = math.radians(10), math.radians(52)          # EPSG:3035 centre
BBOX = (-12.5, 34.0, 42.0, 71.5)                         # lon/lat window drawn (mainland Europe, Turkey's west)
WIDTH = 1000
ISO_FIX = {"KOS": "XKX", "SDS": None}                    # Natural Earth ADM0_A3 -> the codes used here
# Your data centres and the cities with public cloud regions (lon, lat), drawn as points on the map.
CITIES = {"Zurich": (8.54, 47.37), "Frankfurt": (8.68, 50.11), "Dublin": (-6.26, 53.35), "Geneva": (6.14, 46.2),
          "Berlin": (13.4, 52.52), "Amsterdam": (4.9, 52.37), "Eemshaven": (6.83, 53.44), "St. Ghislain": (3.82, 50.45),
          "London": (-0.13, 51.51), "Paris": (2.35, 48.86), "Stockholm": (18.07, 59.33), "Gävle": (17.14, 60.67),
          "Oslo": (10.75, 59.91), "Hamina": (27.2, 60.57), "Warsaw": (21.01, 52.23), "Milan": (9.19, 45.46),
          "Madrid": (-3.7, 40.42), "Aragón": (-0.88, 41.65)}


def _laea(lon: float, lat: float) -> tuple[float, float]:
    lam, phi = math.radians(lon), math.radians(lat)
    k = math.sqrt(2 / (1 + math.sin(LAT0) * math.sin(phi) + math.cos(LAT0) * math.cos(phi) * math.cos(lam - LON0)))
    return (k * math.cos(phi) * math.sin(lam - LON0),
            k * (math.cos(LAT0) * math.sin(phi) - math.sin(LAT0) * math.cos(phi) * math.cos(lam - LON0)))


def _simplify(pts: list[tuple[float, float]], tol: float) -> list[tuple[float, float]]:
    """Douglas-Peucker, iterative."""
    if len(pts) < 4:
        return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        (x1, y1), (x2, y2) = pts[a], pts[b]
        dx, dy = x2 - x1, y2 - y1
        n = math.hypot(dx, dy) or 1e-12
        best, idx = 0.0, -1
        for i in range(a + 1, b):
            d = abs(dy * pts[i][0] - dx * pts[i][1] + x2 * y1 - y2 * x1) / n
            if d > best:
                best, idx = d, i
        if best > tol and idx > 0:
            keep[idx] = True
            stack += [(a, idx), (idx, b)]
    return [p for p, k in zip(pts, keep) if k]


def make_map(geojson: Path, out: Path = ASSET_MAP, tol: float = 0.7) -> dict:
    """Project and simplify Natural Earth countries into SVG paths; label anchor = centre of the largest polygon."""
    gj = json.loads(geojson.read_text(encoding="utf-8"))
    corners = [_laea(lo, la) for lo in (BBOX[0], 10, BBOX[2]) for la in (BBOX[1], BBOX[3])]
    x0, x1 = min(c[0] for c in corners), max(c[0] for c in corners)
    y0, y1 = min(c[1] for c in corners), max(c[1] for c in corners)
    scale = WIDTH / (x1 - x0)
    height = round((y1 - y0) * scale)
    to_px = lambda lon, lat: (lambda p: ((p[0] - x0) * scale, (y1 - p[1]) * scale))(_laea(lon, lat))
    countries = {}
    for f in gj["features"]:
        pr = f["properties"]
        code = ISO_FIX.get(pr.get("ADM0_A3"), pr.get("ADM0_A3"))
        if not code:
            continue
        g = f["geometry"]
        polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        parts, best = [], (0.0, None)
        for poly in polys:
            ring = poly[0]
            lons, lats = [p[0] for p in ring], [p[1] for p in ring]
            if max(lons) < BBOX[0] or min(lons) > BBOX[2] or max(lats) < BBOX[1] or min(lats) > BBOX[3]:
                continue
            full = [to_px(lo, la) for lo, la in ring]
            mid = len(full) // 2   # a closed ring starts and ends on one point: simplify its two halves
            px = _simplify(full[:mid + 1], tol) + _simplify(full[mid:], tol)[1:]
            if len(px) < 4:
                continue
            area = 0.5 * abs(sum(px[i][0] * px[i - 1][1] - px[i - 1][0] * px[i][1] for i in range(len(px))))
            if area < 2:                                           # islands smaller than about 1.5 x 1.5 px
                continue
            parts.append("M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in px) + "Z")
            if area > best[0]:   # area-weighted centroid of the largest polygon (label and flow anchor)
                cross = [px[i - 1][0] * px[i][1] - px[i][0] * px[i - 1][1] for i in range(len(px))]
                a6 = 3 * sum(cross) or 1e-9
                cx = sum((px[i - 1][0] + px[i][0]) * cross[i] for i in range(len(px))) / a6
                cy = sum((px[i - 1][1] + px[i][1]) * cross[i] for i in range(len(px))) / a6
                best = (area, (round(cx, 1), round(cy, 1)))
        if parts:
            countries[code] = {"name": pr.get("NAME_EN") or pr.get("NAME"), "d": "".join(parts), "c": best[1], "a": round(best[0])}
    cities = {n: [round(v, 1) for v in to_px(lo, la)] for n, (lo, la) in CITIES.items()}
    data = {"source": MAP_SOURCE, "cities": cities, "projection": "Lambert azimuthal equal-area, centre 10°E 52°N (as EPSG:3035)",
            "width": WIDTH, "height": height, "countries": countries}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return data


def fetch_map(dest: Path, timeout: int = 120) -> str:
    p = dest / NE_FILE
    try:
        req = urllib.request.Request(NE_URL, headers={"User-Agent": "kilowise-grid-fetch"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            p.write_bytes(r.read())
        d = make_map(p)
        return f"map: {len(d['countries'])} countries -> {ASSET_MAP.relative_to(ROOT)}"
    except (OSError, ValueError, KeyError) as e:
        return f"map: kept the committed map ({e.__class__.__name__})"


def load_map() -> dict | None:
    return json.loads(ASSET_MAP.read_text(encoding="utf-8")) if ASSET_MAP.exists() else None
