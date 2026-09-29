"""Team logins and permissions. Passwords are stored as salted scrypt hashes only."""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets

from . import settings, store

ROLE_LABELS = {
    "founder": "Founder (decides, admin)",
    "hiring_manager": "Hiring manager",
    "interviewer": "Interviewer",
    "coordinator": "Recruiting coordinator",
    "viewer": "Viewer (read only)",
}
PERMISSIONS = {
    "founder": {"view", "decide", "upload", "comment", "review", "scorecard", "schedule", "calibrate", "admin"},
    "hiring_manager": {"view", "upload", "comment", "review", "scorecard", "schedule", "calibrate"},
    "interviewer": {"view", "comment", "review", "scorecard"},
    "coordinator": {"view", "upload", "comment", "schedule"},
    "viewer": {"view"},
}
DEMO_USERS = [
    ("arjun", "Arjun Mehta", "founder", "arjun@example.com"),
    ("priya", "Priya Nair", "hiring_manager", "priya@example.com"),
    ("rahul", "Rahul Verma", "interviewer", "rahul@example.com"),
    ("meera", "Meera Iyer", "coordinator", "meera@example.com"),
]


def hash_password(pw: str) -> str:
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt${salt.hex()}${h.hex()}"


def check_password(pw: str, stored: str | None) -> bool:
    if not stored or not stored.startswith("scrypt$"):
        return False
    _, salt, h = stored.split("$")
    got = hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1)
    return hmac.compare_digest(got.hex(), h)


def validate_password(pw: str) -> str | None:
    if len(pw) < 10:
        return "use at least 10 characters"
    if not (re.search(r"[A-Za-z]", pw) and re.search(r"\d", pw)):
        return "use letters and at least one number"
    return None


def create_user(username: str, display_name: str, role: str, password: str | None, email: str = "",
                by: str = "system") -> None:
    username = username.strip().lower()
    if not re.fullmatch(r"[a-z0-9._-]{2,32}", username):
        raise ValueError("username: 2-32 lower-case letters, digits, dot, dash or underscore")
    if role not in PERMISSIONS:
        raise ValueError(f"unknown role {role}")
    pw_hash = None
    if password is not None:
        problem = validate_password(password)
        if problem:
            raise ValueError(f"password: {problem}")
        pw_hash = hash_password(password)
    with store.connect() as c:
        if c.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
            raise ValueError("that username is taken")
        c.execute("INSERT INTO users (username, display_name, role, pw_hash, email, active, created_at) "
                  "VALUES (?, ?, ?, ?, ?, 1, ?)", (username, display_name.strip(), role, pw_hash, email.strip(),
                                                   store.now()))
        store.audit("user_created", _conn=c, username=username, role=role, by=by)


def set_password(username: str, password: str, by: str) -> None:
    problem = validate_password(password)
    if problem:
        raise ValueError(f"password: {problem}")
    with store.connect() as c:
        c.execute("UPDATE users SET pw_hash = ? WHERE username = ?", (hash_password(password), username))
        store.audit("password_set", _conn=c, username=username, by=by)


def update_user(username: str, *, role: str | None = None, active: bool | None = None, by: str) -> None:
    with store.connect() as c:
        if role:
            if role not in PERMISSIONS:
                raise ValueError(f"unknown role {role}")
            c.execute("UPDATE users SET role = ? WHERE username = ?", (role, username))
        if active is not None:
            c.execute("UPDATE users SET active = ? WHERE username = ?", (1 if active else 0, username))
        store.audit("user_updated", _conn=c, username=username, role=role, active=active, by=by)


def users(active_only: bool = False) -> list[dict]:
    with store.connect() as c:
        sql = "SELECT username, display_name, role, email, active, created_at FROM users"
        if active_only:
            sql += " WHERE active = 1"
        return store.rows(c, sql + " ORDER BY display_name")


def get_user(username: str) -> dict | None:
    with store.connect() as c:
        return store.one(c, "SELECT username, display_name, role, email, active FROM users WHERE username = ?",
                         (username,))


def authenticate(username: str, password: str) -> dict | None:
    with store.connect() as c:
        u = store.one(c, "SELECT * FROM users WHERE username = ? AND active = 1", (username.strip().lower(),))
    if u and check_password(password, u["pw_hash"]):
        store.audit("login", username=u["username"])
        return {k: u[k] for k in ("username", "display_name", "role", "email")}
    store.audit("login_failed", username=username.strip().lower()[:32])
    return None


def has_users() -> bool:
    with store.connect() as c:
        return bool(c.execute("SELECT 1 FROM users LIMIT 1").fetchone())


def can(user: dict | None, perm: str) -> bool:
    if not user:
        return False
    if perm == "decide":
        return user["role"] in settings.get("decision_roles")
    return perm in PERMISSIONS.get(user["role"], set())


def seed_demo_users() -> None:
    for username, name, role, email in DEMO_USERS:
        try:
            create_user(username, name, role, None, email)
        except ValueError:
            pass
