from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.ai.analyzer import analyze
from app.allocation.candidates import candidate_rows, rank
from app.core import security
from app.core.config import settings
from app.db.session import engine
from app.realtime.events import publish

router = APIRouter(prefix="/incidents", tags=["incidents"])
DISPATCH = Depends(security.require(*security.DISPATCH_ROLES))

RESOURCE_FOR_CATEGORY = {"medical": "ambulance", "accident": "ambulance",
                         "fire": "fire_truck", "rescue": "rescue"}


class IncidentIn(BaseModel):
    description: str = Field(min_length=3, max_length=2000)
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    category: str | None = None          # honoured only for logged-in staff
    idempotency_key: str | None = None


def _get(conn, incident_id: int):
    return conn.execute(text("""
        SELECT id, raw_text, category, category_confirmed, severity, status, duplicate_of, created_at,
               ST_Y(location::geometry) AS lat, ST_X(location::geometry) AS lon
        FROM incidents WHERE id = :i"""), {"i": incident_id}).mappings().first()


@router.post("", status_code=201, dependencies=[Depends(security.public_report_limit)])
def create_incident(body: IncidentIn, background: BackgroundTasks, request: Request):
    user = security.get_user(request)
    category = body.category if user else None      # a stranger cannot create a "verified" incident
    with engine.begin() as conn:
        inside = conn.execute(text("""
            SELECT ST_Covers(z.geom, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography)
            FROM zones z WHERE z.name = :z"""),
            {"lon": body.lon, "lat": body.lat, "z": settings.zone_name}).scalar()
        if not inside:
            raise HTTPException(422, "Location is outside the service zone")

        # One statement: a repeated or simultaneous submit with the same key creates nothing new
        new_id = conn.execute(text("""
            INSERT INTO incidents (raw_text, category, category_confirmed, location, idempotency_key)
            VALUES (:t, :c, :cc, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, :k)
            ON CONFLICT (idempotency_key) DO NOTHING
            RETURNING id"""),
            {"t": body.description, "c": category, "cc": category is not None,
             "lon": body.lon, "lat": body.lat, "k": body.idempotency_key}).scalar()
        if new_id is None:
            existing = conn.execute(text("SELECT id FROM incidents WHERE idempotency_key = :k"),
                                    {"k": body.idempotency_key}).scalar()
            return dict(_get(conn, existing))       # already received: no new event, no new AI call
        row = dict(_get(conn, new_id))

    publish("incident_created", row)         # after commit
    background.add_task(analyze, new_id)     # AI runs after the response is sent
    return row


@router.get("", dependencies=[DISPATCH])
def list_incidents(active_only: bool = True, limit: int = 100):
    sql = """SELECT id, raw_text, category, category_confirmed, severity, status, created_at,
                    ST_Y(location::geometry) AS lat, ST_X(location::geometry) AS lon
             FROM incidents
             WHERE (:a = FALSE OR status NOT IN ('resolved', 'cancelled', 'duplicate'))
             ORDER BY id DESC LIMIT :n"""
    with engine.connect() as conn:
        rows = conn.execute(text(sql), {"a": active_only, "n": limit}).mappings().all()
    return [dict(r) for r in rows]


@router.get("/{incident_id}", dependencies=[DISPATCH])
def get_incident(incident_id: int):
    with engine.connect() as conn:
        row = _get(conn, incident_id)
    if not row:
        raise HTTPException(404, "Incident not found")
    return dict(row)


@router.get("/{incident_id}/recommendations", dependencies=[DISPATCH])
def recommendations(incident_id: int, resource_type: str | None = None, limit: int = 3):
    with engine.connect() as conn:
        inc = _get(conn, incident_id)
        if not inc:
            raise HTTPException(404, "Incident not found")
        rtype = resource_type or RESOURCE_FOR_CATEGORY.get(inc["category"] or "", "ambulance")
        rows = candidate_rows(conn, inc["lon"], inc["lat"], rtype)
    # The database connection is released above. The slow network call below must not hold one.
    recs = rank(rows, inc["lon"], inc["lat"], top=limit)
    return {"incident_id": incident_id, "resource_type": rtype, "recommendations": recs}
