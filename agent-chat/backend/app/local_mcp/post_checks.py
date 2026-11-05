"""Fact-checks of blog posts, for the open blog's publishing rule (blog-app/backend/app/publishing.py).

The Fact-check agent reads a post with read_post; when its report passes, the check is recorded on the post,
signed with a key derived from the origin secret, so the blog API lets it be published until the title or
text changes. The hash and the key derivation must match publishing.py exactly.
"""

import hashlib
import hmac
import os
import time

import httpx

ATTESTATION_PURPOSE = "post-pilot fact-check attestation v1"


def content_hash(title: str, content: str) -> str:
    return hashlib.sha256(f"{title.strip()}\n{content.strip()}".encode()).hexdigest()


def attestation_signature(post_id: int, digest: str, checked_at: int) -> str:
    secret = os.getenv("ORIGIN_SECRET", "")
    key = hmac.new(secret.encode(), ATTESTATION_PURPOSE.encode(), hashlib.sha256).digest()
    return hmac.new(key, f"{post_id}\n{digest}\n{checked_at}".encode(), hashlib.sha256).hexdigest()


def min_claims(content: str) -> int:
    """How many checked claims a passing report needs: one per 150 words, between 1 and 5, so a long post can't
    pass on one easy claim."""
    return max(1, min(5, len(content.split()) // 150))


def blog_api_url() -> str:
    if url := os.getenv("BLOG_API_URL"):
        return url.rstrip("/")
    if public := os.getenv("BLOG_PUBLIC_URL"):  # on AWS: the API behind CloudFront
        return public.rstrip("/") + "/api/blog"
    return "http://127.0.0.1:8100"


def _headers() -> dict[str, str]:
    secret = os.getenv("ORIGIN_SECRET")
    return {"x-origin-secret": secret} if secret and os.getenv("BLOG_API_URL") else {}


async def get_post(post_id: int) -> dict:
    async with httpx.AsyncClient(timeout=10, headers=_headers()) as client:
        resp = await client.get(f"{blog_api_url()}/posts/{post_id}")
    if resp.status_code == 404:
        raise LookupError(f"Post {post_id} not found")
    resp.raise_for_status()
    return resp.json()


async def record_check(post_id: int, digest: str, report: str) -> tuple[bool, str]:
    """Record a passing check on the post; returns whether it was recorded and the blog's answer."""
    checked_at = int(time.time())
    body = {
        "content_hash": digest,
        "checked_at": checked_at,
        "report": report[:20000],
        "signature": attestation_signature(post_id, digest, checked_at),
    }
    async with httpx.AsyncClient(timeout=10, headers=_headers()) as client:
        resp = await client.post(f"{blog_api_url()}/posts/{post_id}/fact-check", json=body)
    if resp.status_code == 200:
        return True, "recorded"
    try:
        detail = resp.json().get("detail", resp.text)
    except ValueError:
        detail = resp.text
    return False, f"HTTP {resp.status_code}: {detail}"[:300]
