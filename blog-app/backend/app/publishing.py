"""Who may publish and change posts on the open blog.

Anyone can write drafts, but a post is only published when the Fact-check agent has checked its exact text
and found every claim supported by a source it read (or when the blog owner publishes it). Published posts
can only be changed, unpublished or deleted by the owner.

The Fact-check agent records a passing check with POST /posts/{id}/fact-check, signed with a key derived
from the origin secret that only CloudFront and the site's own services know; the record names the hash of
the title and text it checked, so any later edit needs a new check. The owner's key is derived from the same
secret (deploy/owner-key.sh prints it). Without an origin secret (local development) every request counts
as the owner's, as before.
"""

import hashlib
import hmac
import os

ATTESTATION_PURPOSE = "post-pilot fact-check attestation v1"
OWNER_PURPOSE = "post-pilot blog owner v1"
MAX_CHECK_AGE = 15 * 60  # seconds between the check and recording it


def content_hash(title: str, content: str) -> str:
    """The hash a fact-check is bound to: the title and text, ignoring surrounding whitespace."""
    return hashlib.sha256(f"{title.strip()}\n{content.strip()}".encode()).hexdigest()


def _derived(purpose: str) -> bytes | None:
    secret = os.getenv("ORIGIN_SECRET")
    return hmac.new(secret.encode(), purpose.encode(), hashlib.sha256).digest() if secret else None


def attestation_signature(post_id: int, digest: str, checked_at: int) -> str | None:
    key = _derived(ATTESTATION_PURPOSE)
    if key is None:
        return None
    return hmac.new(key, f"{post_id}\n{digest}\n{checked_at}".encode(), hashlib.sha256).hexdigest()


def valid_attestation(post_id: int, digest: str, checked_at: int, signature: str) -> bool:
    expected = attestation_signature(post_id, digest, checked_at)
    if expected is None:  # local development: no secret to sign with
        return True
    return hmac.compare_digest(expected, signature)


def owner_key() -> str | None:
    key = _derived(OWNER_PURPOSE)
    return key.hex() if key else None


def is_owner(supplied: str | None) -> bool:
    expected = owner_key()
    if expected is None:
        return True
    return bool(supplied) and hmac.compare_digest(expected, supplied)


def fact_checked(post: dict) -> bool:
    """Whether the post's current title and text passed a fact-check."""
    return bool(post.get("fact_check_hash")) and post["fact_check_hash"] == content_hash(post["title"], post["content"])
