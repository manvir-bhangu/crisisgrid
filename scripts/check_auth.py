"""Access-control checks. Run with the server up and AUTH_ENABLED=true.
Wait a minute between runs: the rate-limit test fills the anonymous bucket."""
import os
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor

import httpx
from dotenv import dotenv_values
from websockets.exceptions import InvalidStatus
from websockets.sync.client import connect

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
KEY = dotenv_values(os.path.join(ROOT, ".env")).get("SERVICE_API_KEY", "")
HOST = "127.0.0.1:8000"

anon = httpx.Client(base_url="http://" + HOST, timeout=15)
svc = httpx.Client(base_url="http://" + HOST, timeout=15, headers={"X-API-Key": KEY})
fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok or detail == "" else f"    [{detail}]"))
    fails += 0 if ok else 1


if not KEY:
    sys.exit("SERVICE_API_KEY is empty in .env")
if anon.get("/resources").status_code == 200:
    sys.exit("GET /resources worked without logging in: AUTH_ENABLED is false, or uvicorn was not restarted.")

for method, path, body in [
        ("GET", "/resources", None), ("GET", "/facilities", None), ("GET", "/incidents", None),
        ("GET", "/incidents/1", None), ("GET", "/dispatch/assignments", None),
        ("POST", "/dispatch/plan", None),
        ("POST", "/dispatch/assign", {"incident_id": 1, "resource_id": 1}),
        ("POST", "/resources/1/location", {"lat": 31.6, "lon": 74.8}),
        ("POST", "/incidents/1/confirm", {"category": "fire"})]:
    r = anon.request(method, path, json=body)
    check(f"anonymous {method} {path} is refused", r.status_code == 401, r.status_code)

r = anon.get("/resources", headers={"Cookie": "cg_session=abc.def"})
check("forged session cookie is refused", r.status_code == 401, r.status_code)
r = anon.get("/resources", headers={"X-API-Key": "wrong-key"})
check("wrong service key is refused", r.status_code == 401, r.status_code)
check("correct service key is accepted", svc.get("/resources").status_code == 200)

r = anon.get("/dashboard", follow_redirects=False)
check("dashboard redirects strangers to login",
      r.status_code in (302, 303, 307) and r.headers.get("location", "").startswith("/login"), r.status_code)
check("login page is public", anon.get("/login").status_code == 200)
check("citizen report page is public", anon.get("/report").status_code == 200)

try:
    with connect(f"ws://{HOST}/ws", open_timeout=5):
        check("anonymous WebSocket is refused", False, "connection was accepted")
except InvalidStatus as exc:
    check("anonymous WebSocket is refused", exc.response.status_code in (401, 403), exc.response.status_code)
except Exception as exc:
    check("anonymous WebSocket is refused", False, repr(exc))

r = anon.post("/incidents", json={"description": "AUTHTEST citizen with forged category",
                                  "lat": 31.634, "lon": 74.8723, "category": "other"})
if r.status_code == 201:
    inc = svc.get(f"/incidents/{r.json()['id']}").json()
    check("citizen cannot set a verified category",
          inc["category"] is None and inc["category_confirmed"] is False, inc)
else:
    check("citizen report accepted", False, f"{r.status_code}: wait a minute and rerun")

key = "authtest-" + uuid.uuid4().hex


def post_same_key(_):
    r = svc.post("/incidents", json={"description": "AUTHTEST simultaneous retry",
                                     "lat": 31.634, "lon": 74.8723, "idempotency_key": key})
    return r.status_code, (r.json().get("id") if r.status_code == 201 else None)


with ThreadPoolExecutor(max_workers=10) as pool:
    results = list(pool.map(post_same_key, range(10)))
check("10 simultaneous retries with one key give one incident and no errors",
      all(code == 201 for code, _ in results) and len({i for _, i in results}) == 1, results)

codes = [anon.post("/incidents", json={"description": "AUTHTEST rate limit",
                                       "lat": 31.634, "lon": 74.8723}).status_code for _ in range(15)]
check("anonymous reports are rate limited", 429 in codes, codes)

print("\nClean up the test incidents with:")
print("docker exec -it crisisgrid_db psql -U crisis -d crisisgrid -c "
      "\"UPDATE incidents SET status='cancelled' WHERE raw_text LIKE 'AUTHTEST%';\"")
print("\nALL CHECKS PASSED" if fails == 0 else f"\n{fails} CHECK(S) FAILED")
sys.exit(1 if fails else 0)