"""Download an image from a web address for the chat UI.

Browsers can't read most sites' images from script (cross-origin rules), so the UI asks the server.
The download goes through the fact-checker's fetch: public addresses only, every redirect checked again,
reading stops at the size limit. Only JPEG, PNG, WebP and GIF are accepted, recognised by their bytes
rather than the Content-Type header.
"""

import re
from pathlib import PurePosixPath
from urllib.parse import unquote, urlsplit

import httpx

from .local_mcp.research import FetchError, fetch

MAX_IMAGE_BYTES = 15_000_000
USER_AGENT = "PostPilotImageFetch/1.0 (+https://agent.sachin-kale.com)"
EXTENSIONS = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif"}


class ImageUrlError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


def image_type(data: bytes) -> str | None:
    """The image's media type from its first bytes, or None if it isn't a JPEG, PNG, WebP or GIF."""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return None


def file_name(url: str, media_type: str) -> str:
    """A short, safe file name from the URL's last path segment, with the right extension."""
    stem = PurePosixPath(unquote(urlsplit(url).path)).stem
    stem = re.sub(r"[^\w.-]+", "-", stem).strip(".-")[:60] or "image"
    return stem + EXTENSIONS[media_type]


async def download_image(url: str) -> tuple[bytes, str, str]:
    """(bytes, media type, file name) of the image at url."""
    if not url.lower().startswith(("http://", "https://")):
        raise ImageUrlError(400, "Enter an http(s) address of an image")
    try:
        resp, final_url, body = await fetch(url, max_bytes=MAX_IMAGE_BYTES, user_agent=USER_AGENT)
    except FetchError as exc:
        raise ImageUrlError(400, str(exc)) from exc
    except httpx.HTTPError as exc:
        raise ImageUrlError(502, f"Could not download the image ({type(exc).__name__})") from exc
    if resp.status_code >= 400:
        raise ImageUrlError(502, f"The address answered HTTP {resp.status_code}")
    if len(body) > MAX_IMAGE_BYTES:
        raise ImageUrlError(413, f"The image is larger than {MAX_IMAGE_BYTES // 1_000_000} MB")
    media_type = image_type(body)
    if media_type is None:
        hint = resp.headers.get("content-type", "").split(";")[0] or "unknown content"
        raise ImageUrlError(415, f"That address isn't a JPEG, PNG, WebP or GIF image ({hint}). Use the image's own address.")
    return body, media_type, file_name(final_url, media_type)
