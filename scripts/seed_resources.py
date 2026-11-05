import random
from sqlalchemy import text
from load_facilities import engine

random.seed(42)  # fixed seed so the fleet is identical on every run

DDL = """
CREATE TABLE IF NOT EXISTS resources (
    id SERIAL PRIMARY KEY,
    code TEXT UNIQUE NOT NULL,                 -- AMB-01, FIRE-01, RSC-01
    type TEXT NOT NULL CHECK (type IN ('ambulance','fire_truck','rescue')),
    capabilities TEXT[] NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'available' CHECK (status IN
        ('available','assigned','en_route','on_scene','returning','out_of_service')),
    home_facility_id INT REFERENCES facilities(id),
    last_location geography(Point, 4326),
    last_seen TIMESTAMPTZ DEFAULT now(),
    is_simulated BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE INDEX IF NOT EXISTS resources_location_gix ON resources USING GIST (last_location);
CREATE INDEX IF NOT EXISTS resources_status_idx ON resources (status);
"""

CAPS = {
    "ambulance": ["medical", "transport"],
    "fire_truck": ["fire", "rescue_basic"],
    "rescue": ["rescue", "traffic_control"],
}

def main():
    with engine.begin() as conn:
        conn.execute(text(DDL))
        conn.execute(text("DELETE FROM resources"))  # safe now: nothing references it yet

        in_zone = lambda t: conn.execute(text("""
            SELECT f.id FROM facilities f JOIN zones z ON ST_Covers(z.geom, f.location)
            WHERE z.name='amritsar_core' AND f.type=:t AND f.name IS NOT NULL
            ORDER BY f.id"""), {"t": t}).scalars().all()
        anywhere = lambda t: conn.execute(text(
            "SELECT id FROM facilities WHERE type=:t ORDER BY id"), {"t": t}).scalars().all()

        hospitals = in_zone("hospital")
        ambulance_bases = random.sample(hospitals, min(12, len(hospitals)))
        fire_bases = [f for f in anywhere("fire_station") for _ in range(2)]
        police_bases = anywhere("police")

        plan = ([("ambulance", "AMB", b) for b in ambulance_bases]
                + [("fire_truck", "FIRE", b) for b in fire_bases]
                + [("rescue", "RSC", b) for b in police_bases])

        counters = {}
        for rtype, prefix, base in plan:
            counters[prefix] = counters.get(prefix, 0) + 1
            conn.execute(text("""
                INSERT INTO resources (code, type, capabilities, home_facility_id, last_location)
                SELECT :code, :type, :caps, f.id, f.location FROM facilities f WHERE f.id = :base
            """), {"code": f"{prefix}-{counters[prefix]:02d}", "type": rtype,
                   "caps": CAPS[rtype], "base": base})
        print("Created:", counters)

if __name__ == "__main__":
    main()