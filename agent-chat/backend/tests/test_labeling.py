"""The "Label images" flow, with a stub label server and agent (no OpenAI or MCP calls)."""

import json
from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient

from app import labeling, main
from app.specialists import AgentSpec

LABELS = AgentSpec(
    name="labels", title="Labeling agent", description="d", mcp_url="http://labels/mcp", prompt="p",
    images=True, attachment_base_url="https://blog.example",
)
IMAGE = {"url": "/media/abc.webp", "data_url": "data:image/webp;base64,AAAA", "name": "cats.webp"}
SAVED = [{"id": "a1", "type": "circle", "label": "cat", "x": 50, "y": 40, "radius": 20, "confidence": "low"}]


@pytest.fixture
def label_server(monkeypatch):
    calls = []

    @asynccontextmanager
    async def fake_connect(spec):
        yield object()

    async def fake_call(mcp, name, arguments):
        calls.append((name, arguments))
        results = {
            "upload_image_from_url": {"imageId": "img-1", "width": 200, "height": 100},
            "get_image": {"imageId": "img-1", "width": 200, "height": 100, "annotations": SAVED},
            "export_annotations": {"result": "coco-json"} if arguments.get("format") == "coco" else {"classes": ["cat"], "annotations": "0 0.25 0.4 0.2 0.4"},
        }
        return json.dumps(results[name]), False

    async def fake_specialist(spec, *, task, images, delegation_id, emit, **_):
        calls.append(("agent", task))
        assert images == [IMAGE]
        emit({"type": "tool_call", "id": "t1", "name": "add_annotations", "input": {}, "agent": "labels", "delegation": delegation_id})
        return "Labeled one cat (approximate)."

    monkeypatch.setattr(labeling, "load_agents", lambda: (LABELS,))
    monkeypatch.setattr(labeling, "connect", fake_connect)
    monkeypatch.setattr(labeling, "call_mcp_tool", fake_call)
    monkeypatch.setattr(labeling, "run_specialist", fake_specialist)
    return calls


async def test_uploads_annotates_and_returns_the_saved_result(label_server):
    events = [e async for e in labeling.run_labeling(IMAGE, "Circle every cat", ["cat", "dog"], "pets")]

    upload = label_server[0]
    assert upload == ("upload_image_from_url", {"url": "https://blog.example/media/abc.webp", "name": "cats.webp", "category": "pets"})
    task = next(t for name, t in label_server if name == "agent")
    assert "img-1 (200 x 100 pixels)" in task and "Circle every cat" in task and "cat, dog" in task

    types = [e["type"] for e in events]
    assert types[0] == "agent_start" and types[-1] == "agent_end" and not events[-1]["is_error"]
    assert {e["delegation"] for e in events if e["type"] in ("tool_call", "tool_result")} == {events[0]["id"]}
    result = next(e for e in events if e["type"] == "label_result")
    assert result["image_id"] == "img-1" and result["annotations"] == SAVED
    assert result["exports"] == {"coco": "coco-json", "yolo": {"classes": ["cat"], "annotations": "0 0.25 0.4 0.2 0.4"}}
    assert result["report"] == "Labeled one cat (approximate)."


def test_endpoint_reports_a_missing_labeling_agent(monkeypatch):
    monkeypatch.setattr(labeling, "load_agents", lambda: ())
    with TestClient(main.app) as client:
        body = client.post("/label", json={"image": IMAGE, "instructions": "Circle every cat"}).text
    assert "event: error" in body and "isn't configured" in body and "event: done" in body


def test_endpoint_validates_the_request():
    with TestClient(main.app) as client:
        assert client.post("/label", json={"image": {**IMAGE, "url": "https://evil.example/x.png"}, "instructions": "x y z"}).status_code == 422
        assert client.post("/label", json={"image": IMAGE, "instructions": "go", "labels": ["x" * 41]}).status_code == 422
