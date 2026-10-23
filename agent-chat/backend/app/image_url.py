"""Download an image from a web address for the chat UI.

Browsers can't read most sites' images from script (cross-origin rules), so the UI asks the server.
The download goes through the fact-checker's fetch: public addresses only, every redirect checked again,
reading stops at the size limit. JPEG, PNG, WebP and GIF (recognised by their bytes, not the
Content-Type header) are passed through; other formats Pillow can read, such as AVIF (which image CDNs
often serve), BMP or TIFF, are converted to JPEG, or PNG when they have transparency.
"""

import io
import re
from pathlib import PurePosixPath
from urllib.parse import unquote, urlsplit

import httpx
from PIL import Image, UnidentifiedImageError

from .local_mcp.research import FetchError, fetch

MAX_IMAGE_BYTES = 15_000_000
MAX_PIXELS = 50_000_000  # refuse "decompression bombs": small files that expand to huge images
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


def convert(data: bytes) -> tuple[bytes, str, str] | None:
    """(bytes, media type, source format) of the image as JPEG or PNG, or None if Pillow can't read it."""
    try:
        with Image.open(io.BytesIO(data)) as im:
            source = im.format or "image"
            if im.width * im.height > MAX_PIXELS:
                raise ImageUrlError(413, f"The image is too large ({im.width} x {im.height} pixels)")
            im.seek(0)  # animations: the first frame
            frame = im.convert("RGBA") if im.mode in ("RGBA", "LA", "PA") or "transparency" in im.info else im.convert("RGB")
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        return None
    out = io.BytesIO()
    if frame.mode == "RGBA":
        frame.save(out, "PNG", optimize=True)
        return out.getvalue(), "image/png", source
    frame.save(out, "JPEG", quality=92)
    return out.getvalue(), "image/jpeg", source


def file_name(url: str, media_type: str) -> str:
    """A short, safe file name from the URL's last path segment, with the right extension."""
    stem = PurePosixPath(unquote(urlsplit(url).path)).stem
    stem = re.sub(r"[^\w.-]+", "-", stem).strip(".-")[:60] or "image"
    return stem + EXTENSIONS[media_type]


async def download_image(url: str) -> tuple[bytes, str, str]:
    """(bytes, media type, file name) of the image at url, converted to JPEG or PNG when the browser-side
    pipeline wouldn't take its format."""
    if not url.lower().startswith(("http://", "https://")):
        raise ImageUrlError(400, "Enter an http(s) address of an image")
    if "\u2026" in url:  # "…": copied from a page that shortens long links for display
        raise ImageUrlError(
            400,
            "This address was shortened when it was copied (it contains \u201c\u2026\u201d). Copy the full address: "
            "right-click the image and choose Copy Image Address.",
        )
    try:
        resp, final_url, body = await fetch(url, max_bytes=MAX_IMAGE_BYTES, user_agent=USER_AGENT)
    except FetchError as exc:
        raise ImageUrlError(400, str(exc)) from exc
    except httpx.HTTPError as exc:
        raise ImageUrlError(502, f"Could not download the image ({type(exc).__name__})") from exc
    if resp.status_code == 404:
        raise ImageUrlError(502, "Nothing was found at that address (HTTP 404). Check that it is complete.")
    if resp.status_code >= 400:
        raise ImageUrlError(502, f"The address answered HTTP {resp.status_code}")
    if len(body) > MAX_IMAGE_BYTES:
        raise ImageUrlError(413, f"The image is larger than {MAX_IMAGE_BYTES // 1_000_000} MB")
    media_type = image_type(body)
    if media_type is None:
        converted = convert(body)
        if converted is None:
            hint = resp.headers.get("content-type", "").split(";")[0] or "unknown content"
            raise ImageUrlError(415, f"That address isn't an image this tool can read ({hint}). Use the image's own address.")
        body, media_type, _ = converted
    return body, media_type, file_name(final_url, media_type)
