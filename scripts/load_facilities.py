import os
import httpx
from sqlalchemy import create_engine, text

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://crisis:crisis@localhost:5433/crisisgrid",
)
engine = create_engine(DATABASE_URL)

# Zone: circle around central Amritsar (lon, lat) with radius in meters
CENTER_LON, CENTER_LAT, RADIUS_M = 74.8765, 31.6200, 2500
# Download area: same box as the OSRM extract (south, west, north, east)
BBOX = (31.57, 74.78, 31.70, 74.97)

DDL = """
CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE IF NOT EXISTS zones (
    id SERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    geom geography(Polygon, 4326) NOT NULL
);

CREATE TABLE IF NOT EXISTS facilities (
    id SERIAL PRIMARY KEY,
    osm_type TEXT NOT NULL,
    osm_id BIGINT NOT NULL,
    name TEXT,
    type TEXT NOT NULL,              -- hospital | fire_station | police
    location geography(Point, 4326) NOT NULL,
    source TEXT NOT NULL DEFAULT 'openstreetmap',
    UNIQUE (osm_type, osm_id)
);

CREATE INDEX IF NOT EXISTS facilities_location_gix ON facilities USING GIST (location);
CREATE INDEX IF NOT EXISTS zones_geom_gix ON zones USING GIST (geom);
"""

OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
HEADERS = {
    "User-Agent": "CrisisGrid-student-project/0.1 (college major project, Amritsar)",
    "Accept": "application/json",
}

def fetch_overpass():
    s, w, n, e = BBOX
    query = f"""
    [out:json][timeout:90];
    (
      nwr["amenity"="hospital"]({s},{w},{n},{e});
      nwr["amenity"="fire_station"]({s},{w},{n},{e});
      nwr["amenity"="police"]({s},{w},{n},{e});
    );
    out center tags;
    """
    last_error = None
    for url in OVERPASS_URLS:
        try:
            r = httpx.post(url, data={"data": query}, headers=HEADERS, timeout=120)
            r.raise_for_status()
            print(f"Fetched from {url}")
            return r.json()["elements"]
        except httpx.HTTPError as err:
            print(f"{url} failed: {err}")
            last_error = err
    raise last_error

def main():
    with engine.begin() as conn:
        conn.execute(text(DDL))
        conn.execute(text("""
            INSERT INTO zones (name, geom)
            VALUES ('amritsar_core',
                    ST_Buffer(ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, :r))
            ON CONFLICT (name) DO NOTHING
        """), {"lon": CENTER_LON, "lat": CENTER_LAT, "r": RADIUS_M})

        inserted = 0
        for el in fetch_overpass():
            tags = el.get("tags", {})
            ftype = tags.get("amenity")
            if ftype not in ("hospital", "fire_station", "police"):
                continue
            lat = el.get("lat") or el.get("center", {}).get("lat")
            lon = el.get("lon") or el.get("center", {}).get("lon")
            if lat is None or lon is None:
                continue
            res = conn.execute(text("""
                INSERT INTO facilities (osm_type, osm_id, name, type, location)
                VALUES (:t, :i, :n, :ft, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography)
                ON CONFLICT (osm_type, osm_id) DO NOTHING
            """), {"t": el["type"], "i": el["id"], "n": tags.get("name"),
                   "ft": ftype, "lon": lon, "lat": lat})
            inserted += res.rowcount
        print(f"Inserted {inserted} new facilities")

if __name__ == "__main__":
    main()