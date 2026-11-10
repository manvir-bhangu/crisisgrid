from pathlib import Path
from urllib.parse import quote

import redis
from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from sqlalchemy import text

from app.api import ai_api, auth_api, dispatch, incidents, plan, resources
from app.core import security
from app.core.config import settings
from app.db.session import engine
from app.realtime import ws

security.check_config()

STATIC = Path(__file__).parent / "static"
STAFF = Depends(security.require(*security.STAFF_ROLES))
DISPATCH = Depends(security.require(*security.DISPATCH_ROLES))

app = FastAPI(title="CrisisGrid")
app.include_router(auth_api.router)
app.include_router(resources.router, dependencies=[STAFF])
app.include_router(resources.facilities_router, dependencies=[STAFF])
app.include_router(incidents.router)        # POST is public (citizen reports); reads are protected inside
app.include_router(ai_api.router, dependencies=[DISPATCH])
app.include_router(dispatch.router, dependencies=[DISPATCH])
app.include_router(plan.router, dependencies=[DISPATCH])
app.include_router(ws.router)               # checks the session itself

r = redis.from_url(settings.redis_url, socket_connect_timeout=0.5, socket_timeout=0.5)


def guarded_page(filename: str, roles: tuple[str, ...]):
    def handler(request: Request):
        user = security.get_user(request)
        if user is None:
            return RedirectResponse("/login?next=" + quote(request.url.path), status_code=303)
        if user["role"] not in roles:
            return HTMLResponse("<h3>Your account cannot open this page.</h3>"
                                "<a href='/login'>Sign in with another account</a>", status_code=403)
        return FileResponse(STATIC / filename)
    return handler


app.add_api_route("/dashboard", guarded_page("dashboard.html", security.DISPATCH_ROLES),
                  methods=["GET"], include_in_schema=False)
app.add_api_route("/planner", guarded_page("planner.html", security.DISPATCH_ROLES),
                  methods=["GET"], include_in_schema=False)
app.add_api_route("/responder", guarded_page("responder.html", security.STAFF_ROLES),
                  methods=["GET"], include_in_schema=False)


@app.get("/login", include_in_schema=False)
def login_page():
    return FileResponse(STATIC / "login.html")


@app.get("/report", include_in_schema=False)
def report_page():
    return FileResponse(STATIC / "citizen.html")


@app.get("/health")
def health():
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    try:
        redis_ok = bool(r.ping())
    except Exception:
        redis_ok = False
    return {"status": "ok", "redis": redis_ok}