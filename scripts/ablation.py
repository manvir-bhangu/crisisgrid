"""Separates the LLM from the protocol floor. Uses cached LLM answers where they exist.
  python scripts/ablation.py --split test
Prints a summary table; writes case lists (UTF-8) to research/results/ablation_<split>.txt"""
import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, os.path.join(ROOT, "backend"))

from app.ai.fallback_rules import protocol_floor, rule_assessment  # noqa: E402
from app.ai.provider import call_llm  # noqa: E402
from app.ai.schemas import SEV_ORDER  # noqa: E402


def load(split):
    path = os.path.join(ROOT, "research", "scenarios", "scenarios.jsonl")
    rows = [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]
    return [r for r in rows if split == "all" or r["split"] == split]


def llm(text):
    for attempt in range(4):
        try:
            a, meta = call_llm(text)
            return a, meta.get("cached", False)
        except Exception:
            time.sleep(8 * (attempt + 1))
    return None, False


def stats(name, truth, pred):
    n = len(truth)
    exact = sum(t == p for t, p in zip(truth, pred)) / n
    under = sum(SEV_ORDER[p] < SEV_ORDER[t] for t, p in zip(truth, pred)) / n
    over = sum(SEV_ORDER[p] > SEV_ORDER[t] for t, p in zip(truth, pred)) / n
    crit_true = [i for i, t in enumerate(truth) if t == "critical"]
    crit_pred = [i for i, p in enumerate(pred) if p == "critical"]
    recall = sum(pred[i] == "critical" for i in crit_true) / len(crit_true) if crit_true else float("nan")
    prec = sum(truth[i] == "critical" for i in crit_pred) / len(crit_pred) if crit_pred else float("nan")
    print(f"{name:24} exact {exact:6.1%} | under {under:6.1%} | over {over:6.1%} | "
          f"critical recall {recall:6.1%} | critical precision {prec:6.1%}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="test", choices=["all", "dev", "test"])
    args = ap.parse_args()

    rows = load(args.split)
    kept, truth, raw, final, rules, floors, cat_err = [], [], [], [], [], [], []
    skipped = 0
    for i, r in enumerate(rows, 1):
        a, cached = llm(r["text"])
        if a is None:
            skipped += 1
            continue
        if not cached:
            time.sleep(4.0)
        floor = protocol_floor(r["text"])
        fin = floor if SEV_ORDER[a.severity] < SEV_ORDER[floor] else a.severity
        kept.append(r)
        truth.append(r["severity"])
        raw.append(a.severity)
        final.append(fin)
        floors.append(floor)
        rules.append(rule_assessment(r["text"]).severity)
        if a.category != r["category"]:
            cat_err.append((r, a.category))
        print(f"  {i}/{len(rows)}", end="\r")
    print()
    if skipped:
        print(f"WARNING: {skipped} scenarios skipped because the LLM failed. Run again to fill them in.")

    print(f"\nSeverity on {len(kept)} {args.split} scenarios")
    stats("B rules only", truth, rules)
    stats("LLM alone (no floor)", truth, raw)
    stats("LLM + floor (system C)", truth, final)

    lines = []
    changed = [(r, a, f, fin) for r, a, f, fin in zip(kept, raw, floors, final) if a != fin]
    helped = sum(abs(SEV_ORDER[fin] - SEV_ORDER[r["severity"]]) < abs(SEV_ORDER[a] - SEV_ORDER[r["severity"]])
                 for r, a, f, fin in changed)
    hurt = sum(abs(SEV_ORDER[fin] - SEV_ORDER[r["severity"]]) > abs(SEV_ORDER[a] - SEV_ORDER[r["severity"]])
               for r, a, f, fin in changed)
    print(f"\nFloor changed the LLM's severity on {len(changed)} reports: helped {helped}, hurt {hurt}, "
          f"neutral {len(changed) - helped - hurt}")

    lines.append(f"FLOOR CHANGED THE ANSWER ({len(changed)} reports; helped {helped}, hurt {hurt})")
    for r, a, f, fin in changed:
        d_before = abs(SEV_ORDER[a] - SEV_ORDER[r["severity"]])
        d_after = abs(SEV_ORDER[fin] - SEV_ORDER[r["severity"]])
        verdict = "HELPED" if d_after < d_before else "HURT" if d_after > d_before else "neutral"
        lines.append(f"{r['id']} {verdict}: truth={r['severity']} llm={a} floor={f} final={fin} | {r['text'][:110]}")

    lines.append("")
    lines.append(f"CATEGORY ERRORS OF THE LLM ({len(cat_err)})")
    for r, pred in cat_err:
        lines.append(f"{r['id']}: truth={r['category']} llm={pred} | {r['text'][:110]}")

    lines.append("")
    lines.append("FINAL SEVERITY WRONG BY TWO OR MORE LEVELS")
    for r, fin in zip(kept, final):
        if abs(SEV_ORDER[fin] - SEV_ORDER[r["severity"]]) >= 2:
            lines.append(f"{r['id']}: truth={r['severity']} final={fin} | {r['text'][:110]}")

    out = os.path.join(ROOT, "research", "results", f"ablation_{args.split}.txt")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"\nCase lists saved to {out} (open it in VS Code)")


if __name__ == "__main__":
    main()
