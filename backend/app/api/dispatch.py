import json
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from app.db.session import engine
from app.realtime.events import publish

router = APIRouter(prefix="/dispatch", tags=["dispatch"])

# The state machine: each assignment can only move one step forward
NEXT = {"assigned": "en_route", "en_route": "on_scene",
        "on_scene": "returning", "returning": "completed"}


class AssignIn(BaseModel):
    incident_id: int
    resource_id: int
    assigned_by: str = "dispatcher"


def _event(conn, incident_id: int, event_type: str, payload: dict):
    conn.execute(text("""
        INSERT INTO incident_events (incident_id, event_type, payload)
        VALUES (:i, :t, CAST(:p AS jsonb))"""),
        {"i": incident_id, "t": event_type, "p": json.dumps(payload)})


@router.post("/assign", status_code=201)
def assign(body: AssignIn):
    with engine.begin() as conn:
        # Lock order is always incident first, then resource (prevents deadlocks)
        inc = conn.execute(text("SELECT id, status FROM incidents WHERE id = :i FOR UPDATE"),
                           {"i": body.incident_id}).mappings().first()
        if not inc:
            raise HTTPException(404, "Incident not found")
        if inc["status"] in ("resolved", "cancelled", "duplicate"):
            raise HTTPException(409, f"Incident is already {inc['status']}")

        res = conn.execute(text("SELECT id, code, status FROM resources WHERE id = :r FOR UPDATE"),
                           {"r": body.resource_id}).mappings().first()
        if not res:
            raise HTTPException(404, "Resource not found")
        if res["status"] != "available":
            raise HTTPException(409, f"{res['code']} is not available (status: {res['status']})")

        conn.execute(text("UPDATE resources SET status = 'assigned' WHERE id = :r"),
                     {"r": body.resource_id})
        aid = conn.execute(text("""
            INSERT INTO assignments (incident_id, resource_id, assigned_by)
            VALUES (:i, :r, :by) RETURNING id"""),
            {"i": body.incident_id, "r": body.resource_id, "by": body.assigned_by}).scalar()
        conn.execute(text("UPDATE incidents SET status = 'dispatched' WHERE id = :i AND status = 'new'"),
                     {"i": body.incident_id})
        _event(conn, body.incident_id, "assigned",
               {"assignment_id": aid, "resource": res["code"], "by": body.assigned_by})

    result = {"assignment_id": aid, "incident_id": body.incident_id,
              "resource_id": body.resource_id, "resource": res["code"], "status": "assigned"}
    publish("assignment_created", result)    # after commit
    return result


@router.post("/assignments/{assignment_id}/advance")
def advance(assignment_id: int, expected: str | None = None): 
    with engine.begin() as conn:
        a = conn.execute(text("SELECT * FROM assignments WHERE id = :a FOR UPDATE"),
                         {"a": assignment_id}).mappings().first()
        if not a:
            raise HTTPException(404, "Assignment not found")
        nxt = NEXT.get(a["status"])
        if not nxt:
            raise HTTPException(409, f"Assignment is {a['status']}; cannot advance")

        if nxt == "completed":
            # unit returns to its home station and becomes available again
            conn.execute(text("""
                UPDATE resources SET status = 'available', last_seen = now(),
                    last_location = (SELECT f.location FROM facilities f
                                     WHERE f.id = resources.home_facility_id)
                WHERE id = :r"""), {"r": a["resource_id"]})
        else:
            conn.execute(text("UPDATE resources SET status = :s, last_seen = now() WHERE id = :r"),
                         {"s": nxt, "r": a["resource_id"]})

        conn.execute(text("UPDATE assignments SET status = :s, updated_at = now() WHERE id = :a"),
                     {"s": nxt, "a": assignment_id})

        incident_status = None
        if nxt == "on_scene":
            conn.execute(text("UPDATE incidents SET status = 'on_scene' WHERE id = :i"),
                         {"i": a["incident_id"]})
            incident_status = "on_scene"
        if nxt == "completed":
            active = conn.execute(text("""
                SELECT count(*) FROM assignments
                WHERE incident_id = :i AND status NOT IN ('completed','cancelled')"""),
                {"i": a["incident_id"]}).scalar()
            if active == 0:
                conn.execute(text("UPDATE incidents SET status = 'resolved' WHERE id = :i"),
                             {"i": a["incident_id"]})
                incident_status = "resolved"
        _event(conn, a["incident_id"], f"assignment_{nxt}", {"assignment_id": assignment_id})

    result = {"assignment_id": assignment_id, "incident_id": a["incident_id"],
              "resource_id": a["resource_id"], "status": nxt,
              "incident_status": incident_status}
    publish("assignment_updated", result)    # after commit
    return result


@router.post("/assignments/{assignment_id}/cancel")
def cancel(assignment_id: int):
    with engine.begin() as conn:
        a = conn.execute(text("SELECT * FROM assignments WHERE id = :a FOR UPDATE"),
                         {"a": assignment_id}).mappings().first()
        if not a:
            raise HTTPException(404, "Assignment not found")
        if a["status"] not in ("assigned", "en_route"):
            raise HTTPException(409, f"Cannot cancel an assignment that is {a['status']}")
        conn.execute(text("UPDATE assignments SET status = 'cancelled', updated_at = now() WHERE id = :a"),
                     {"a": assignment_id})
        conn.execute(text("UPDATE resources SET status = 'available', last_seen = now() WHERE id = :r"),
                     {"r": a["resource_id"]})
        remaining = conn.execute(text("""
            SELECT count(*) FROM assignments
            WHERE incident_id = :i AND status NOT IN ('completed','cancelled')"""),
            {"i": a["incident_id"]}).scalar()
        if remaining == 0:
            conn.execute(text("UPDATE incidents SET status = 'new' WHERE id = :i AND status = 'dispatched'"),
                         {"i": a["incident_id"]})
        _event(conn, a["incident_id"], "assignment_cancelled", {"assignment_id": assignment_id})

    result = {"assignment_id": assignment_id, "incident_id": a["incident_id"],
              "resource_id": a["resource_id"], "status": "cancelled"}
    publish("assignment_updated", result)    # after commit
    return result


@router.get("/assignments")
def list_assignments(active_only: bool = True):
    sql = """SELECT a.id, a.incident_id, a.resource_id, r.code, a.status, a.assigned_at
             FROM assignments a JOIN resources r ON r.id = a.resource_id
             WHERE (:active = FALSE OR a.status NOT IN ('completed','cancelled'))
             ORDER BY a.id DESC"""
    with engine.connect() as conn:
        rows = conn.execute(text(sql), {"active": active_only}).mappings().all()
    return [dict(r) for r in rows]