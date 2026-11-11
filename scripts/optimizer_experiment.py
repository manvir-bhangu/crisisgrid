"""Offline experiment: dispatch strategies on surges of simultaneous incidents.
All strategies are scored on real OSRM road travel times, on identical scenarios."""
import argparse
import csv
import math
import os
import sys
import time
from datetime import datetime

import httpx
import numpy as np
from scipy.stats import wilcoxon
from sqlalchemy import text

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, os.path.join(ROOT, "backend"))

from app.allocation.optimizer import greedy, hungarian  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.db.session import engine  # noqa: E402

CENTER_LON, CENTER_LAT, RADIUS_M = 74.8765, 31.62, 3000
SEV_P = [0.15, 0.25, 0.35, 0.25]          # critical, high, medium, low (assumed mix)
METHODS = ["A nearest straight-line", "B nearest road-time", "C road-time + critical first",
           "D Hungarian (unweighted)", "E Hungarian (priority-weighted)"]
METRICS = ((0, "all served"), (1, "critical only"), (2, "weighted cost"))


def load_units():
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT ST_X(f.location::geometry), ST_Y(f.location::geometry)
            FROM resources r JOIN facilities f ON f.id = r.home_facility_id
            WHERE r.type = 'ambulance' ORDER BY r.code""")).all()
    return np.array([[r[0], r[1]] for r in rows], dtype=float)


def random_point(rng):
    r = RADIUS_M * math.sqrt(rng.random())
    th = 2 * math.pi * rng.random()
    dlat = r * math.sin(th) / 111320.0
    dlon = r * math.cos(th) / (111320.0 * math.cos(math.radians(CENTER_LAT)))
    return CENTER_LON + dlon, CENTER_LAT + dlat


def straight_matrix(U, I):
    lat1 = np.radians(U[:, 1])[:, None]
    lat2 = np.radians(I[:, 1])[None, :]
    dlon = np.radians(I[:, 0])[None, :] - np.radians(U[:, 0])[:, None]
    h = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return 2 * 6371000.0 * np.arcsin(np.sqrt(h))


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
    return np.array([[np.nan if v is None else v for v in row] for row in d["durations"]], dtype=float)


def timed(fn):
    t0 = time.perf_counter()
    out = fn()
    return out, (time.perf_counter() - t0) * 1000


def paired(pt_a, pt_b, idx):
    x = np.array([a[idx] for a in pt_a])
    y = np.array([b[idx] for b in pt_b])
    ok = np.isfinite(x) & np.isfinite(y)
    d = (x - y)[ok]
    if len(d) < 10:
        return len(d), float("nan"), None
    if np.allclose(d, 0):
        return len(d), 0.0, 1.0
    return len(d), float(d.mean()), float(wilcoxon(x[ok], y[ok]).pvalue)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, nargs="+", default=[8, 15, 25], help="incidents per surge")
    ap.add_argument("--trials", type=int, default=200)
    ap.add_argument("--avail", type=float, default=0.7, help="chance each ambulance is free")
    ap.add_argument("--weights", default="8,4,2,1", help="weights E optimises (critical,high,medium,low)")
    ap.add_argument("--eval-weights", default=None, help="weights used to SCORE the weighted cost (default: same)")
    ap.add_argument("--penalty", type=float, default=1800.0, help="seconds charged for an unserved incident")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    units = load_units()
    if len(units) == 0:
        sys.exit("No ambulances found. Run scripts/seed_resources.py first.")
    ws = np.array([float(x) for x in args.weights.split(",")])
    ev = np.array([float(x) for x in (args.eval_weights or args.weights).split(",")])
    client = httpx.Client(timeout=10)
    try:
        road_matrix(client, units[:1], units[:1])
    except Exception as exc:
        sys.exit(f"OSRM is not reachable ({exc!r}). Start it with: docker start crisisgrid_osrm")

    print(f"{len(units)} ambulances | {args.trials} trials per size | availability {args.avail:.0%} "
          f"| E weights {args.weights} | scoring weights {args.eval_weights or args.weights} "
          f"| unserved penalty {args.penalty:.0f}s | seed {args.seed}")
    out_rows = []

    for N in args.n:
        agg = {m: {"t": [], "ct": [], "ctot": 0, "cserv": 0, "serv": 0, "tot": 0, "ms": [], "wc": []}
               for m in METHODS}
        per_trial = {m: [] for m in METHODS}

        for trial in range(args.trials):
            rng = np.random.default_rng(args.seed + 1000 * N + trial)
            mask = rng.random(len(units)) < args.avail
            if not mask.any():
                mask[rng.integers(len(units))] = True
            U = units[mask]
            pts = np.array([random_point(rng) for _ in range(N)])
            sev = rng.choice(4, size=N, p=SEV_P)
            w = ws[sev]
            w_eval = ev[sev]
            S, R = straight_matrix(U, pts), road_matrix(client, U, pts)
            arrival = list(range(N))
            prio = sorted(arrival, key=lambda j: (-w[j], j))

            plans = {
                METHODS[0]: timed(lambda: greedy(S, arrival)),
                METHODS[1]: timed(lambda: greedy(R, arrival)),
                METHODS[2]: timed(lambda: greedy(R, prio)),
                METHODS[3]: timed(lambda: hungarian(R, np.ones(N))),
                METHODS[4]: timed(lambda: hungarian(R, w)),
            }
            for m, (plan, ms) in plans.items():
                a = agg[m]
                times, ctimes, wsum = [], [], 0.0
                for j in range(N):
                    crit = int(sev[j] == 0)
                    a["tot"] += 1
                    a["ctot"] += crit
                    served = j in plan and np.isfinite(R[plan[j], j])
                    if served:
                        tj = float(R[plan[j], j])
                        a["serv"] += 1
                        a["cserv"] += crit
                        times.append(tj)
                        a["t"].append(tj)
                        if crit:
                            ctimes.append(tj)
                            a["ct"].append(tj)
                    else:
                        tj = args.penalty
                    wsum += w_eval[j] * tj
                a["ms"].append(ms)
                wc = wsum / w_eval.sum()
                a["wc"].append(wc)
                per_trial[m].append((np.mean(times) if times else np.nan,
                                     np.mean(ctimes) if ctimes else np.nan, wc))

        print(f"\n=== {N} simultaneous incidents per surge ===")
        print(f"{'method':32}{'mean s':>8}{'p95 s':>8}{'crit mean s':>13}{'crit served':>13}"
              f"{'served':>9}{'w.cost s':>10}{'solve ms':>10}")
        for m in METHODS:
            a = agg[m]
            mean = np.mean(a["t"]) if a["t"] else float("nan")
            p95 = np.percentile(a["t"], 95) if a["t"] else float("nan")
            cm = np.mean(a["ct"]) if a["ct"] else float("nan")
            cs = a["cserv"] / a["ctot"] if a["ctot"] else float("nan")
            sv = a["serv"] / a["tot"]
            wc = np.mean(a["wc"])
            ms = np.mean(a["ms"])
            print(f"{m:32}{mean:8.0f}{p95:8.0f}{cm:13.0f}{cs:13.1%}{sv:9.1%}{wc:10.0f}{ms:10.2f}")
            out_rows.append([N, m, round(mean, 1), round(p95, 1), round(cm, 1), round(cs, 4),
                             round(sv, 4), round(wc, 1), round(ms, 3)])

        print("Paired comparisons, mean difference in seconds (negative = E is better), Wilcoxon p (uncorrected):")
        for other in (METHODS[1], METHODS[2], METHODS[3]):
            for idx, label in METRICS:
                n, diff, p = paired(per_trial[METHODS[4]], per_trial[other], idx)
                ptxt = "n/a" if p is None else f"{p:.4f}"
                print(f"  E vs {other[:1]}  {label:14} n={n:3}  diff={diff:8.1f}s  p={ptxt}")

    out = os.path.join(ROOT, "research", "results", f"optimizer_{datetime.now():%Y%m%d_%H%M%S}.csv")
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["n_incidents", "method", "mean_s", "p95_s", "critical_mean_s",
                    "critical_served", "served", "weighted_cost_s", "solve_ms"])
        w.writerows(out_rows)
    print(f"\nSaved to {out}")


if __name__ == "__main__":
    main()
