import math

import httpx
import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from app.allocation.optimizer import hungarian
from app.api.dispatch import AssignIn, assign
from app.core.config import settings
from app.db.session import engine

router = APIRouter(prefix="/dispatch", tags=["planner"])

WEIGHT = {"critical": 8, "high": 4, "medium": 2, "low": 1}
TYPE_FOR = {"medical": "ambulance", "accident": "ambulance", "fire": "fire_truck", "rescue": "rescue"}

INCIDENTS_SQL = text("""
    SELECT i.id, i.raw_text, i.category_confirmed,
           COALESCE(i.category, a.category) AS category,
           COALESCE(i.severity, a.severity) AS severity,
           ST_X(i.location::geometry) AS lon, ST_Y(i.location::geometry) AS lat
    FROM incidents i
    LEFT JOIN LATERAL (SELECT category, severity FROM ai_assessments
                       WHERE incident_id = i.id ORDER BY id DESC LIMIT 1) a ON TRUE
    WHERE i.status = 'new'
      AND NOT EXISTS (SELECT 1 FROM assignments s WHERE s.incident_id = i.id
                      AND s.status NOT IN ('completed', 'cancelled'))
    ORDER BY i.id""")

UNITS_SQL = text("""
    SELECT id, code, type, ST_X(last_location::geometry) AS lon, ST_Y(last_location::geometry) AS lat
    FROM resources WHERE status = 'available' AND last_location IS NOT NULL ORDER BY code""")


def _hav(a_lon, a_lat, b_lon, b_lat):
    la1, la2 = math.radians(a_lat), math.radians(b_lat)
    dla, dlo = la2 - la1, math.radians(b_lon - a_lon)
    h = math.sin(dla / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(dlo / 2) ** 2
    return 2 * 6371000.0 * math.asin(math.sqrt(h))


def _matrix(units, incs):
    """Travel seconds, units x incidents. Road times from OSRM, straight-line estimate if it is down."""
    k = len(units)
    coords = ";".join(f"{p['lon']:.6f},{p['lat']:.6f}" for p in units + incs)
    try:
        r = httpx.get(f"{settings.osrm_url}/table/v1/driving/{coords}", timeout=5, params={
            "sources": ";".join(str(i) for i in range(k)),
            "destinations": ";".join(str(k + j) for j in range(len(incs))),
            "annotations": "duration"})
        r.raise_for_status()
        d = r.json()
        if d.get("code") != "Ok":
            raise RuntimeError(d.get("code"))
        return (np.array([[np.nan if v is None else v for v in row] for row in d["durations"]], dtype=float),
                "osrm")
    except Exception:
        speed = settings.fallback_speed_kmh * 1000 / 3600
        return (np.array([[_hav(u["lon"], u["lat"], i["lon"], i["lat"]) / speed for i in incs] for u in units]),
                "straight_line_fallback")


@router.post("/plan")
def plan():
    with engine.connect() as conn:
        incs = [dict(r) for r in conn.execute(INCIDENTS_SQL).mappings().all()]
        units = [dict(r) for r in conn.execute(UNITS_SQL).mappings().all()]

    groups, skipped = {}, []
    for i in incs:
        rtype = TYPE_FOR.get(i["category"] or "")
        if rtype is None:
            skipped.append({"incident_id": i["id"], "text": i["raw_text"][:90],
                            "reason": "no category or 'other': needs dispatcher review"})
        else:
            groups.setdefault(rtype, []).append(i)

    pairs, unserved, sources = [], [], set()
    for rtype, ii in groups.items():
        uu = [u for u in units if u["type"] == rtype]
        if not uu:
            unserved += [{"incident_id": i["id"], "text": i["raw_text"][:90],
                          "reason": f"no available {rtype}"} for i in ii]
            continue
        T, src = _matrix(uu, ii)
        sources.add(src)
        w = [WEIGHT.get(i["severity"] or "", 2) for i in ii]
        result = hungarian(T, w)
        for j, ui in result.items():
            pairs.append({"incident_id": ii[j]["id"], "resource_id": uu[ui]["id"], "code": uu[ui]["code"],
                          "resource_type": rtype, "eta_seconds": round(float(T[ui][j])),
                          "severity": ii[j]["severity"], "category": ii[j]["category"],
                          "confirmed": bool(ii[j]["category_confirmed"]), "text": ii[j]["raw_text"][:90],
                          "weight": w[j]})
        unserved += [{"incident_id": ii[j]["id"], "text": ii[j]["raw_text"][:90],
                      "reason": f"not enough available {rtype}"} for j in range(len(ii)) if j not in result]

    pairs.sort(key=lambda p: (-p["weight"], p["eta_seconds"]))
    return {"pairs": pairs, "unserved": unserved, "skipped": skipped,
            "eta_source": "straight_line_fallback" if "straight_line_fallback" in sources else "osrm",
            "open_incidents": len(incs), "available_units": len(units)}


class Pair(BaseModel):
    incident_id: int
    resource_id: int


class ApplyIn(BaseModel):
    pairs: list[Pair]


@router.post("/plan/apply")
def apply_plan(body: ApplyIn):
    results = []
    for p in body.pairs:
        try:
            out = assign(AssignIn(incident_id=p.incident_id, resource_id=p.resource_id,
                                  assigned_by="optimizer+dispatcher"))
            results.append({**p.model_dump(), "ok": True, "assignment_id": out["assignment_id"]})
        except HTTPException as exc:
            results.append({**p.model_dump(), "ok": False, "error": exc.detail})
    return {"results": results}