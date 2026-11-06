"""Where the chat's visitor is, passed on to the Image Label server so its usage counts show people and places.

CloudFront adds the visitor's city, region, country and time zone to each request (CloudFront-Viewer-*). The
visitor id is a hash of their address and browser with a secret and the date: it counts distinct visitors per
day, can't be reversed to an address, and changes daily. The address itself goes only to the Image Label
server, which logs it as a keyed hash to count distinct addresses. The site's own usage analytics (analytics.py)
store the same visitor id and place, never the address; the only cookie read is the owner's "internal" mark.
"""

import datetime
import hashlib
import os
from contextvars import ContextVar
from urllib.parse import quote

VIEWER: ContextVar[dict[str, str]] = ContextVar("viewer", default={})
# This request's headers (lower-cased) plus "x-client-host", the TCP peer: for the usage analytics
REQUEST: ContextVar[dict[str, str]] = ContextVar("request", default={})


def is_internal(headers: dict[str, str]) -> bool:
    """The owner's own browsers (set with ?internal=1 on the site): left out of the usage counts."""
    return "internal=1" in headers.get("cookie", "").replace(" ", "").split(";")


def visitor_id(address: str, user_agent: str) -> str:
    """Distinct per address + browser + day; keyed with the origin secret, so it can't be reversed to an address."""
    day = datetime.date.today().isoformat()
    seed = f"{os.getenv('ORIGIN_SECRET', '')}|{day}|{address}|{user_agent}"
    return hashlib.sha256(seed.encode()).hexdigest()[:12]


def viewer_headers(headers: dict[str, str]) -> dict[str, str]:
    """The x-viewer-* headers for this request, or none when it didn't come through CloudFront."""
    internal = {"x-viewer-internal": "1"} if is_internal(headers) else {}
    country = headers.get("cloudfront-viewer-country", "")
    if not country:
        return internal
    address = headers.get("cloudfront-viewer-address", "").rsplit(":", 1)[0]  # "ip:port"
    values = {
        "x-viewer-visitor": visitor_id(address, headers.get("user-agent", "")),
        "x-viewer-country": country,
        "x-viewer-region": headers.get("cloudfront-viewer-country-region-name", ""),
        "x-viewer-city": headers.get("cloudfront-viewer-city", ""),
        "x-viewer-time-zone": headers.get("cloudfront-viewer-time-zone", ""),
        # For counting distinct addresses: Image Label logs it only as a keyed hash
        "x-viewer-address": address,
    }
    return {key: quote(value[:100], safe=" /_-") for key, value in values.items() if value} | internal


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
        client = scope.get("client") or ("", 0)
        request_token = REQUEST.set(headers | {"x-client-host": client[0] or ""})
        try:
            await self.app(scope, receive, send)
        finally:
            REQUEST.reset(request_token)
            VIEWER.reset(token)
