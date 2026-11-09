import json
import math
import os
import random
import sys

import httpx

API = "http://127.0.0.1:8000"
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
CENTER_LON, CENTER_LAT, R = 74.8765, 31.62, 2800


def point():
    r = R * math.sqrt(random.random())
    th = 2 * math.pi * random.random()
    return (CENTER_LON + r * math.cos(th) / (111320.0 * math.cos(math.radians(CENTER_LAT))),
            CENTER_LAT + r * math.sin(th) / 111320.0)


n = int(sys.argv[1]) if len(sys.argv) > 1 else 8
path = os.path.join(ROOT, "research", "scenarios", "scenarios.jsonl")
texts = [json.loads(line)["text"] for line in open(path, encoding="utf-8") if line.strip()]
for t in random.sample(texts, min(n, len(texts))):
    lon, lat = point()
    r = httpx.post(f"{API}/incidents", json={"description": t, "lat": lat, "lon": lon})
    print(r.status_code, r.json().get("id"), t[:60])