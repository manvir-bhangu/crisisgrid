from fastapi import FastAPI
import os, redis
from sqlalchemy import create_engine, text

app = FastAPI(title="CrisisGrid")

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg2://crisis:crisis@localhost:5433/crisisgrid")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6380/0")

engine = create_engine(DATABASE_URL)
r = redis.from_url(REDIS_URL)

@app.get("/health")
def health():
    with engine.connect() as conn:
        postgis = conn.execute(text("SELECT PostGIS_Version()")).scalar()
    return {"status": "ok", "postgis": postgis, "redis": r.ping()}