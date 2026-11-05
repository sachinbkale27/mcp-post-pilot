"""Publishing on the open blog: drafts for anyone, publishing only after a signed, passing fact-check of the
exact text (or by the owner), and published posts changed only by the owner. In-memory store, no database."""

import time
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app import main, publishing
from app.store import get_store

SECRET = "s" * 40
ORIGIN = {"x-origin-secret": SECRET}


class MemoryStore:
    def __init__(self):
        self.posts: dict[int, dict] = {}

    def list(self, status=None, q=None, category=None):
        return [p for p in self.posts.values() if not status or p["status"] == status]

    def create(self, fields):
        now = datetime.now(timezone.utc)
        post = {"id": len(self.posts) + 1, "status": "draft", "created_at": now, "updated_at": now, "published_at": None, **fields}
        self.posts[post["id"]] = post
        return dict(post)

    def get(self, post_id):
        return dict(self.posts[post_id]) if post_id in self.posts else None

    def update(self, post_id, fields):
        if post_id not in self.posts:
            return None
        self.posts[post_id].update(fields, updated_at=datetime.now(timezone.utc))
        return dict(self.posts[post_id])

    def delete(self, post_id):
        return self.posts.pop(post_id, None) is not None


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ORIGIN_SECRET", SECRET)
    store = MemoryStore()
    main.app.user_middleware.clear()  # the origin check is added at import time only when the secret is set
    main.app.middleware_stack = None
    main.app.add_middleware(main.OriginSecretMiddleware, secret=SECRET)
    main.app.dependency_overrides[get_store] = lambda: store
    with TestClient(main.app, headers=ORIGIN) as c:
        yield c
    main.app.dependency_overrides.clear()


def attest(post: dict, *, checked_at: int | None = None, digest: str | None = None) -> dict:
    checked_at = checked_at or int(time.time())
    digest = digest or publishing.content_hash(post["title"], post["content"])
    return {
        "content_hash": digest,
        "checked_at": checked_at,
        "report": "**Fact-check: ready to publish** (3 claims checked: 3 supported)",
        "signature": publishing.attestation_signature(post["id"], digest, checked_at),
    }


def draft(client) -> dict:
    return client.post("/posts", json={"title": "CFTR", "content": "F508del is the most common CFTR variant."}).json()


def test_anyone_can_draft_but_not_publish_unchecked(client):
    post = draft(client)
    assert post["status"] == "draft" and post["fact_checked"] is False
    refused = client.post(f"/posts/{post['id']}/publish")
    assert refused.status_code == 409 and "needs a passing fact-check" in refused.json()["detail"]


def test_a_signed_check_of_the_exact_text_allows_publishing(client):
    post = draft(client)
    recorded = client.post(f"/posts/{post['id']}/fact-check", json=attest(post)).json()
    assert recorded["fact_checked"] and "ready to publish" in recorded["fact_check_report"]
    published = client.post(f"/posts/{post['id']}/publish").json()
    assert published["status"] == "published" and published["fact_checked"]


def test_editing_after_the_check_needs_a_new_check(client):
    post = draft(client)
    client.post(f"/posts/{post['id']}/fact-check", json=attest(post))
    client.patch(f"/posts/{post['id']}", json={"content": "F508del cures cancer."})
    refused = client.post(f"/posts/{post['id']}/publish")
    assert refused.status_code == 409 and "edited after its last check" in refused.json()["detail"]


def test_forged_stale_or_mismatched_checks_are_refused(client):
    post = draft(client)
    forged = {**attest(post), "signature": "0" * 64}
    assert client.post(f"/posts/{post['id']}/fact-check", json=forged).status_code == 403
    stale = attest(post, checked_at=int(time.time()) - 3600)
    assert client.post(f"/posts/{post['id']}/fact-check", json=stale).status_code == 409
    other = attest(post, digest=publishing.content_hash("CFTR", "something else"))
    assert "changed after it was checked" in client.post(f"/posts/{post['id']}/fact-check", json=other).json()["detail"]
    # A check signed for another post doesn't transfer
    second = draft(client)
    moved = {**attest(post), "content_hash": publishing.content_hash(second["title"], second["content"])}
    assert client.post(f"/posts/{second['id']}/fact-check", json=moved).status_code == 403


def test_published_posts_are_changed_only_by_the_owner(client):
    post = draft(client)
    client.post(f"/posts/{post['id']}/fact-check", json=attest(post))
    client.post(f"/posts/{post['id']}/publish")
    for method, path, body in [("PATCH", "", {"content": "changed"}), ("POST", "/unpublish", None), ("DELETE", "", None)]:
        resp = client.request(method, f"/posts/{post['id']}{path}", json=body)
        assert resp.status_code == 403 and "blog owner" in resp.json()["detail"], (method, path)
        wrong = client.request(method, f"/posts/{post['id']}{path}", json=body, headers={"x-owner-key": "nope"})
        assert wrong.status_code == 403
    owner = {"x-owner-key": publishing.owner_key()}
    assert client.patch(f"/posts/{post['id']}", json={"content": "fixed"}, headers=owner).status_code == 200
    assert client.delete(f"/posts/{post['id']}", headers=owner).status_code == 204


def test_the_owner_can_publish_without_a_check_and_drafts_stay_open(client):
    post = draft(client)
    owner = {"x-owner-key": publishing.owner_key()}
    assert client.post(f"/posts/{post['id']}/publish", headers=owner).json()["status"] == "published"
    other = draft(client)
    assert client.patch(f"/posts/{other['id']}", json={"content": "edited draft"}).status_code == 200
    assert client.delete(f"/posts/{other['id']}").status_code == 204


def test_without_the_origin_secret_nothing_gets_through(client):
    with TestClient(main.app) as bare:
        assert bare.post("/posts", json={"title": "x"}).status_code == 403


def test_signatures_match_the_fact_check_agent(monkeypatch):
    # The same vector is pinned in agent-chat/backend/tests/test_research.py
    monkeypatch.setenv("ORIGIN_SECRET", "x" * 40)
    digest = publishing.content_hash("T", "body")
    assert publishing.attestation_signature(3, digest, 100) == "e15c416bf310abf21ba768a4db46e627540c8af357f68b6df357387d1855a58f"
