import os
import osmium
from sqlalchemy import text

# Reuses the DB engine, SQL and zone settings from the first script
from load_facilities import engine, DDL, CENTER_LON, CENTER_LAT, RADIUS_M

PBF = os.path.join(os.path.dirname(__file__), "..", "data", "osrm", "amritsar.osm.pbf")
WANTED = {"hospital", "fire_station", "police"}


class Handler(osmium.SimpleHandler):
    def __init__(self):
        super().__init__()
        self.rows = []

    def node(self, n):
        t = n.tags.get("amenity")
        if t in WANTED and n.location.valid():
            self.rows.append(("node", n.id, n.tags.get("name"), t,
                              n.location.lon, n.location.lat))

    def area(self, a):
        t = a.tags.get("amenity")
        if t not in WANTED:
            return
        lons, lats = [], []
        for ring in a.outer_rings():
            for nd in ring:
                lons.append(nd.lon)
                lats.append(nd.lat)
        if not lons:
            return
        kind = "way" if a.from_way() else "relation"
        self.rows.append((kind, a.orig_id(), a.tags.get("name"), t,
                          sum(lons) / len(lons), sum(lats) / len(lats)))


def main():
    h = Handler()
    h.apply_file(PBF, locations=True)
    print(f"Found {len(h.rows)} facilities in the map file")

    with engine.begin() as conn:
        conn.execute(text(DDL))
        conn.execute(text("""
            INSERT INTO zones (name, geom)
            VALUES ('amritsar_core',
                    ST_Buffer(ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, :r))
            ON CONFLICT (name) DO NOTHING
        """), {"lon": CENTER_LON, "lat": CENTER_LAT, "r": RADIUS_M})

        inserted = 0
        for kind, osm_id, name, ftype, lon, lat in h.rows:
            res = conn.execute(text("""
                INSERT INTO facilities (osm_type, osm_id, name, type, location)
                VALUES (:t, :i, :n, :ft, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography)
                ON CONFLICT (osm_type, osm_id) DO NOTHING
            """), {"t": kind, "i": osm_id, "n": name, "ft": ftype,
                   "lon": lon, "lat": lat})
            inserted += res.rowcount
        print(f"Inserted {inserted} new facilities")


if __name__ == "__main__":
    main()