from pathlib import Path

import redis
from fastapi import FastAPI
from fastapi.responses import FileResponse
from sqlalchemy import text

from app.api import ai_api, dispatch, incidents, plan, resources
from app.core.config import settings
from app.db.session import engine
from app.realtime import ws

STATIC = Path(__file__).parent / "static"

app = FastAPI(title="CrisisGrid")
app.include_router(resources.router)
app.include_router(resources.facilities_router)
app.include_router(incidents.router)
app.include_router(ai_api.router)
app.include_router(dispatch.router)
app.include_router(plan.router)
app.include_router(ws.router)

r = redis.from_url(settings.redis_url)


@app.get("/dashboard", include_in_schema=False)
def dashboard():
    return FileResponse(STATIC / "dashboard.html")


@app.get("/planner", include_in_schema=False)
def planner_page():
    return FileResponse(STATIC / "planner.html")


@app.get("/report", include_in_schema=False)
def report_page():
    return FileResponse(STATIC / "citizen.html")


@app.get("/responder", include_in_schema=False)
def responder_page():
    return FileResponse(STATIC / "responder.html")


@app.get("/health")
def health():
    with engine.connect() as conn:
        postgis = conn.execute(text("SELECT PostGIS_Version()")).scalar()
    return {"status": "ok", "postgis": postgis, "redis": r.ping()}