from sqlalchemy import text
from load_facilities import engine

DDL = """
CREATE TABLE IF NOT EXISTS assignments (
    id SERIAL PRIMARY KEY,
    incident_id INT NOT NULL REFERENCES incidents(id),
    resource_id INT NOT NULL REFERENCES resources(id),
    status TEXT NOT NULL DEFAULT 'assigned' CHECK (status IN
        ('assigned','en_route','on_scene','returning','completed','cancelled')),
    assigned_by TEXT NOT NULL DEFAULT 'dispatcher',
    assigned_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Database-level guarantee: a unit can have only ONE active assignment
CREATE UNIQUE INDEX IF NOT EXISTS one_active_assignment_per_resource
    ON assignments (resource_id)
    WHERE status NOT IN ('completed', 'cancelled');

CREATE INDEX IF NOT EXISTS assignments_incident_idx ON assignments (incident_id);

CREATE TABLE IF NOT EXISTS incident_events (
    id SERIAL PRIMARY KEY,
    incident_id INT NOT NULL REFERENCES incidents(id),
    event_type TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}',
    ts TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS incident_events_incident_idx ON incident_events (incident_id, ts);
"""

with engine.begin() as conn:
    conn.execute(text(DDL))
print("assignments and incident_events tables ready")