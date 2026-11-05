from sqlalchemy import text
from load_facilities import engine

DDL = """
CREATE TABLE IF NOT EXISTS incidents (
    id SERIAL PRIMARY KEY,
    raw_text TEXT NOT NULL,
    category TEXT,
    severity TEXT,
    status TEXT NOT NULL DEFAULT 'new',
    location geography(Point, 4326) NOT NULL,
    idempotency_key TEXT UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS incidents_location_gix ON incidents USING GIST (location);
CREATE INDEX IF NOT EXISTS incidents_status_idx ON incidents (status);
"""

with engine.begin() as conn:
    conn.execute(text(DDL))
print("incidents table ready")