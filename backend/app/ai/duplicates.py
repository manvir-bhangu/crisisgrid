"""Heuristic duplicate finder: nearby + recent + similar wording. The dispatcher decides."""
import re

from sqlalchemy import text

RADIUS_M = 300
WINDOW_MIN = 30

SQL = text("""
    SELECT o.id, o.raw_text, o.status,
           ST_Distance(o.location, me.location) AS dist_m,
           EXTRACT(EPOCH FROM (me.created_at - o.created_at)) / 60.0 AS minutes_apart
    FROM incidents me, incidents o
    WHERE me.id = :i AND o.id <> me.id
      AND o.status NOT IN ('resolved', 'cancelled', 'duplicate')
      AND o.created_at > me.created_at - make_interval(mins => :w)
      AND ST_DWithin(o.location, me.location, :r)
""")


def _tokens(s: str) -> set[str]:
    return {w for w in re.findall(r"\w+", s.lower()) if len(w) > 2}


def find_duplicates(conn, incident_id: int, report: str, top: int = 3) -> list[dict]:
    mine = _tokens(report)
    out = []
    for o in conn.execute(SQL, {"i": incident_id, "w": WINDOW_MIN, "r": RADIUS_M}).mappings():
        theirs = _tokens(o["raw_text"])
        sim = len(mine & theirs) / len(mine | theirs) if mine | theirs else 0.0
        dist = float(o["dist_m"])
        score = 0.5 * (1 - dist / RADIUS_M) + 0.5 * sim
        if score >= 0.35:
            out.append({"incident_id": o["id"], "distance_m": round(dist),
                        "minutes_apart": round(abs(float(o["minutes_apart"])), 1),
                        "text_similarity": round(sim, 2), "score": round(score, 2),
                        "snippet": o["raw_text"][:80]})
    return sorted(out, key=lambda d: -d["score"])[:top]