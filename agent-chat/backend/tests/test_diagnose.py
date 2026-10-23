"""The Diagnose button's endpoint, with a scripted model (no OpenAI calls)."""

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessageChunk

from app import diagnose, main
from app.diagnose import Region, Regions

IMAGE = {"url": "/media/abc.webp", "data_url": "data:image/webp;base64,AAAA", "name": "slide.webp"}


class FakeModel:
    def __init__(self):
        self.messages = None

    async def astream(self, messages):
        self.messages = messages
        for text in ["## What the image shows\n", "H&E histology", ""]:
            yield AIMessageChunk(content=text)


def test_streams_the_interpretation_with_the_image_and_context(monkeypatch):
    model = FakeModel()
    monkeypatch.setattr(diagnose, "_model", lambda **kwargs: model)
    seen = []

    async def fake_regions(text, image_data_url):
        seen.append(text)
        assert image_data_url == IMAGE["data_url"]
        return Regions(medical=True, regions=[Region(label="melanophage", description="cells packed with brown pigment", significance="melanin in a melanocytic lesion")])

    monkeypatch.setattr(diagnose, "extract_regions", fake_regions)
    with TestClient(main.app) as client:
        body = client.post("/diagnose", json={"image": IMAGE, "context": "skin biopsy, back"}).text
    assert body.count("event: token") == 2 and "H&E histology" in body and body.rstrip().endswith("data: {}")
    assert seen == ["## What the image shows\nH&E histology"]  # the regions come from the whole interpretation
    assert "event: diagnosis_regions" in body and '"medical":true' in body.replace(" ", "") and "melanophage" in body
    system, human = model.messages
    assert "not a medical diagnosis" in system.content
    text, image = human.content
    assert "skin biopsy, back" in text["text"]
    assert image["image_url"] == {"url": IMAGE["data_url"], "detail": "high"}


def test_errors_end_the_stream_cleanly(monkeypatch):
    class Broken:
        async def astream(self, messages):
            raise RuntimeError("model down")
            yield

    monkeypatch.setattr(diagnose, "_model", lambda **kwargs: Broken())
    with TestClient(main.app) as client:
        body = client.post("/diagnose", json={"image": IMAGE}).text
    assert "event: error" in body and "model down" in body and "event: done" in body
