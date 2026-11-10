import time
from collections import defaultdict

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.core import security
from app.core.config import settings
from app.db.session import engine

router = APIRouter(prefix="/auth", tags=["auth"])

_fails: dict[str, list[float]] = defaultdict(list)
MAX_FAILS, WINDOW_S = 5, 300


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


def _throttled(name: str) -> bool:
    now = time.time()
    _fails[name] = [t for t in _fails[name] if now - t < WINDOW_S]
    return len(_fails[name]) >= MAX_FAILS


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response):
    name = body.username.strip().lower()
    if _throttled(name):
        raise HTTPException(429, "Too many failed attempts. Wait a few minutes and try again.")
    with engine.connect() as conn:
        row = conn.execute(text("SELECT id, username, password_hash, role, active FROM users "
                                "WHERE username = :u"), {"u": name}).mappings().first()
    ok = security.verify_password(body.password, row["password_hash"] if row else None)
    if not (ok and row and row["active"]):
        if len(_fails) > 5000:
            _fails.clear()
        _fails[name].append(time.time())
        raise HTTPException(401, "Wrong username or password")
    _fails.pop(name, None)
    secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    response.set_cookie(security.COOKIE, security.make_token(row["id"], row["username"], row["role"]),
                        max_age=settings.session_hours * 3600, httponly=True, samesite="lax",
                        secure=secure, path="/")
    return {"username": row["username"], "role": row["role"]}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(security.COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(request: Request):
    user = security.get_user(request)
    if user is None:
        raise HTTPException(401, "Not logged in")
    return user