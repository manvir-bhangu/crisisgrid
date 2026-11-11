import json
import os
from collections import Counter

path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "research", "scenarios", "scenarios.jsonl")
rows = [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]
print(len(rows), "scenarios")
for key in ("split", "category", "severity", "lang"):
    print(f"{key:9}", dict(sorted(Counter(r[key] for r in rows).items())))
ids = [r["id"] for r in rows]
print("duplicate ids:", len(ids) - len(set(ids)))
