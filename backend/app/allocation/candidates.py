from sqlalchemy import text

from app.allocation.routing_client import travel_times
from app.core.config import settings

CANDIDATE_SQL = text("""
    SELECT r.id, r.code, r.type, r.status,
           ST_X(r.last_location::geometry) AS lon,
           ST_Y(r.last_location::geometry) AS lat,
           ST_Distance(r.last_location,
                       ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography) AS straight_m
    FROM resources r
    WHERE r.status = 'available'
      AND r.type = :rtype
      AND r.last_location IS NOT NULL
    ORDER BY r.last_location <-> ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography
    LIMIT :k
""")


def candidate_rows(conn, lon: float, lat: float, rtype: str, k: int = 10) -> list[dict]:
    """Database part only. Call this inside a connection, then release the connection."""
    rows = conn.execute(CANDIDATE_SQL, {"lon": lon, "lat": lat, "rtype": rtype, "k": k}).mappings().all()
    return [dict(r) for r in rows]


def _fallback(rows):
    speed_ms = settings.fallback_speed_kmh * 1000 / 3600
    return [{"resource_id": r["id"], "code": r["code"], "type": r["type"],
             "eta_seconds": round(r["straight_m"] / speed_ms),
             "road_distance_m": None,
             "straight_line_m": round(r["straight_m"]),
             "eta_source": "straight_line_fallback"} for r in rows]


def rank(rows: list[dict], lon: float, lat: float, top: int = 3) -> list[dict]:
    """Network part: road travel times from OSRM, straight-line fallback if unavailable.
    Holds no database connection."""
    if not rows:
        return []

    out = []
    result = travel_times([(r["lon"], r["lat"]) for r in rows], (lon, lat))
    if result is not None:
        durations, distances = result
        for r, dur, dist in zip(rows, durations, distances):
            if dur is None:              # OSRM found no road route for this unit
                continue
            out.append({"resource_id": r["id"], "code": r["code"], "type": r["type"],
                        "eta_seconds": round(dur), "road_distance_m": round(dist),
                        "straight_line_m": round(r["straight_m"]), "eta_source": "osrm"})

    if not out:                          # OSRM down, or it returned no usable routes
        out = _fallback(rows)

    out.sort(key=lambda x: x["eta_seconds"])
    for position, item in enumerate(out[:top], start=1):
        item["rank"] = position
    return out[:top]


def recommend(conn, lon: float, lat: float, rtype: str, top: int = 3, k: int = 10):
    """Convenience wrapper kept for scripts. The API uses the two-step version."""
    return rank(candidate_rows(conn, lon, lat, rtype, k), lon, lat, top)