"""Deterministic keyword baseline. Used when the LLM is unavailable, as the
protocol safety floor, and as approach B in the experiments."""
import re

from app.ai.schemas import Assessment

CATEGORY_KEYWORDS = {
    "fire": ["fire", "smoke", "burning", "blaze", "explosion", "blast", "cylinder", "short circuit",
             "aag", "dhuan", "dhuaan", "आग", "धुआं", "ਅੱਗ", "ਧੂੰਆਂ"],
    "accident": ["accident", "collision", "crash", "overturned", "rammed", "hit and run",
                 "takkar", "takkar", "hadsa", "hadsaa", "टक्कर", "हादसा", "ਟੱਕਰ", "ਹਾਦਸਾ"],
    "medical": ["heart attack", "chest pain", "unconscious", "not breathing", "faint", "seizure",
                "bleeding", "labour", "pregnant", "stroke", "overdose", "behosh", "dil ka daura",
                "saans", "बेहोश", "सांस", "ਬੇਹੋਸ਼", "ਸਾਹ"],
    "rescue": ["trapped", "stuck", "collapse", "collapsed", "drowning", "flood", "fas gaya",
               "fas gayi", "fasya", "fase hue", "डूब", "फंस", "ਫਸ", "ਡੁੱਬ"],
}
CRITICAL = ["not breathing", "no pulse", "unconscious", "severe bleeding", "heavily bleeding",
            "trapped", "explosion", "blast", "collapse", "collapsed", "drowning", "heart attack",
            "behosh", "fas gaya", "fas gayi", "fasya", "बेहोश", "फंस", "ਬੇਹੋਸ਼", "ਫਸ"]
HIGH = ["fire", "smoke", "injured", "bleeding", "chest pain", "collision", "crash", "overturned",
        "seizure", "ghayal", "zakhmi", "घायल", "ਜ਼ਖਮੀ", "ਜ਼ਖ਼ਮੀ"]

NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
       "ek": 1, "ik": 1, "do": 2, "teen": 3, "char": 4, "panj": 5}
COUNT_RE = re.compile(r"\b(\d{1,3}|" + "|".join(NUM) +
                      r")\s+(?:people|persons|person|injured|hurt|log|bande|banday|ghayal|zakhmi)\b")


def _has(text: str, kw: str) -> bool:
    if kw.isascii():
        return re.search(r"\b" + re.escape(kw) + r"\w*", text) is not None
    return kw in text


def protocol_floor(report: str) -> str:
    """Minimum severity the protocol guarantees, whatever the LLM says."""
    t = report.lower()
    if any(_has(t, k) for k in CRITICAL):
        return "critical"
    if any(_has(t, k) for k in HIGH):
        return "high"
    return "low"


def rule_assessment(report: str) -> Assessment:
    t = report.lower()
    hits = {c: [k for k in kws if _has(t, k)] for c, kws in CATEGORY_KEYWORDS.items()}
    best = max(hits, key=lambda c: len(hits[c]))
    category = best if hits[best] else "other"

    severity = protocol_floor(report)
    if severity == "low" and category == "medical":
        severity = "medium"

    injuries = None
    m = COUNT_RE.search(t)
    if m:
        injuries = int(m.group(1)) if m.group(1).isdigit() else NUM[m.group(1)]
    matched = hits.get(category, [])
    return Assessment(
        category=category, severity=severity, injuries=injuries,
        trapped=any(_has(t, k) for k in ("trapped", "stuck", "fas gaya", "fasya", "फंस", "ਫਸ")),
        location_clues=[], confidence=0.55 if matched else 0.25,
        reasoning=("Keyword rules matched: " + ", ".join(matched)) if matched
        else "No emergency keywords matched; needs dispatcher review.")