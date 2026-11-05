import csv
import os
from sqlalchemy import text
from load_facilities import engine, DDL

CSV_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "seed", "manual_facilities.csv")
VALID = {"hospital", "fire_station", "police"}

def main():
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    with engine.begin() as conn:
        conn.execute(text(DDL))
        # reload manual rows from scratch so re-running never duplicates
        conn.execute(text("DELETE FROM facilities WHERE osm_type = 'manual'"))
        for i, r in enumerate(rows, start=1):
            if r["type"] not in VALID:
                raise ValueError(f"Bad type in row {i}: {r['type']}")
            conn.execute(text("""
                INSERT INTO facilities (osm_type, osm_id, name, type, location, source)
                VALUES ('manual', :i, :n, :t,
                        ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography,
                        'manual_google_maps')
            """), {"i": i, "n": r["name"], "t": r["type"],
                   "lon": float(r["lon"]), "lat": float(r["lat"])})
    print(f"Loaded {len(rows)} manual facilities")

if __name__ == "__main__":
    main()