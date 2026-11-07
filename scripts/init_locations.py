from sqlalchemy import text
from load_facilities import engine

DDL = """
CREATE TABLE IF NOT EXISTS location_updates (
    id BIGSERIAL PRIMARY KEY,
    resource_id INT NOT NULL REFERENCES resources(id),
    location geography(Point, 4326) NOT NULL,
    ts TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS location_updates_resource_ts ON location_updates (resource_id, ts DESC);
CREATE INDEX IF NOT EXISTS location_updates_gix ON location_updates USING GIST (location);
"""

with engine.begin() as conn:
    conn.execute(text(DDL))
print("location_updates table ready")