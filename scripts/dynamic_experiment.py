"""Dynamic-arrival experiment: incidents arrive over time, units become free again.
Policies (no reassignment of units already moving):
  A FIFO + nearest free unit
  B priority queue (severity, then arrival) + nearest free unit
  C Hungarian over waiting incidents x free units, severity-weighted
  D like C, with weights growing with waiting time (aging)
Response time = from report arrival until a unit reaches the scene. Road times from OSRM."""
import argparse
import csv
import heapq
import math
import os
import sys
from datetime import datetime

import httpx
import numpy as np
from scipy.stats import wilcoxon
from sqlalchemy import text

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, os.path.join(ROOT, "backend"))

from app.allocation.optimizer import UNREACHABLE, hungarian  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.db.session import engine  # noqa: E402

CENTER_LON, CENTER_LAT, RADIUS_M = 74.8765, 31.62, 3000
SEV_P = [0.15, 0.25, 0.35, 0.25]          # critical, high, medium, low (assumed mix)
POLICIES = ["A FIFO + nearest", "B priority + nearest", "C Hungarian weighted", "D Hungarian + aging"]
MAX_INCIDENTS = 80                         # OSRM table limit is 100 coordinates by default
CRIT_LIMIT_S = 900


def load_stations():
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT ST_X(f.location::geometry), ST_Y(f.location::geometry)
            FROM resources r JOIN facilities f ON f.id = r.home_facility_id
            WHERE r.type = 'ambulance' ORDER BY r.code""")).all()
    return np.array([[r[0], r[1]] for r in rows], dtype=float)


def random_point(rng):
    r = RADIUS_M * math.sqrt(rng.random())
    th = 2 * math.pi * rng.random()
    return (CENTER_LON + r * math.cos(th) / (111320.0 * math.cos(math.radians(CENTER_LAT))),
            CENTER_LAT + r * math.sin(th) / 111320.0)


def road_matrix(client, U, I):
    k = len(U)
    coords = ";".join(f"{x:.6f},{y:.6f}" for x, y in list(U) + list(I))
    r = client.get(f"{settings.osrm_url}/table/v1/driving/{coords}", params={
        "sources": ";".join(str(i) for i in range(k)),
        "destinations": ";".join(str(k + j) for j in range(len(I))),
        "annotations": "duration"})
    r.raise_for_status()
    d = r.json()
    if d.get("code") != "Ok":
        raise RuntimeError(f"OSRM said {d.get('code')}")
    A = np.array([[np.nan if v is None else v for v in row] for row in d["durations"]], dtype=float)
    A[~np.isfinite(A)] = UNREACHABLE
    return A


def decide(policy, t, free, waiting, arr_t, w, Tm, aging_s):
    """Returns a list of (incident, unit) pairs to dispatch right now."""
    if not free or not waiting:
        return []
    if policy in (0, 1):
        avail = set(free)
        key = (lambda i: (arr_t[i], i)) if policy == 0 else (lambda i: (-w[i], arr_t[i], i))
        pairs = []
        for i in sorted(waiting, key=key):
            if not avail:
                break
            u = min(avail, key=lambda x: Tm[x, i])
            if Tm[u, i] >= UNREACHABLE:
                continue
            pairs.append((i, u))
            avail.discard(u)
        return pairs
    fr, wt = sorted(free), list(waiting)
    ww = np.array([w[i] for i in wt], dtype=float)
    if policy == 3:
        ww = ww * (1.0 + np.array([t - arr_t[i] for i in wt]) / aging_s)
    plan = hungarian(Tm[np.ix_(fr, wt)], ww)
    return [(wt[j], fr[ui]) for j, ui in plan.items()]


def simulate(policy, arr_t, w, dwell, Tm, aging_s):
    n_units, n = Tm.shape
    free, waiting = set(range(n_units)), []
    events = []                              # (time, kind, index); kind 0 = unit free, 1 = arrival
    for i, t in enumerate(arr_t):
        heapq.heappush(events, (t, 1, i))
    resp = np.full(n, np.nan)
    while events:
        t, kind, idx = heapq.heappop(events)
        if kind == 1:
            waiting.append(idx)
        else:
            free.add(idx)
        for i, u in decide(policy, t, free, waiting, arr_t, w, Tm, aging_s):
            free.discard(u)
            waiting.remove(i)
            travel = Tm[u, i]
            resp[i] = (t - arr_t[i]) + travel
            heapq.heappush(events, (t + travel + dwell[i] + travel, 0, u))   # return trip = same time
    return resp


def paired(a, b):
    x, y = np.array(a), np.array(b)
    ok = np.isfinite(x) & np.isfinite(y)
    d = (x - y)[ok]
    if len(d) < 10:
        return len(d), float("nan"), None
    if np.allclose(d, 0):
        return len(d), 0.0, 1.0
    return len(d), float(d.mean()), float(wilcoxon(x[ok], y[ok]).pvalue)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rates", type=float, nargs="+", default=[20, 30, 40], help="incidents per hour")
    ap.add_argument("--hours", type=float, default=2.0)
    ap.add_argument("--trials", type=int, default=30)
    ap.add_argument("--weights", default="8,4,2,1", help="critical,high,medium,low")
    ap.add_argument("--aging", type=float, default=900.0, help="seconds of waiting that add one times the base weight in D")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    stations = load_stations()
    if len(stations) == 0:
        sys.exit("No ambulances found. Run scripts/seed_resources.py first.")
    ws = np.array([float(x) for x in args.weights.split(",")])
    client = httpx.Client(timeout=15)
    try:
        road_matrix(client, stations[:1], stations[:1])
    except Exception as exc:
        sys.exit(f"OSRM is not reachable ({exc!r}). Start it with: docker start crisisgrid_osrm")

    print(f"{len(stations)} ambulances | {args.hours} h of arrivals | {args.trials} trials per rate | "
          f"weights {args.weights} | aging {args.aging:.0f}s | seed {args.seed}")
    rows_out = []

    for ri, rate in enumerate(args.rates):
        pool = {p: {s: [] for s in range(4)} for p in range(4)}
        per_trial = {p: [] for p in range(4)}
        n_inc = []
        for trial in range(args.trials):
            rng = np.random.default_rng(args.seed + 1000 * ri + trial)
            t, arr = 0.0, []
            while True:
                t += rng.exponential(3600.0 / rate)
                if t > args.hours * 3600 or len(arr) >= MAX_INCIDENTS:
                    break
                arr.append(t)
            if len(arr) < 2:
                continue
            arr_t = np.array(arr)
            n = len(arr_t)
            sev = rng.choice(4, size=n, p=SEV_P)
            dwell = rng.uniform(480, 1200, size=n)
            pts = np.array([random_point(rng) for _ in range(n)])
            Tm = road_matrix(client, stations, pts)
            keep = Tm.min(axis=0) < UNREACHABLE
            if not keep.all():
                arr_t, sev, dwell, Tm = arr_t[keep], sev[keep], dwell[keep], Tm[:, keep]
            n_inc.append(len(arr_t))
            w = ws[sev]
            for p in range(4):
                resp = simulate(p, arr_t, w, dwell, Tm, args.aging)
                for s in range(4):
                    pool[p][s].extend(resp[sev == s].tolist())
                m = lambda mask: float(np.mean(resp[mask])) if mask.any() else float("nan")
                per_trial[p].append((m(sev == 0), m(np.ones(len(sev), bool)), m(sev == 3)))

        print(f"\n=== {rate:.0f} incidents per hour (about {np.mean(n_inc):.0f} per trial) ===")
        print(f"{'policy':24}{'all mean s':>11}{'crit mean s':>12}{'crit p95 s':>11}{'crit<=15min':>12}"
              f"{'low mean s':>11}{'low p95 s':>10}{'worst s':>9}")
        for p in range(4):
            allv = [v for s in range(4) for v in pool[p][s]]
            crit, low = pool[p][0], pool[p][3]
            print(f"{POLICIES[p]:24}{np.mean(allv):11.0f}{np.mean(crit):12.0f}{np.percentile(crit, 95):11.0f}"
                  f"{np.mean(np.array(crit) <= CRIT_LIMIT_S):12.1%}{np.mean(low):11.0f}"
                  f"{np.percentile(low, 95):10.0f}{max(allv):9.0f}")
            rows_out.append([rate, POLICIES[p], round(float(np.mean(allv)), 1), round(float(np.mean(crit)), 1),
                             round(float(np.percentile(crit, 95)), 1),
                             round(float(np.mean(np.array(crit) <= CRIT_LIMIT_S)), 4),
                             round(float(np.mean(low)), 1), round(float(np.percentile(low, 95)), 1),
                             round(float(max(allv)), 1)])

        print("Paired per-trial comparisons: mean difference in seconds (negative = first policy is faster), "
              "Wilcoxon p (uncorrected):")
        for a, b in ((1, 0), (2, 1), (2, 0), (3, 2)):
            for idx, label in ((0, "critical mean"), (1, "all mean"), (2, "low mean")):
                n, diff, pv = paired([x[idx] for x in per_trial[a]], [x[idx] for x in per_trial[b]])
                print(f"  {POLICIES[a][0]} vs {POLICIES[b][0]}  {label:14} n={n:3}  diff={diff:8.1f}s  "
                      f"p={'n/a' if pv is None else f'{pv:.4f}'}")

    out = os.path.join(ROOT, "research", "results", f"dynamic_{datetime.now():%Y%m%d_%H%M%S}.csv")
    with open(out, "w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f)
        wr.writerow(["rate_per_hour", "policy", "all_mean_s", "crit_mean_s", "crit_p95_s",
                     "crit_within_15min", "low_mean_s", "low_p95_s", "worst_s"])
        wr.writerows(rows_out)
    print(f"\nSaved to {out}")


if __name__ == "__main__":
    main()
