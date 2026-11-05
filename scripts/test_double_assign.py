"""Fires many simultaneous requests for the SAME ambulance from TWO incidents.
Correct behaviour: exactly 1 succeeds, all the rest get 409."""
from concurrent.futures import ThreadPoolExecutor
import httpx

API = "http://127.0.0.1:8000"


def new_incident(n):
    r = httpx.post(f"{API}/incidents", json={
        "description": f"concurrency test {n}", "lat": 31.634, "lon": 74.8723,
        "category": "accident"})
    r.raise_for_status()
    return r.json()["id"]


def main():
    unit = httpx.get(f"{API}/resources", params={"status": "available", "type": "ambulance"}).json()[0]
    inc_a, inc_b = new_incident(1), new_incident(2)
    print(f"Racing for {unit['code']} between incidents {inc_a} and {inc_b} ...")

    def attempt(i):
        incident = inc_a if i % 2 == 0 else inc_b
        r = httpx.post(f"{API}/dispatch/assign",
                       json={"incident_id": incident, "resource_id": unit["id"]})
        return r.status_code, r.json()

    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(attempt, range(20)))

    ok = [x for x in results if x[0] == 201]
    conflict = [x for x in results if x[0] == 409]
    print(f"201 Created: {len(ok)}   409 Conflict: {len(conflict)}   other: {len(results)-len(ok)-len(conflict)}")
    print("PASS" if len(ok) == 1 else "FAIL: double booking happened")

    if ok:  # clean up so the unit is free again
        httpx.post(f"{API}/dispatch/assignments/{ok[0][1]['assignment_id']}/cancel")


if __name__ == "__main__":
    main()