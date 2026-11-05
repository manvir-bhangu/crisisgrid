from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from app.allocation.candidates import recommend
from app.core.config import settings
from app.db.session import engine

router = APIRouter(prefix="/incidents", tags=["incidents"])

RESOURCE_FOR_CATEGORY = {"medical": "ambulance", "accident": "ambulance",
                         "fire": "fire_truck", "rescue": "rescue"}


class IncidentIn(BaseModel):
    description: str = Field(min_length=3, max_length=2000)
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    category: str | None = None          # AI fills this in later (Step 9)
    idempotency_key: str | None = None


def _get(conn, incident_id: int):
    return conn.execute(text("""
        SELECT id, raw_text, category, severity, status, created_at,
               ST_Y(location::geometry) AS lat, ST_X(location::geometry) AS lon
        FROM incidents WHERE id = :i"""), {"i": incident_id}).mappings().first()


@router.post("", status_code=201)
def create_incident(body: IncidentIn):
    with engine.begin() as conn:
        if body.idempotency_key:
            existing = conn.execute(text("SELECT id FROM incidents WHERE idempotency_key = :k"),
                                    {"k": body.idempotency_key}).scalar()
            if existing:
                return dict(_get(conn, existing))

        inside = conn.execute(text("""
            SELECT ST_Covers(z.geom, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography)
            FROM zones z WHERE z.name = :z"""),
            {"lon": body.lon, "lat": body.lat, "z": settings.zone_name}).scalar()
        if not inside:
            raise HTTPException(422, "Location is outside the service zone")

        new_id = conn.execute(text("""
            INSERT INTO incidents (raw_text, category, location, idempotency_key)
            VALUES (:t, :c, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, :k)
            RETURNING id"""),
            {"t": body.description, "c": body.category, "lon": body.lon,
             "lat": body.lat, "k": body.idempotency_key}).scalar()
        return dict(_get(conn, new_id))


@router.get("/{incident_id}")
def get_incident(incident_id: int):
    with engine.connect() as conn:
        row = _get(conn, incident_id)
    if not row:
        raise HTTPException(404, "Incident not found")
    return dict(row)


@router.get("/{incident_id}/recommendations")
def recommendations(incident_id: int, resource_type: str | None = None, limit: int = 3):
    with engine.connect() as conn:
        inc = _get(conn, incident_id)
        if not inc:
            raise HTTPException(404, "Incident not found")
        rtype = resource_type or RESOURCE_FOR_CATEGORY.get(inc["category"] or "", "ambulance")
        recs = recommend(conn, inc["lon"], inc["lat"], rtype, top=limit)
    return {"incident_id": incident_id, "resource_type": rtype, "recommendations": recs}