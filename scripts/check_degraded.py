"""One incident through the whole path, printing how the system behaves right now.
Run it normally, then again with Redis stopped, then with OSRM stopped."""
import sys
import time
import uuid

import httpx

c = httpx.Client(base_url="http://127.0.0.1:8000", timeout=40)
label = sys.argv[1] if len(sys.argv) > 1 else "run"

t = time.perf_counter()
r = c.post("/incidents", json={"description": f"DEGRADED {label}: fire near Town Hall",
                               "lat": 31.6262, "lon": 74.8731, "category": "fire",
                               "idempotency_key": str(uuid.uuid4())})
print(f"create incident  : HTTP {r.status_code} in {(time.perf_counter() - t) * 1000:.0f} ms")
if r.status_code != 201:
    print(r.text)
    sys.exit(1)
iid = r.json()["id"]

t = time.perf_counter()
r = c.get(f"/incidents/{iid}/recommendations")
recs = r.json().get("recommendations", []) if r.status_code == 200 else []
print(f"recommendations  : HTTP {r.status_code} in {(time.perf_counter() - t) * 1000:.0f} ms | "
      f"units {len(recs)} | eta_source {recs[0]['eta_source'] if recs else 'none'}")

a = None
for _ in range(25):
    a = c.get(f"/incidents/{iid}/assessment")
    if a.status_code == 200:
        break
    time.sleep(1)
print(f"incident stored  : {c.get(f'/incidents/{iid}').status_code == 200}")
print(f"AI assessment    : {a.json().get('source') if a is not None and a.status_code == 200 else 'not ready after 25s'}")