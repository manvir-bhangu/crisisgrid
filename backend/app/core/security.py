import base64
import hashlib
import hmac
import json
import secrets
import time
from collections import defaultdict

from fastapi import HTTPException, Request
from starlette.requests import HTTPConnection

from app.core.config import settings

COOKIE = "cg_session"
DISPATCH_ROLES = ("dispatcher", "admin", "system")
STAFF_ROLES = ("responder", "dispatcher", "admin", "system")

_N, _R, _P = 2 ** 14, 8, 1
_DUMMY = f"scrypt${_N}${_R}${_P}$" + base64.b64encode(b"0" * 16).decode() + "$" + base64.b64encode(b"0" * 32).decode()
_hits: dict[str, list[float]] = defaultdict(list)


def check_config() -> None:
    """Fail closed: refuse to start with auth on but no signing key."""
    if settings.auth_enabled and len(settings.secret_key) < 32:
        raise RuntimeError(
            "AUTH_ENABLED is true but SECRET_KEY in .env is missing or shorter than 32 characters. "
            'Generate one with: python -c "import secrets; print(secrets.token_urlsafe(48))"')


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${_N}${_R}${_P}$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(dk).decode()


def verify_password(password: str, stored: str | None) -> bool:
    """Does the same work for unknown users, so timing does not reveal which usernames exist."""
    try:
        _, n, r, p, salt_b64, hash_b64 = (stored or _DUMMY).split("$")
        salt, expected = base64.b64decode(salt_b64), base64.b64decode(hash_b64)
        derived = hashlib.scrypt(password.encode(), salt=salt, n=int(n), r=int(r), p=int(p), dklen=len(expected))
    except Exception:
        return False
    return stored is not None and hmac.compare_digest(derived, expected)


def _sign(payload: bytes) -> str:
    return hmac.new(settings.secret_key.encode(), payload, hashlib.sha256).hexdigest()


def make_token(user_id: int, username: str, role: str) -> str:
    body = base64.urlsafe_b64encode(json.dumps({
        "id": user_id, "u": username, "r": role,
        "exp": int(time.time()) + settings.session_hours * 3600}).encode()).decode()
    return body + "." + _sign(body.encode())


def read_token(token: str | None) -> dict | None:
    if not token or "." not in token:
        return None
    body, sig = token.rsplit(".", 1)
    if not hmac.compare_digest(sig.encode(), _sign(body.encode()).encode()):
        return None
    try:
        data = json.loads(base64.urlsafe_b64decode(body.encode()))
        if data["exp"] < time.time():
            return None
        return {"id": data["id"], "username": data["u"], "role": data["r"]}
    except Exception:
        return None


def get_user(conn: HTTPConnection) -> dict | None:
    """Works for normal requests and WebSockets."""
    if not settings.auth_enabled:
        return {"id": 0, "username": "auth-disabled", "role": "admin"}
    key = conn.headers.get("x-api-key")
    if key and settings.service_api_key and hmac.compare_digest(key.encode(), settings.service_api_key.encode()):
        return {"id": 0, "username": "service", "role": "system"}
    return read_token(conn.cookies.get(COOKIE))


def require(*roles: str):
    def dep(request: Request) -> dict:
        user = get_user(request)
        if user is None:
            raise HTTPException(401, "Login required")
        if user["role"] not in roles:
            raise HTTPException(403, "Your role cannot do this")
        return user
    return dep


def public_report_limit(request: Request) -> None:
    """Rate-limits anonymous citizen reports. Logged-in staff and scripts are exempt."""
    if get_user(request) is not None:
        return
    ip = request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "unknown")
    now = time.time()
    recent = [t for t in _hits[ip] if now - t < 60]
    if len(recent) >= 10:
        raise HTTPException(429, "Too many reports from this address. Please wait a minute.")
    recent.append(now)
    _hits[ip] = recent
    if len(_hits) > 10000:
        _hits.clear()