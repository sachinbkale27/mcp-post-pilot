"""Where the chat's visitor is, passed on to the Image Label server so its usage counts show people and places.

CloudFront adds the visitor's city, region, country and time zone to each request (CloudFront-Viewer-*). The
visitor id is a hash of their address and browser with a secret and the date: it counts distinct visitors per
day, can't be reversed to an address, and changes daily. Nothing is stored here; no cookie is set.
"""

import datetime
import hashlib
import os
from contextvars import ContextVar
from urllib.parse import quote

VIEWER: ContextVar[dict[str, str]] = ContextVar("viewer", default={})


def viewer_headers(headers: dict[str, str]) -> dict[str, str]:
    """The x-viewer-* headers for this request, or none when it didn't come through CloudFront."""
    country = headers.get("cloudfront-viewer-country", "")
    if not country:
        return {}
    address = headers.get("cloudfront-viewer-address", "").rsplit(":", 1)[0]  # "ip:port"
    day = datetime.date.today().isoformat()
    seed = f"{os.getenv('ORIGIN_SECRET', '')}|{day}|{address}|{headers.get('user-agent', '')}"
    values = {
        "x-viewer-visitor": hashlib.sha256(seed.encode()).hexdigest()[:12],
        "x-viewer-country": country,
        "x-viewer-region": headers.get("cloudfront-viewer-country-region-name", ""),
        "x-viewer-city": headers.get("cloudfront-viewer-city", ""),
        "x-viewer-time-zone": headers.get("cloudfront-viewer-time-zone", ""),
    }
    return {key: quote(value[:100], safe=" /_-") for key, value in values.items() if value}


class ViewerMiddleware:
    """Pure ASGI (streaming-safe): makes the visitor's place available to MCP calls made for this request."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {key.decode("latin-1").lower(): value.decode("latin-1") for key, value in scope["headers"]}
        token = VIEWER.set(viewer_headers(headers))
        try:
            await self.app(scope, receive, send)
        finally:
            VIEWER.reset(token)
