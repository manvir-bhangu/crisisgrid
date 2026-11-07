from fastapi import APIRouter
from sqlalchemy import text
from app.db.session import engine

router = APIRouter(prefix="/resources", tags=["resources"])
facilities_router = APIRouter(prefix="/facilities", tags=["facilities"])


@router.get("")
def list_resources(status: str | None = None, type: str | None = None):
    sql = """SELECT id, code, type, status, capabilities, is_simulated,
                    ST_Y(last_location::geometry) AS lat, ST_X(last_location::geometry) AS lon
             FROM resources WHERE (:status IS NULL OR status = :status)
                              AND (:type IS NULL OR type = :type)
             ORDER BY code"""
    with engine.connect() as conn:
        rows = conn.execute(text(sql), {"status": status, "type": type}).mappings().all()
    return [dict(r) for r in rows]


@facilities_router.get("")
def list_facilities():
    sql = """SELECT id, name, type,
                    ST_Y(location::geometry) AS lat, ST_X(location::geometry) AS lon
             FROM facilities ORDER BY id"""
    with engine.connect() as conn:
        rows = conn.execute(text(sql)).mappings().all()
    return [dict(r) for r in rows]