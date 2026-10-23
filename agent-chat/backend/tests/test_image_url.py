"""Downloading images by web address for the UI (no network: fetch is stubbed)."""

import io

import httpx
import pytest
from PIL import Image
from fastapi.testclient import TestClient

from app import image_url, main
from app.image_url import MAX_IMAGE_BYTES, file_name, image_type
from app.local_mcp.research import FetchError

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 20


def stub_fetch(monkeypatch, *, status=200, body=PNG, final="https://img.example/photos/My%20Cat.jpeg?w=800", error=None):
    calls = []

    async def fake_fetch(url, **kwargs):
        calls.append((url, kwargs))
        if error:
            raise error
        return httpx.Response(status, headers={"content-type": "text/html"}), final, body

    monkeypatch.setattr(image_url, "fetch", fake_fetch)
    return calls


def post(url):
    with TestClient(main.app) as client:
        return client.post("/fetch-image", json={"url": url})


def test_returns_the_image_with_a_safe_name(monkeypatch):
    calls = stub_fetch(monkeypatch)
    res = post("https://img.example/photos/My%20Cat.jpeg?w=800")
    assert res.status_code == 200 and res.content == PNG
    assert res.headers["content-type"] == "image/png"
    assert res.headers["x-image-name"] == "My-Cat.png"  # named by its real type
    assert calls[0][1]["max_bytes"] == MAX_IMAGE_BYTES


@pytest.mark.parametrize(
    "kwargs, status, message",
    [
        ({"body": b"<html>gallery page</html>"}, 415, "isn't an image this tool can read"),
        ({"status": 404}, 502, "Check that it is complete"),
        ({"status": 403}, 502, "HTTP 403"),
        ({"body": PNG + b"\x00" * MAX_IMAGE_BYTES}, 413, "larger than 15 MB"),
        ({"error": FetchError("localhost resolves to a non-public address")}, 400, "non-public"),
        ({"error": httpx.ConnectTimeout("slow")}, 502, "ConnectTimeout"),
    ],
)
def test_refusals(monkeypatch, kwargs, status, message):
    stub_fetch(monkeypatch, **kwargs)
    res = post("https://img.example/x.png")
    assert res.status_code == status and message in res.json()["detail"]


def test_only_web_addresses(monkeypatch):
    calls = stub_fetch(monkeypatch)
    assert post("file:///etc/passwd").status_code == 400
    shortened = post("https://media.example/prod/g\u2026022202031528.jpg?q=1")
    assert shortened.status_code == 400 and "shortened" in shortened.json()["detail"]
    assert calls == []


def test_image_types_and_names():
    assert image_type(WEBP) == "image/webp" and image_type(b"GIF89a....") == "image/gif"
    assert image_type(b"\xff\xd8\xff\xe0") == "image/jpeg" and image_type(b"%PDF-1.7") is None
    assert file_name("https://x.example/", "image/jpeg") == "image.jpg"
    assert file_name("https://x.example/a/../evil name!.svg", "image/png") == "evil-name.png"


def encoded(fmt: str, mode: str = "RGB", size=(40, 30)) -> bytes:
    out = io.BytesIO()
    Image.new(mode, size, (200, 30, 30, 128) if mode == "RGBA" else (200, 30, 30)).save(out, fmt)
    return out.getvalue()


@pytest.mark.parametrize(
    "fmt, mode, media_type, name",
    [
        ("AVIF", "RGB", "image/jpeg", "photo.jpg"),  # what CDNs serve for ...f_avif
        ("BMP", "RGB", "image/jpeg", "photo.jpg"),
        ("TIFF", "RGBA", "image/png", "photo.png"),  # transparency is kept
    ],
)
def test_other_formats_are_converted(monkeypatch, fmt, mode, media_type, name):
    stub_fetch(monkeypatch, body=encoded(fmt, mode), final="https://cdn.example/photo.jpg?f_avif")
    res = post("https://cdn.example/photo.jpg?q=w_680/f_avif")
    assert res.status_code == 200 and res.headers["content-type"] == media_type
    assert res.headers["x-image-name"] == name
    with Image.open(io.BytesIO(res.content)) as im:
        assert im.size == (40, 30)


def test_decompression_bombs_are_refused(monkeypatch):
    monkeypatch.setattr(image_url, "MAX_PIXELS", 100)
    stub_fetch(monkeypatch, body=encoded("BMP"))
    res = post("https://cdn.example/huge.bmp")
    assert res.status_code == 413 and "too large" in res.json()["detail"]
