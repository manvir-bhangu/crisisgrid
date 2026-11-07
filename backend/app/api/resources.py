from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.db.session import engine
from app.realtime.events import publish

router = APIRouter(prefix="/resources", tags=["resources"])
facilities_router = APIRouter(prefix="/facilities", tags=["facilities"])


class LocationIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


@router.get("")
def list_resources(status: str | None = None, type: str | None = None):
    sql = """SELECT r.id, r.code, r.type, r.status, r.capabilities, r.is_simulated,
                    ST_Y(r.last_location::geometry) AS lat, ST_X(r.last_location::geometry) AS lon,
                    ST_Y(f.location::geometry) AS home_lat, ST_X(f.location::geometry) AS home_lon
             FROM resources r LEFT JOIN facilities f ON f.id = r.home_facility_id
             WHERE (:status IS NULL OR r.status = :status)
               AND (:type IS NULL OR r.type = :type)
             ORDER BY r.code"""
    with engine.connect() as conn:
        rows = conn.execute(text(sql), {"status": status, "type": type}).mappings().all()
    return [dict(r) for r in rows]


@router.post("/{resource_id}/location")
def update_location(resource_id: int, body: LocationIn):
    """Called by a GPS device, the responder phone page, or the simulator."""
    with engine.begin() as conn:
        row = conn.execute(text("""
            UPDATE resources
            SET last_location = ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography,
                last_seen = now()
            WHERE id = :r RETURNING code, status"""),
            {"lon": body.lon, "lat": body.lat, "r": resource_id}).mappings().first()
        if not row:
            raise HTTPException(404, "Resource not found")
        # keep history at most once every 5 seconds per unit
        conn.execute(text("""
            INSERT INTO location_updates (resource_id, location)
            SELECT :r, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography
            WHERE NOT EXISTS (SELECT 1 FROM location_updates
                              WHERE resource_id = :r AND ts > now() - interval '5 seconds')"""),
            {"lon": body.lon, "lat": body.lat, "r": resource_id})
    publish("unit_moved", {"resource_id": resource_id, "code": row["code"],
                           "status": row["status"], "lat": body.lat, "lon": body.lon})
    return {"resource_id": resource_id, "lat": body.lat, "lon": body.lon}


@facilities_router.get("")
def list_facilities():
    sql = """SELECT id, name, type,
                    ST_Y(location::geometry) AS lat, ST_X(location::geometry) AS lon
             FROM facilities ORDER BY id"""
    with engine.connect() as conn:
        rows = conn.execute(text(sql)).mappings().all()
    return [dict(r) for r in rows]