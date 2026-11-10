"""Load test: concurrent incident creation, read endpoints, and live-event delay."""
import argparse
import json
import math
import random
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import httpx
from websockets.sync.client import connect

API = "http://127.0.0.1:8000"
WS = "ws://127.0.0.1:8000/ws"
CENTER_LON, CENTER_LAT, R = 74.8765, 31.62, 2800


def point():
    r = R * math.sqrt(random.random())
    th = 2 * math.pi * random.random()
    return (CENTER_LON + r * math.cos(th) / (111320.0 * math.cos(math.radians(CENTER_LAT))),
            CENTER_LAT + r * math.sin(th) / 111320.0)


def pct(values, p):
    if not values:
        return float("nan")
    s = sorted(values)
    return s[min(len(s) - 1, math.ceil(p / 100 * len(s)) - 1)]


def listen(stop, lags):
    try:
        with connect(WS) as ws:
            while not stop.is_set():
                try:
                    msg = ws.recv(timeout=0.5)
                except TimeoutError:
                    continue
                e = json.loads(msg)
                if e["type"] == "incident_created":
                    sent = datetime.fromisoformat(e["ts"])
                    lags.append((datetime.now(timezone.utc) - sent).total_seconds() * 1000)
    except Exception as exc:
        print("event listener stopped:", repr(exc))


def report(title, results, wall):
    ok = [ms for code, ms, _ in results if code in (200, 201)]
    codes = Counter(code for code, _, _ in results)
    print(f"\n--- {title} ---")
    print(f"requests {len(results)} | wall {wall:.1f}s | throughput {len(results) / wall:.1f} req/s")
    print(f"success {len(ok)}/{len(results)} | status counts {dict(codes)}")
    print(f"latency ms: p50 {pct(ok, 50):.0f} | p95 {pct(ok, 95):.0f} | p99 {pct(ok, 99):.0f} | max {max(ok, default=float('nan')):.0f}")


def run(fn, total, conc):
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=conc) as pool:
        results = list(pool.map(fn, range(total)))
    return results, time.perf_counter() - t0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--total", type=int, default=300)
    ap.add_argument("--concurrency", type=int, default=20)
    args = ap.parse_args()
    run_id = int(time.time())
    client = httpx.Client(base_url=API, timeout=60)

    def create(i):
        lon, lat = point()
        t = time.perf_counter()
        try:
            r = client.post("/incidents", json={
                "description": f"LOADTEST {i} fire near the market", "lat": lat, "lon": lon,
                "idempotency_key": f"load-{run_id}-{i}"})
            code, body = r.status_code, (r.json() if r.status_code == 201 else {})
        except Exception as exc:
            code, body = type(exc).__name__, {}
        return code, (time.perf_counter() - t) * 1000, body.get("id")

    lags, stop = [], threading.Event()
    listener = threading.Thread(target=listen, args=(stop, lags), daemon=True)
    listener.start()
    time.sleep(1)

    print(f"Creating {args.total} incidents with {args.concurrency} concurrent clients ...")
    results, wall = run(create, args.total, args.concurrency)
    report("POST /incidents", results, wall)
    ids = [i for _, _, i in results if i]

    time.sleep(2)
    stop.set()
    listener.join(timeout=3)
    if lags:
        print(f"\nlive event delay (publish to browser socket), {len(lags)} events: "
              f"p50 {pct(lags, 50):.0f} ms | p95 {pct(lags, 95):.0f} ms | max {max(lags):.0f} ms")
        if len(lags) < len(ids):
            print(f"NOTE: only {len(lags)} of {len(ids)} events reached the listener")

    def timed_get(path):
        def f(_):
            t = time.perf_counter()
            try:
                code = client.get(path).status_code
            except Exception as exc:
                code = type(exc).__name__
            return code, (time.perf_counter() - t) * 1000, None
        return f

    if ids:
        for path in ("/resources", "/incidents?active_only=true&limit=100", f"/incidents/{ids[0]}/recommendations"):
            res, w = run(timed_get(path), 200, args.concurrency)
            report(f"GET {path.split('?')[0].replace(str(ids[0]), '{id}')}", res, w)

    print("\nClean up the test data afterwards with:")
    print("docker exec -it crisisgrid_db psql -U crisis -d crisisgrid -c "
          "\"UPDATE incidents SET status='cancelled' WHERE raw_text LIKE 'LOADTEST%';\"")


if __name__ == "__main__":
    main()