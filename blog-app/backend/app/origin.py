import hmac


class OriginSecretMiddleware:
    """Reject HTTP requests without the shared `x-origin-secret` header (pure ASGI, streaming-safe).

    Lambda function URLs are public; CloudFront adds this header, so only traffic
    through CloudFront (and our own services) reaches the app.
    """

    def __init__(self, app, secret: str):
        self.app = app
        self.secret = secret.encode()

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            supplied = dict(scope["headers"]).get(b"x-origin-secret", b"")
            if not hmac.compare_digest(supplied, self.secret):
                await send({"type": "http.response.start", "status": 403, "headers": [(b"content-type", b"text/plain")]})
                await send({"type": "http.response.body", "body": b"Forbidden"})
                return
        await self.app(scope, receive, send)
