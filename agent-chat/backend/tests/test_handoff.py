"""Ask AI: the server hands results to the genetics assistant with the handoff key."""

import json

import httpx
from fastapi.testclient import TestClient

from app import handoff, main

RESULTS = {"suspected_diagnosis": "invasive carcinoma", "image_url": "https://blog.example/media/a.webp", "findings": [{"label": "stroma", "count": 2}]}


def test_handoff_posts_with_the_key_and_returns_the_chat_address(monkeypatch):
    sent = []

    def respond(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(201, json={"results_id": "abc123"})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(handoff.httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(respond), **kw))
    monkeypatch.setenv("GENETICS_HANDOFF_KEY", "k3y")
    monkeypatch.setattr(handoff, "_key", None)
    with TestClient(main.app) as client:
        resp = client.post("/handoff", json=RESULTS)
    assert resp.json() == {"url": "https://genetics.sachin-kale.com/?results=abc123"}
    assert sent[0].url == "https://genapi.sachin-kale.com/api/v1/results"
    assert sent[0].headers["x-handoff-key"] == "k3y"
    assert json.loads(sent[0].content)["suspected_diagnosis"] == "invasive carcinoma"


def test_handoff_validates_and_reports_problems(monkeypatch):
    monkeypatch.delenv("GENETICS_HANDOFF_KEY", raising=False)
    monkeypatch.delenv("GENETICS_HANDOFF_SECRET", raising=False)
    monkeypatch.setattr(handoff, "_key", None)
    with TestClient(main.app) as client:
        assert client.post("/handoff", json={**RESULTS, "image_url": "javascript:alert(1)"}).status_code == 422
        unconfigured = client.post("/handoff", json=RESULTS)
    assert unconfigured.status_code == 502 and "isn't configured" in unconfigured.json()["detail"]
