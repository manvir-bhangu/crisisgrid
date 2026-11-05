import redis
from fastapi import FastAPI
from sqlalchemy import text

from app.api import dispatch, incidents, resources

from app.core.config import settings
from app.db.session import engine

app = FastAPI(title="CrisisGrid")
app.include_router(resources.router)
app.include_router(incidents.router)
...
app.include_router(resources.router)
app.include_router(incidents.router)
app.include_router(dispatch.router)
r = redis.from_url(settings.redis_url)


@app.get("/health")
def health():
    with engine.connect() as conn:
        postgis = conn.execute(text("SELECT PostGIS_Version()")).scalar()
    return {"status": "ok", "postgis": postgis, "redis": r.ping()}