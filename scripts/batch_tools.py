"""Labelling helper.
  python scripts/batch_tools.py assistant                       write the assistant's labels for batch 2
  python scripts/batch_tools.py compare <your_labelled.csv>     agreement with the assistant's labels
  python scripts/batch_tools.py add <labelled.csv> <dev|test>   append a reviewed batch to scenarios.jsonl
CSV columns: id,lang,text,category,severity  (save from Excel as 'CSV UTF-8')"""
import csv
import json
import os
import sys
from collections import Counter

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
SC = os.path.join(ROOT, "research", "scenarios")
CATS = ["medical", "accident", "fire", "rescue", "other"]
SEVS = ["low", "medium", "high", "critical"]

ASSISTANT = {
    "S031": ("accident", "medium"), "S032": ("fire", "high"), "S033": ("medical", "critical"),
    "S034": ("other", "low"), "S035": ("medical", "critical"), "S036": ("fire", "low"),
    "S037": ("fire", "critical"), "S038": ("rescue", "critical"), "S039": ("medical", "medium"),
    "S040": ("fire", "critical"), "S041": ("accident", "critical"), "S042": ("medical", "low"),
    "S043": ("other", "low"), "S044": ("rescue", "critical"), "S045": ("other", "medium"),
    "S046": ("medical", "high"), "S047": ("other", "low"), "S048": ("accident", "critical"),
    "S049": ("rescue", "high"), "S050": ("fire", "critical"), "S051": ("other", "low"),
    "S052": ("medical", "high"), "S053": ("accident", "critical"), "S054": ("rescue", "high"),
    "S055": ("other", "low"), "S056": ("medical", "high"), "S057": ("other", "high"),
    "S058": ("fire", "critical"), "S059": ("accident", "low"), "S060": ("medical", "high"),
}
AMBIGUOUS = ["S032", "S045", "S046", "S049", "S060"]


def read(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def kappa(a, b):
    n = len(a)
    po = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / n ** 2
    return 1.0 if pe >= 1 else (po - pe) / (1 - pe)


def cmd_assistant():
    src = os.path.join(SC, "batch2_blank.csv")
    if not os.path.exists(src):
        sys.exit("Missing " + src + ". Create it from the earlier message first.")
    rows = read(src)
    out = os.path.join(SC, "batch2_assistant_labels.csv")
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["id", "lang", "text", "category", "severity"])
        for r in rows:
            cat, sev = ASSISTANT[r["id"]]
            w.writerow([r["id"], r["lang"], r["text"], cat, sev])
    print("Wrote", out)
    print("Ambiguous cases the assistant was unsure about:", ", ".join(AMBIGUOUS))


def cmd_compare(path):
    mine = read(path)
    ids = [r["id"] for r in mine]
    c1 = [r["category"].strip().lower() for r in mine]
    s1 = [r["severity"].strip().lower() for r in mine]
    bad = [i for i, c, s in zip(ids, c1, s1) if c not in CATS or s not in SEVS]
    if bad:
        sys.exit("Fill in valid labels first. Problem rows: " + ", ".join(bad))
    c2 = [ASSISTANT[i][0] for i in ids]
    s2 = [ASSISTANT[i][1] for i in ids]
    n = len(ids)
    print(f"{n} reports")
    print(f"category agreement {sum(a == b for a, b in zip(c1, c2)) / n:.0%}   Cohen kappa {kappa(c1, c2):.2f}")
    print(f"severity agreement {sum(a == b for a, b in zip(s1, s2)) / n:.0%}   Cohen kappa {kappa(s1, s2):.2f}")
    print("severity within one level "
          f"{sum(abs(SEVS.index(a) - SEVS.index(b)) <= 1 for a, b in zip(s1, s2)) / n:.0%}")
    print("\nDisagreements (yours | assistant's):")
    for r, a, b, x, y in zip(mine, c1, s1, c2, s2):
        if (a, b) != (x, y):
            print(f"  {r['id']}: {a}/{b} | {x}/{ASSISTANT[r['id']][1]}   {r['text'][:70]}")
    print("\nDecide each disagreement using your rubric, then fix the CSV before adding it.")


def cmd_add(path, split):
    if split not in ("dev", "test"):
        sys.exit("split must be dev or test")
    rows = read(path)
    target = os.path.join(SC, "scenarios.jsonl")
    existing = set()
    if os.path.exists(target):
        with open(target, encoding="utf-8") as f:
            existing = {json.loads(line)["id"] for line in f if line.strip()}
    bad = [r["id"] for r in rows if r["category"].strip().lower() not in CATS
           or r["severity"].strip().lower() not in SEVS]
    if bad:
        sys.exit("Invalid or empty labels in: " + ", ".join(bad))
    new = [r for r in rows if r["id"] not in existing]
    need_newline = False
    if os.path.exists(target) and os.path.getsize(target) > 0:
        with open(target, "rb") as f:
            f.seek(-1, 2)
            need_newline = f.read(1) != b"\n"
    with open(target, "a", encoding="utf-8") as f:
        if need_newline:
            f.write("\n")
        for r in new:
            f.write(json.dumps({"id": r["id"], "split": split, "lang": r["lang"], "text": r["text"],
                                "category": r["category"].strip().lower(),
                                "severity": r["severity"].strip().lower()}, ensure_ascii=False) + "\n")
    print(f"Added {len(new)} scenarios as {split}; skipped {len(rows) - len(new)} already present.")


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["assistant"]:
        cmd_assistant()
    elif a[:1] == ["compare"] and len(a) == 2:
        cmd_compare(a[1])
    elif a[:1] == ["add"] and len(a) == 3:
        cmd_add(a[1], a[2])
    else:
        print(__doc__)
