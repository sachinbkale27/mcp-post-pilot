"""Owner sign-in for the admin pages (the usage analytics), the same way Image Label (labels.sachin-kale.com) does it.

ADMIN_USERS holds the accounts, in Image Label's admin-secret format:
    {"username": "sachin", "password": "..."}                              one user, an admin
    {"users": [{"username": "a", "password": "...", "admin": true}, ...]}  several; those marked admin are
                                                                           (none marked: the first one is)
SESSION_SECRET signs the session tokens (at least 32 characters, e.g. `openssl rand -hex 32`).
On AWS both are SecureString parameters under /mcp-post-pilot (see settings.py); locally, agent-chat/.env.
Without them, sign-in is off and the admin pages can't be used.

Token format (as Image Label's session.js): base64url(JSON {sub, admin, exp}) + "." + base64url(HMAC-SHA256).
It can't be forged or extended without the key, and expires after TOKEN_TTL_SECONDS.
"""

import base64
import hashlib
import hmac
import json
import os
import time

TOKEN_TTL_SECONDS = 12 * 60 * 60
MIN_SECRET = 32


class AdminUnavailable(Exception):
    """Sign-in isn't configured on this server."""


def _key() -> bytes:
    key = os.getenv("SESSION_SECRET", "")
    if len(key) < MIN_SECRET:
        raise AdminUnavailable(f"Admin sign-in is off: set SESSION_SECRET (at least {MIN_SECRET} characters) and ADMIN_USERS.")
    return key.encode()


def _users() -> list[dict]:
    """The accounts, each {"username", "password", "admin"} with admin resolved as Image Label does."""
    try:
        config = json.loads(os.getenv("ADMIN_USERS", "") or "null")
    except json.JSONDecodeError as exc:
        raise AdminUnavailable("Admin sign-in is off: ADMIN_USERS is not valid JSON.") from exc
    if isinstance(config, dict) and isinstance(config.get("users"), list):
        users = [u for u in config["users"] if isinstance(u, dict)]
        any_marked = any(u.get("admin") is True for u in users)
        return [{**u, "admin": u.get("admin") is True if any_marked else i == 0} for i, u in enumerate(users)]
    if isinstance(config, dict) and config.get("username"):
        return [{**config, "admin": True}]
    raise AdminUnavailable("Admin sign-in is off: set ADMIN_USERS and SESSION_SECRET.")


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(payload: str) -> bytes:
    return hmac.new(_key(), payload.encode(), hashlib.sha256).digest()


def create_token(username: str, admin: bool, ttl_seconds: int = TOKEN_TTL_SECONDS) -> str:
    payload = _b64(json.dumps({"sub": username, "admin": bool(admin), "exp": int(time.time()) + ttl_seconds}).encode())
    return f"{payload}.{_b64(_sign(payload))}"


def login(username: str, password: str) -> dict | None:
    """{"token", "username", "admin", "expires_in"} for a valid account, else None."""
    _key()  # off without a signing key, before looking at any password
    match = None
    for user in _users():  # check every account (constant-time compares), so timing doesn't tell which exists
        same_name = hmac.compare_digest(str(user.get("username", "")).encode(), username.encode())
        same_password = hmac.compare_digest(str(user.get("password", "")).encode(), password.encode())
        if same_name and same_password and match is None:
            match = user
    if match is None:
        return None
    return {
        "token": create_token(username, match["admin"]),
        "username": username,
        "admin": match["admin"],
        "expires_in": TOKEN_TTL_SECONDS,
    }


def get_session(token: str) -> dict | None:
    """The verified session ({"username", "admin"}), or None when the token is missing, malformed, tampered
    with or expired."""
    parts = token.strip().split(".")
    if len(parts) != 2 or not all(parts):
        return None
    payload, signature = parts
    try:
        if not hmac.compare_digest(_unb64(signature), _sign(payload)):
            return None
        claims = json.loads(_unb64(payload))
    except (ValueError, json.JSONDecodeError):
        return None
    if not isinstance(claims, dict) or not claims.get("sub") or not isinstance(claims.get("exp"), int):
        return None
    if claims["exp"] < time.time():
        return None
    return {"username": claims["sub"], "admin": claims.get("admin") is True}
