"""Compares B (rules only) with C (LLM + protocol floor, rules on failure)
on a labelled scenario file. LLM answers are cached, so re-runs are free."""
import argparse
import csv
import json
import math
import os
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, os.path.join(ROOT, "backend"))

from app.ai.fallback_rules import protocol_floor, rule_assessment  # noqa: E402
from app.ai.provider import call_llm  # noqa: E402
from app.ai.schemas import SEV_ORDER  # noqa: E402
from app.core.config import settings  # noqa: E402

CATS = ["medical", "accident", "fire", "rescue", "other"]
SEVS = ["low", "medium", "high", "critical"]


def load(path, split):
    rows = []
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            assert r["category"] in CATS and r["severity"] in SEVS, f"bad label on line {n}"
            if split == "all" or r["split"] == split:
                rows.append(r)
    return rows


def predict_b(text):
    a = rule_assessment(text)
    return a.category, a.severity


def predict_c(text):
    floor = protocol_floor(text)
    err = ""
    for attempt in range(4):
        try:
            a, meta = call_llm(text)
            sev = floor if SEV_ORDER[a.severity] < SEV_ORDER[floor] else a.severity
            return a.category, sev, "llm", meta.get("cached", False)
        except Exception as exc:
            err = repr(exc)[:120]
            time.sleep(8 * (attempt + 1))     # back off: 8s, 16s, 24s, 32s
    a = rule_assessment(text)
    return a.category, a.severity, "rules_fallback:" + err, False


def macro_f1(truth, pred):
    f1s = []
    for c in CATS:
        tp = sum(t == c and p == c for t, p in zip(truth, pred))
        fp = sum(t != c and p == c for t, p in zip(truth, pred))
        fn = sum(t == c and p != c for t, p in zip(truth, pred))
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        f1s.append(2 * prec * rec / (prec + rec) if prec + rec else 0.0)
    return sum(f1s) / len(f1s)


def mcnemar_p(b, c):
    """Exact two-sided McNemar test. b = only A correct, c = only B correct."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)


def confusion(truth, pred, labels):
    m = {t: Counter() for t in labels}
    for t, p in zip(truth, pred):
        m[t][p] += 1
    head = "true \\ pred".ljust(12) + "".join(l[:8].rjust(9) for l in labels)
    return "\n".join([head] + [t.ljust(12) + "".join(str(m[t][p]).rjust(9) for p in labels) for t in labels])


def metrics(name, rows, cats, sevs):
    tc = [r["category"] for r in rows]
    ts = [r["severity"] for r in rows]
    n = len(rows)
    cat_acc = sum(a == b for a, b in zip(tc, cats)) / n
    sev_acc = sum(a == b for a, b in zip(ts, sevs)) / n
    within1 = sum(abs(SEV_ORDER[a] - SEV_ORDER[b]) <= 1 for a, b in zip(ts, sevs)) / n
    under = sum(SEV_ORDER[b] < SEV_ORDER[a] for a, b in zip(ts, sevs)) / n
    crit = [(a, b) for a, b in zip(ts, sevs) if a == "critical"]
    crit_missed = sum(b != "critical" for a, b in crit)
    print(f"\n=== {name} (n={n}) ===")
    print(f"category accuracy      {cat_acc:.1%}")
    print(f"category macro-F1      {macro_f1(tc, cats):.3f}")
    print(f"severity exact         {sev_acc:.1%}")
    print(f"severity within 1      {within1:.1%}")
    print(f"under-triage rate      {under:.1%}   (severity rated LOWER than truth)")
    print(f"critical cases missed  {crit_missed}/{len(crit)}")
    print("\ncategory confusion:\n" + confusion(tc, cats, CATS))
    print("\nseverity confusion:\n" + confusion(ts, sevs, SEVS))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=os.path.join(ROOT, "research", "scenarios", "scenarios.jsonl"))
    ap.add_argument("--split", default="all", choices=["all", "dev", "test"])
    ap.add_argument("--no-llm", action="store_true")
    args = ap.parse_args()

    rows = load(args.file, args.split)
    use_llm = settings.ai_enabled and bool(settings.gemini_api_key) and not args.no_llm
    print(f"{len(rows)} scenarios | split={args.split} | model={settings.gemini_model if use_llm else 'none'}")

    b_cat, b_sev, c_cat, c_sev, srcs = [], [], [], [], []
    for i, r in enumerate(rows, 1):
        bc, bs = predict_b(r["text"])
        b_cat.append(bc)
        b_sev.append(bs)
        if use_llm:
            cc, cs, src, cached = predict_c(r["text"])
            c_cat.append(cc)
            c_sev.append(cs)
            srcs.append(src)
            if not cached:
                time.sleep(4.0)       # stay under free-tier rate limits
            print(f"  {i}/{len(rows)} {r['id']} -> {src[:30]}{' (cached)' if cached else ''}      ", end="\r")
    print()

    metrics("B: rules only", rows, b_cat, b_sev)
    if use_llm:
        metrics("C: CrisisGrid (LLM + protocol floor)", rows, c_cat, c_sev)
        fb = sum(s.startswith("rules_fallback") for s in srcs)
        print(f"\nLLM failures that fell back to rules: {fb}/{len(rows)}")
        if fb:
            print("WARNING: these runs are partly rules-only. Re-run until this is 0 before reporting.")

        only_b = sum(bc == r["category"] and cc != r["category"] for r, bc, cc in zip(rows, b_cat, c_cat))
        only_c = sum(bc != r["category"] and cc == r["category"] for r, bc, cc in zip(rows, b_cat, c_cat))
        print(f"\nCategory, paired comparison: only B right = {only_b}, only C right = {only_c}, "
              f"McNemar exact p = {mcnemar_p(only_b, only_c):.3f}")
        if len(rows) < 100:
            print("NOTE: fewer than 100 scenarios; treat differences as indicative, not proven.")

        by = defaultdict(lambda: [0, 0, 0])
        for r, bc, cc in zip(rows, b_cat, c_cat):
            by[r["lang"]][0] += 1
            by[r["lang"]][1] += bc == r["category"]
            by[r["lang"]][2] += cc == r["category"]
        print("\nCategory accuracy by language (B / C):")
        for lang, (n, b, c) in sorted(by.items()):
            print(f"  {lang:6} n={n:3}  {b / n:.0%} / {c / n:.0%}")

    out = os.path.join(ROOT, "research", "results", f"run_{datetime.now():%Y%m%d_%H%M%S}.csv")
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "split", "lang", "true_cat", "true_sev", "B_cat", "B_sev", "C_cat", "C_sev", "C_source", "text"])
        for i, r in enumerate(rows):
            w.writerow([r["id"], r["split"], r["lang"], r["category"], r["severity"], b_cat[i], b_sev[i],
                        c_cat[i] if use_llm else "", c_sev[i] if use_llm else "",
                        srcs[i] if use_llm else "", r["text"]])
    print(f"\nPer-scenario results saved to {out}")


if __name__ == "__main__":
    main()