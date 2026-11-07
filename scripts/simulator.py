"""Plays the role of the vehicles. Talks to CrisisGrid only through its public API,
exactly as real GPS-equipped vehicles would."""
import argparse
import bisect
import math
import time

import httpx

API = "http://127.0.0.1:8000"
OSRM = "http://localhost:5001"


def haversine(a, b):  # points are (lon, lat)
    R = 6371000.0
    la1, la2 = math.radians(a[1]), math.radians(b[1])
    dla, dlo = la2 - la1, math.radians(b[0] - a[0])
    h = math.sin(dla / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(dlo / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def fetch_route(a, b):
    """Real road geometry from OSRM; straight line if OSRM is unreachable."""
    try:
        r = httpx.get(f"{OSRM}/route/v1/driving/{a[0]},{a[1]};{b[0]},{b[1]}",
                      params={"overview": "full", "geometries": "geojson"}, timeout=5)
        r.raise_for_status()
        pts = [tuple(p) for p in r.json()["routes"][0]["geometry"]["coordinates"]]
        return [a] + pts + [b]
    except Exception as exc:
        print("  route fallback (straight line):", repr(exc))
        return [a, b]


class Path:
    def __init__(self, pts):
        self.pts = pts
        self.cum = [0.0]
        for p, q in zip(pts, pts[1:]):
            self.cum.append(self.cum[-1] + haversine(p, q))
        self.total = self.cum[-1]

    def at(self, d):
        if d >= self.total:
            return self.pts[-1]
        i = bisect.bisect_right(self.cum, d) - 1
        seg = self.cum[i + 1] - self.cum[i]
        f = 0.0 if seg == 0 else (d - self.cum[i]) / seg
        p, q = self.pts[i], self.pts[i + 1]
        return (p[0] + (q[0] - p[0]) * f, p[1] + (q[1] - p[1]) * f)


def advance(client, a):
    r = client.post(f"/dispatch/assignments/{a['id']}/advance", params={"expected": a["status"]})
    if r.status_code == 200:
        print(f"  {a['code']}: {a['status']} -> {r.json()['status']}")
    elif r.status_code != 409:   # 409 just means someone else already moved it
        print("  advance failed:", r.status_code, r.text)


def move(client, unit, st, dest, dt, speed_ms):
    """Moves the unit along its road route. Returns True when it has arrived."""
    if st["path"] is None:
        st["path"] = Path(fetch_route((unit["lon"], unit["lat"]), dest))
        st["dist"] = 0.0
    st["dist"] += speed_ms * dt
    lon, lat = st["path"].at(st["dist"])
    client.post(f"/resources/{unit['id']}/location", json={"lat": lat, "lon": lon})
    return st["dist"] >= st["path"].total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--speed-kmh", type=float, default=40.0, help="vehicle speed")
    ap.add_argument("--accel", type=float, default=1.0, help="time multiplier for demos")
    ap.add_argument("--dispatch-delay", type=float, default=3.0, help="seconds before departure")
    ap.add_argument("--dwell", type=float, default=15.0, help="seconds spent on scene")
    ap.add_argument("--tick", type=float, default=1.0)
    args = ap.parse_args()

    speed_ms = args.speed_kmh / 3.6 * args.accel
    delay, dwell = args.dispatch_delay / args.accel, args.dwell / args.accel
    client = httpx.Client(base_url=API, timeout=5)
    incident_loc, state = {}, {}
    last = time.monotonic()
    print(f"Simulator running: {args.speed_kmh} km/h, {args.accel}x time. Ctrl+C to stop.")

    while True:
        time.sleep(args.tick)
        now = time.monotonic()
        dt, last = now - last, now
        try:
            assignments = client.get("/dispatch/assignments", params={"active_only": True}).json()
            units = {u["id"]: u for u in client.get("/resources").json()}
        except httpx.HTTPError as exc:
            print("API unavailable:", repr(exc))
            continue

        live = set()
        for a in assignments:
            aid, status = a["id"], a["status"]
            live.add(aid)
            unit = units.get(a["resource_id"])
            if unit is None or unit["lat"] is None:
                continue
            st = state.get(aid)
            if st is None or st["status"] != status:     # entered a new phase
                st = state[aid] = {"status": status, "since": now, "path": None, "dist": 0.0}
            try:
                if status == "assigned":
                    if now - st["since"] >= delay:
                        advance(client, a)
                elif status == "en_route":
                    iid = a["incident_id"]
                    if iid not in incident_loc:
                        inc = client.get(f"/incidents/{iid}").json()
                        incident_loc[iid] = (inc["lon"], inc["lat"])
                    if move(client, unit, st, incident_loc[iid], dt, speed_ms):
                        advance(client, a)
                elif status == "on_scene":
                    if now - st["since"] >= dwell:
                        advance(client, a)
                elif status == "returning":
                    if unit.get("home_lat") is None:
                        advance(client, a)
                    elif move(client, unit, st, (unit["home_lon"], unit["home_lat"]), dt, speed_ms):
                        advance(client, a)
            except httpx.HTTPError as exc:
                print("request failed:", repr(exc))

        for aid in [k for k in state if k not in live]:
            del state[aid]


if __name__ == "__main__":
    main()