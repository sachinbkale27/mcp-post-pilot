"""Where uploaded images are stored.

MEDIA_BUCKET set (AWS): S3 objects under media/, served by CloudFront from the same bucket as
the UIs. Otherwise (local development): files in MEDIA_DIR, served by the API at /media.
Either way the public URL is the relative path /media/<file>, which works on every domain
that fronts the blog.
"""

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Protocol

# Content type -> file extension, plus the leading bytes every such file starts with.
IMAGE_TYPES = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
}
MAX_IMAGE_BYTES = 5 * 1024 * 1024


# Our upload names are 32 hex chars + extension, so any URL ending in /media/<such name> is ours.
_OWN_MEDIA_URL = re.compile(r"(?:https?:)?//[^\s()<>\"']*?/?media/([0-9a-f]{32}\.(?:jpg|png|webp|gif))\b|(?<![\w/])media/([0-9a-f]{32}\.(?:jpg|png|webp|gif))\b")


def canonical_media_urls(text: str) -> str:
    """Rewrite any absolute or mangled link to an uploaded image (e.g. https://media/x.webp,
    https://blog.example.com/media/x.webp, media/x.webp) to the canonical /media/x.webp."""
    return _OWN_MEDIA_URL.sub(lambda m: f"/media/{m.group(1) or m.group(2)}", text)


def looks_like_image(content_type: str, data: bytes) -> bool:
    """Check the file signature, so a renamed non-image is rejected."""
    return {
        "image/jpeg": data[:3] == b"\xff\xd8\xff",
        "image/png": data[:8] == b"\x89PNG\r\n\x1a\n",
        "image/gif": data[:6] in (b"GIF87a", b"GIF89a"),
        "image/webp": data[:4] == b"RIFF" and data[8:12] == b"WEBP",
    }.get(content_type, False)


class MediaStore(Protocol):
    def save(self, name: str, data: bytes, content_type: str) -> str: ...


class LocalMediaStore:
    def __init__(self, directory: Path):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)

    def save(self, name, data, content_type):
        (self.directory / name).write_bytes(data)
        return f"/media/{name}"


class S3MediaStore:
    def __init__(self, bucket: str):
        import boto3

        self._s3 = boto3.client("s3")
        self._bucket = bucket

    def save(self, name, data, content_type):
        self._s3.put_object(
            Bucket=self._bucket,
            Key=f"media/{name}",
            Body=data,
            ContentType=content_type,
            CacheControl="public, max-age=31536000, immutable",  # names are random, never reused
        )
        return f"/media/{name}"


def local_media_dir() -> Path:
    return Path(os.getenv("MEDIA_DIR", Path(__file__).resolve().parents[1] / "media"))


@lru_cache
def get_media_store() -> MediaStore:
    if bucket := os.getenv("MEDIA_BUCKET"):
        return S3MediaStore(bucket)
    return LocalMediaStore(local_media_dir())
