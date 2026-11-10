"""Create or update a staff account.
Usage: python scripts/create_user.py <username> <dispatcher|responder|admin>"""
import getpass
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))

from sqlalchemy import text  # noqa: E402

from app.core.security import hash_password  # noqa: E402
from app.db.session import engine  # noqa: E402

ROLES = ("dispatcher", "responder", "admin")

if len(sys.argv) != 3 or sys.argv[2] not in ROLES:
    sys.exit("usage: python scripts/create_user.py <username> <dispatcher|responder|admin>")
name = sys.argv[1].strip().lower()
pw = getpass.getpass("Password (at least 10 characters, typing is hidden): ")
if len(pw) < 10:
    sys.exit("Password too short.")
if pw != getpass.getpass("Repeat password: "):
    sys.exit("Passwords do not match.")

with engine.begin() as conn:
    conn.execute(text("""INSERT INTO users (username, password_hash, role) VALUES (:u, :h, :r)
                         ON CONFLICT (username) DO UPDATE SET password_hash = :h, role = :r, active = TRUE"""),
                 {"u": name, "h": hash_password(pw), "r": sys.argv[2]})
print(f"Saved {name} ({sys.argv[2]})")