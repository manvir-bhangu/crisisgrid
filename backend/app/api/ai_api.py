import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from app.ai.analyzer import analyze
from app.ai.schemas import Category, Severity
from app.db.session import engine
from app.realtime.events import publish

router = APIRouter(prefix="/incidents", tags=["ai"])


class ConfirmIn(BaseModel):
    category: Category
    severity: Severity | None = None
    by: str = "dispatcher"


class DuplicateIn(BaseModel):
    duplicate_of: int


def _event(conn, incident_id: int, event_type: str, payload: dict):
    conn.execute(text("INSERT INTO incident_events (incident_id, event_type, payload) "
                      "VALUES (:i, :t, CAST(:p AS jsonb))"),
                 {"i": incident_id, "t": event_type, "p": json.dumps(payload)})


@router.post("/{incident_id}/analyze")
def rerun(incident_id: int):
    out = analyze(incident_id)
    if out is None:
        raise HTTPException(404, "Incident not found")
    return out


@router.get("/{incident_id}/assessment")
def latest(incident_id: int):
    with engine.connect() as conn:
        row = conn.execute(text("SELECT * FROM ai_assessments WHERE incident_id = :i "
                                "ORDER BY id DESC LIMIT 1"), {"i": incident_id}).mappings().first()
    if not row:
        raise HTTPException(404, "No assessment yet")
    return dict(row)


@router.post("/{incident_id}/confirm")
def confirm(incident_id: int, body: ConfirmIn):
    """The dispatcher accepts or overrides the AI suggestion. Only this sets verified fields."""
    with engine.begin() as conn:
        row = conn.execute(text("""
            UPDATE incidents SET category = :c, severity = COALESCE(:s, severity),
                                 category_confirmed = TRUE
            WHERE id = :i RETURNING id"""),
            {"c": body.category, "s": body.severity, "i": incident_id}).first()
        if not row:
            raise HTTPException(404, "Incident not found")
        _event(conn, incident_id, "category_confirmed",
               {"category": body.category, "severity": body.severity, "by": body.by})
    out = {"incident_id": incident_id, "category": body.category, "severity": body.severity}
    publish("incident_updated", out)
    return out


@router.post("/{incident_id}/mark-duplicate")
def mark_duplicate(incident_id: int, body: DuplicateIn):
    if body.duplicate_of == incident_id:
        raise HTTPException(422, "An incident cannot duplicate itself")
    with engine.begin() as conn:
        active = conn.execute(text("""
            SELECT count(*) FROM assignments
            WHERE incident_id = :i AND status NOT IN ('completed', 'cancelled')"""),
            {"i": incident_id}).scalar()
        if active:
            raise HTTPException(409, "Incident has active assignments; cancel them first")
        target = conn.execute(text("SELECT id FROM incidents WHERE id = :t"),
                              {"t": body.duplicate_of}).first()
        if not target:
            raise HTTPException(404, "Target incident not found")
        updated = conn.execute(text("UPDATE incidents SET status = 'duplicate', duplicate_of = :t "
                                    "WHERE id = :i RETURNING id"),
                               {"t": body.duplicate_of, "i": incident_id}).first()
        if not updated:
            raise HTTPException(404, "Incident not found")
        _event(conn, incident_id, "marked_duplicate", {"duplicate_of": body.duplicate_of})
    out = {"incident_id": incident_id, "status": "duplicate", "duplicate_of": body.duplicate_of}
    publish("incident_updated", out)
    return out
