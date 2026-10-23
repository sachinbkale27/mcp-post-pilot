"""The "Label images" flow, with a stub label server and agent (no OpenAI or MCP calls)."""

import json
from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient

from app import labeling, main, pathology
from app.specialists import AgentSpec

LABELS = AgentSpec(
    name="labels", title="Labeling agent", description="d", mcp_url="http://labels/mcp", prompt="p",
    images=True, attachment_base_url="https://blog.example",
)
IMAGE = {"url": "/media/abc.webp", "data_url": "data:image/webp;base64,AAAA", "name": "cats.webp"}
EXPORTS = {
    "coco": {"result": "coco-json"},
    "yolo": {"classes": ["cat"], "annotations": "0 0.25 0.4 0.2 0.4"},
    "qupath": {"type": "FeatureCollection", "features": []},
}
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
            "warm_up_segmentation": {"warming": "sam"},
            "upload_image_from_url": {"imageId": "img-1", "width": 200, "height": 100},
            "get_image": {"imageId": "img-1", "width": 200, "height": 100, "annotations": SAVED},
            "export_annotations": EXPORTS.get(arguments.get("format")),
            "detect_nuclei": {"summary": {"count": 584, "enlarged": 1}, "labels": {"nucleus": 299, "enlarged nucleus": 1}},
            "check_image_quality": {"verdict": "good", "warnings": [], "metrics": {"blur_score": 800.6}},
            "normalize_stain": {"original": "img-1", "normalized": {"imageId": "img-9"}},
        }
        if name == "get_image" and arguments["image_id"] == "img-9":
            return json.dumps({"imageId": "img-9", "filename": "abc-normalized.jpg", "url": "https://s3.example/n.jpg"}), False
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
    monkeypatch.setattr(pathology, "connect", fake_connect)
    monkeypatch.setattr(pathology, "call_mcp_tool", fake_call)
    return calls


async def test_uploads_annotates_and_returns_the_saved_result(label_server):
    events = [e async for e in labeling.run_labeling(IMAGE, "Circle every cat", ["cat", "dog"], "pets", 50, "medsam")]

    assert ("warm_up_segmentation", {"model": "medsam"}) in label_server
    upload = next(c for c in label_server if c[0] == "upload_image_from_url")
    assert upload == ("upload_image_from_url", {"url": "https://blog.example/media/abc.webp", "name": "cats.webp", "category": "pets"})
    task = next(t for name, t in label_server if name == "agent")
    assert "img-1 (200 x 100 pixels)" in task and "Circle every cat" in task and "cat, dog" in task
    assert "Possible interpretation" in task and "never the wording of the request" in task
    assert "lines every 50 pixels" in task and 'segment_objects call on image img-1\n(model "medsam")' in task

    types = [e["type"] for e in events]
    assert types[0] == "agent_start" and types[-1] == "agent_end" and not events[-1]["is_error"]
    assert {e["delegation"] for e in events if e["type"] in ("tool_call", "tool_result")} == {events[0]["id"]}
    result = next(e for e in events if e["type"] == "label_result")
    assert result["image_id"] == "img-1" and result["annotations"] == SAVED
    assert result["exports"] == {"coco": "coco-json", "yolo": EXPORTS["yolo"], "qupath": EXPORTS["qupath"]}
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


async def test_warm_up_is_best_effort(label_server, monkeypatch):
    assert await labeling.warm_up("sam") is True

    async def offline(mcp, name, arguments):
        raise ConnectionError("label server down")

    monkeypatch.setattr(labeling, "call_mcp_tool", offline)
    assert await labeling.warm_up("sam") is False


def test_label_request_accepts_long_medical_terms():
    import pytest
    from pydantic import ValidationError

    from app.main import LabelRequest

    image = {"url": "/media/a.png", "data_url": "data:image/png;base64,AAAA"}
    req = LabelRequest(image=image, instructions="Outline it", labels=["Suspected invasive ductal carcinoma (AI)x"])
    assert len(req.labels[0]) == 41
    with pytest.raises(ValidationError, match="at most 80"):
        LabelRequest(image=image, instructions="Outline it", labels=["x" * 81])


async def test_pathology_tools_upload_once_and_return_results(label_server):
    events = [e async for e in pathology.run_pathology(IMAGE, "nuclei")]
    assert [c[0] for c in label_server] == ["upload_image_from_url", "detect_nuclei", "get_image", "export_annotations", "export_annotations", "export_annotations"]
    result = next(e for e in events if e["type"] == "label_result")
    assert result["nuclei_summary"]["count"] == 584 and result["exports"]["qupath"]["type"] == "FeatureCollection"
    assert next(e for e in events if e["type"] == "label_image")["image_id"] == "img-1"

    label_server.clear()
    events = [e async for e in pathology.run_pathology(IMAGE, "quality", image_id="0" * 36)]
    assert [c[0] for c in label_server] == ["check_image_quality"]  # already uploaded: no second copy
    assert next(e for e in events if e["type"] == "quality_result")["verdict"] == "good"

    events = [e async for e in pathology.run_pathology(IMAGE, "normalize", image_id="0" * 36)]
    normalized = next(e for e in events if e["type"] == "normalized")
    assert normalized == {"type": "normalized", "image_id": "img-9", "name": "abc-normalized.jpg", "url": "https://s3.example/n.jpg"}


async def test_annotating_an_image_already_in_image_label_adds_to_it(label_server):
    events = [e async for e in labeling.run_labeling(IMAGE, "Outline the gland", [], "pets", None, "medsam", image_id="img-1")]
    assert "upload_image_from_url" not in [c[0] for c in label_server]
    task = next(t for name, t in label_server if name == "agent")
    assert "keep them, and only add new ones" in task
    assert next(e for e in events if e["type"] == "label_result")["image_id"] == "img-1"
