"""Blog REST API. The React UI and the MCP server are both clients of this API."""

import os
import time
import uuid
from datetime import datetime, timezone
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .media import IMAGE_TYPES, MAX_IMAGE_BYTES, canonical_media_urls, get_media_store, local_media_dir, looks_like_image
from .origin import OriginSecretMiddleware
from .publishing import MAX_CHECK_AGE, content_hash, fact_checked, is_owner, valid_attestation
from .schemas import CategoryOut, FactCheckRecord, PostCreate, PostOut, PostUpdate
from .store import Post, PostStore, category_counts, get_store

app = FastAPI(title="Blog API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174"],  # blog and chat dev servers
    allow_methods=["*"],
    allow_headers=["*"],
)
# On AWS only CloudFront (and the MCP server) know this secret; direct calls are rejected.
if secret := os.getenv("ORIGIN_SECRET"):
    app.add_middleware(OriginSecretMiddleware, secret=secret)
# Locally the API serves uploaded images itself; on AWS CloudFront serves them from S3.
if not os.getenv("MEDIA_BUCKET"):
    local_media_dir().mkdir(parents=True, exist_ok=True)
    app.mount("/media", StaticFiles(directory=local_media_dir()), name="media")


def _clean(fields: dict, store: PostStore) -> dict:
    """Normalize fields before saving.

    - links to uploaded images get one canonical form (/media/<name>)
    - categories are trimmed, and reuse the spelling of an existing category that matches
      case-insensitively, so "science" doesn't become a second "Science" topic
    """
    for key in ("content", "cover_image_url"):
        if fields.get(key):
            fields[key] = canonical_media_urls(fields[key])
    if "category" in fields:
        name = " ".join((fields["category"] or "").split())
        if not name:
            fields["category"] = None
        else:
            existing = {c.lower(): c for c, _ in category_counts(store.list())}
            fields["category"] = existing.get(name.lower(), name)
    return fields


def _found(post: Post | None, post_id: int) -> Post:
    if post is None:
        raise HTTPException(status_code=404, detail=f"Post {post_id} not found")
    return {**post, "fact_checked": fact_checked(post)}


OwnerKey = Annotated[str | None, Header(alias="x-owner-key")]
OWNER_ONLY = "Published posts can only be changed, unpublished or deleted by the blog owner."


def _require_owner_if_published(post: Post, owner: str | None) -> None:
    if post["status"] == "published" and not is_owner(owner):
        raise HTTPException(status_code=403, detail=OWNER_ONLY)


@app.get("/posts", response_model=list[PostOut])
def list_posts(
    status: Literal["draft", "published"] | None = None,
    q: str | None = None,
    category: str | None = None,
    store: PostStore = Depends(get_store),
):
    return [{**p, "fact_checked": fact_checked(p)} for p in store.list(status=status, q=q, category=category)]


@app.get("/categories", response_model=list[CategoryOut])
def list_categories(
    status: Literal["draft", "published"] | None = None,
    store: PostStore = Depends(get_store),
):
    """Subjects in use, with how many posts (optionally only drafts or published) fall under each."""
    return [{"name": name, "count": count} for name, count in category_counts(store.list(status=status))]


@app.post("/posts", response_model=PostOut, status_code=201)
def create_post(body: PostCreate, store: PostStore = Depends(get_store)):
    return _found(store.create(_clean(body.model_dump(), store)), 0)


@app.get("/posts/{post_id}", response_model=PostOut)
def get_post(post_id: int, store: PostStore = Depends(get_store)):
    return _found(store.get(post_id), post_id)


@app.patch("/posts/{post_id}", response_model=PostOut)
def update_post(post_id: int, body: PostUpdate, owner: OwnerKey = None, store: PostStore = Depends(get_store)):
    _require_owner_if_published(_found(store.get(post_id), post_id), owner)
    return _found(store.update(post_id, _clean(body.model_dump(exclude_unset=True), store)), post_id)


@app.post("/posts/{post_id}/fact-check", response_model=PostOut)
def record_fact_check(post_id: int, body: FactCheckRecord, store: PostStore = Depends(get_store)):
    """Record a passing fact-check (sent by the Fact-check agent, signed); the post may then be published."""
    post = _found(store.get(post_id), post_id)
    if not valid_attestation(post_id, body.content_hash, body.checked_at, body.signature):
        raise HTTPException(status_code=403, detail="This fact-check record isn't signed by the Fact-check agent.")
    if abs(time.time() - body.checked_at) > MAX_CHECK_AGE:
        raise HTTPException(status_code=409, detail="This fact-check is too old to record; check the post again.")
    if body.content_hash != content_hash(post["title"], post["content"]):
        raise HTTPException(status_code=409, detail=f"Post {post_id} changed after it was checked; check it again.")
    fields = {
        "fact_check_hash": body.content_hash,
        "fact_check_at": datetime.fromtimestamp(body.checked_at, timezone.utc),
        "fact_check_report": body.report,
    }
    return _found(store.update(post_id, fields), post_id)


@app.post("/posts/{post_id}/publish", response_model=PostOut)
def publish_post(post_id: int, owner: OwnerKey = None, store: PostStore = Depends(get_store)):
    """Publish a draft. Its current title and text must have passed a fact-check, unless the owner publishes it."""
    post = _found(store.get(post_id), post_id)
    if post["status"] == "published":
        return post
    if not post["fact_checked"] and not is_owner(owner):
        raise HTTPException(
            status_code=409,
            detail=(
                f"Post {post_id} needs a passing fact-check before it can be published: the Fact-check agent must "
                "check its current title and text and find every factual claim supported by a source. "
                + ("It was edited after its last check. " if post.get("fact_check_hash") else "")
                + "Ask it to fact-check this post, fix what it flags, then publish."
            ),
        )
    fields = {"status": "published", "published_at": datetime.now(timezone.utc)}
    return _found(store.update(post_id, fields), post_id)


@app.post("/posts/{post_id}/unpublish", response_model=PostOut)
def unpublish_post(post_id: int, owner: OwnerKey = None, store: PostStore = Depends(get_store)):
    _require_owner_if_published(_found(store.get(post_id), post_id), owner)
    return _found(store.update(post_id, {"status": "draft", "published_at": None}), post_id)


@app.delete("/posts/{post_id}", status_code=204)
def delete_post(post_id: int, owner: OwnerKey = None, store: PostStore = Depends(get_store)):
    _require_owner_if_published(_found(store.get(post_id), post_id), owner)
    if not store.delete(post_id):
        raise HTTPException(status_code=404, detail=f"Post {post_id} not found")
    return Response(status_code=204)


@app.post("/images", status_code=201)
async def upload_image(request: Request):
    """Store an image sent as the raw request body; returns its public URL.

    The chat UI resizes images in the browser first, so uploads stay small.
    """
    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type not in IMAGE_TYPES:
        raise HTTPException(status_code=415, detail="Upload a JPEG, PNG, WebP or GIF image")
    data = await request.body()
    if not data:
        raise HTTPException(status_code=400, detail="Empty upload")
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail=f"Images must be under {MAX_IMAGE_BYTES // (1024 * 1024)} MB")
    if not looks_like_image(content_type, data):
        raise HTTPException(status_code=400, detail="The file is not a valid image")
    name = f"{uuid.uuid4().hex}.{IMAGE_TYPES[content_type]}"
    return {"url": get_media_store().save(name, data, content_type)}
