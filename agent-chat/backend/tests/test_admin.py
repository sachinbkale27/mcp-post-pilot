"""Owner sign-in for the usage analytics, mirroring Image Label's admin login and sessions."""

import json
import time

import pytest
from fastapi.testclient import TestClient

from app import admin, analytics, main
from app.analytics import MemoryAnalyticsStore

KEY = "k" * 40
ONE_USER = {"username": "sachin", "password": "correct horse"}
SEVERAL = {"users": [{"username": "viewer", "password": "pw1"}, {"username": "sachin", "password": "pw2", "admin": True}]}


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", KEY)
    monkeypatch.setenv("ADMIN_USERS", json.dumps(ONE_USER))
    monkeypatch.setattr(main.time, "sleep", lambda _: None)  # the failed-login pause


@pytest.fixture
def client(monkeypatch):
    store = MemoryAnalyticsStore()
    monkeypatch.setattr(analytics, "get_analytics_store", lambda: store)
    with TestClient(main.app, headers={"user-agent": "Mozilla/5.0 Chrome/131.0"}) as client:
        yield client


# ------------------------------------------------------------ accounts and tokens


def test_the_single_user_format_is_an_admin(configured):
    session = admin.login("sachin", "correct horse")
    assert session["admin"] is True and session["expires_in"] == 12 * 3600
    assert admin.get_session(session["token"]) == {"username": "sachin", "admin": True}


def test_wrong_credentials_get_no_session(configured):
    assert admin.login("sachin", "wrong") is None and admin.login("someone", "correct horse") is None


@pytest.mark.parametrize("config, admins", [
    (SEVERAL, {"viewer": False, "sachin": True}),  # marked admin
    ({"users": [{"username": "viewer", "password": "pw1"}, {"username": "sachin", "password": "pw2"}]},
     {"viewer": True, "sachin": False}),  # none marked: the first one is
    ([{"username": "viewer", "password": "pw1"}, {"username": "sachin", "password": "pw2", "admin": True}],
     {"viewer": False, "sachin": True}),  # the users list without the {"users": ...} wrapper
    ([{"username": "viewer", "password": "pw1"}, {"username": "sachin", "password": "pw2"}],
     {"viewer": True, "sachin": False}),
])
def test_several_users_follow_image_labels_admin_rule(monkeypatch, configured, config, admins):
    monkeypatch.setenv("ADMIN_USERS", json.dumps(config))
    for user in config["users"] if isinstance(config, dict) else config:
        assert admin.login(user["username"], user["password"])["admin"] is admins[user["username"]]


@pytest.mark.parametrize("env", [
    {"SESSION_SECRET": "", "ADMIN_USERS": json.dumps(ONE_USER)},
    {"SESSION_SECRET": "too-short", "ADMIN_USERS": json.dumps(ONE_USER)},
    {"SESSION_SECRET": KEY, "ADMIN_USERS": ""},
    {"SESSION_SECRET": KEY, "ADMIN_USERS": "{not json"},
    {"SESSION_SECRET": KEY, "ADMIN_USERS": '"just a string"'},
])
def test_sign_in_is_off_until_configured(monkeypatch, env):
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    with pytest.raises(admin.AdminUnavailable):
        admin.login("sachin", "correct horse")


def test_a_tampered_or_expired_token_is_rejected(configured, monkeypatch):
    token = admin.create_token("viewer", admin=False)
    payload, signature = token.split(".")
    forged = admin._b64(json.dumps({"sub": "viewer", "admin": True, "exp": int(time.time()) + 3600}).encode())
    assert admin.get_session(f"{forged}.{signature}") is None  # can't promote yourself
    assert admin.get_session(admin.create_token("sachin", True, ttl_seconds=-1)) is None
    assert admin.get_session("garbage") is None and admin.get_session("a.b.c") is None and admin.get_session("") is None
    monkeypatch.setenv("SESSION_SECRET", "z" * 40)
    assert admin.get_session(token) is None  # signed with another key


# ------------------------------------------------------------------- the API


def test_login_endpoint(client, configured):
    res = client.post("/admin/login", json=ONE_USER)
    assert res.status_code == 200 and res.json()["admin"] is True and res.headers["cache-control"] == "no-store"
    assert client.post("/admin/login", json={**ONE_USER, "password": "nope"}).status_code == 401


def test_login_endpoint_is_off_until_configured(client, monkeypatch):
    monkeypatch.delenv("SESSION_SECRET", raising=False)
    assert client.post("/admin/login", json=ONE_USER).status_code == 503


def test_only_a_signed_in_admin_can_read_the_usage(client, configured, monkeypatch):
    client.post("/events", json={"name": "view", "props": {"view": "chat"}})
    assert client.get("/admin/usage").status_code == 401
    assert client.get("/admin/usage", headers={"x-admin-session": "forged.token"}).status_code == 401

    monkeypatch.setenv("ADMIN_USERS", json.dumps(SEVERAL))
    viewer = client.post("/admin/login", json={"username": "viewer", "password": "pw1"}).json()["token"]
    assert client.get("/admin/usage", headers={"x-admin-session": viewer}).status_code == 403

    owner = client.post("/admin/login", json={"username": "sachin", "password": "pw2"}).json()["token"]
    for headers in ({"x-admin-session": owner}, {"authorization": f"Bearer {owner}"}):
        res = client.get("/admin/usage?days=7", headers=headers)
        assert res.status_code == 200 and res.headers["cache-control"] == "no-store"
        assert len(res.json()["daily"]) == 7 and res.json()["totals"]["views"] == 1
    assert client.get("/admin/usage?days=500", headers={"x-admin-session": owner}).status_code == 422
