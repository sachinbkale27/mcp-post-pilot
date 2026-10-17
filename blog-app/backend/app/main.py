"""Blog REST API. The React UI and the MCP server are both clients of this API."""

import os
from datetime import datetime, timezone
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware

from .origin import OriginSecretMiddleware
from .schemas import PostCreate, PostOut, PostUpdate
from .store import Post, PostStore, get_store

app = FastAPI(title="Blog API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)
# On AWS only CloudFront (and the MCP server) know this secret; direct calls are rejected.
if secret := os.getenv("ORIGIN_SECRET"):
    app.add_middleware(OriginSecretMiddleware, secret=secret)


def _found(post: Post | None, post_id: int) -> Post:
    if post is None:
        raise HTTPException(status_code=404, detail=f"Post {post_id} not found")
    return post


@app.get("/posts", response_model=list[PostOut])
def list_posts(
    status: Literal["draft", "published"] | None = None,
    q: str | None = None,
    store: PostStore = Depends(get_store),
):
    return store.list(status=status, q=q)


@app.post("/posts", response_model=PostOut, status_code=201)
def create_post(body: PostCreate, store: PostStore = Depends(get_store)):
    return store.create(body.model_dump())


@app.get("/posts/{post_id}", response_model=PostOut)
def get_post(post_id: int, store: PostStore = Depends(get_store)):
    return _found(store.get(post_id), post_id)


@app.patch("/posts/{post_id}", response_model=PostOut)
def update_post(post_id: int, body: PostUpdate, store: PostStore = Depends(get_store)):
    return _found(store.update(post_id, body.model_dump(exclude_unset=True)), post_id)


@app.post("/posts/{post_id}/publish", response_model=PostOut)
def publish_post(post_id: int, store: PostStore = Depends(get_store)):
    fields = {"status": "published", "published_at": datetime.now(timezone.utc)}
    return _found(store.update(post_id, fields), post_id)


@app.post("/posts/{post_id}/unpublish", response_model=PostOut)
def unpublish_post(post_id: int, store: PostStore = Depends(get_store)):
    return _found(store.update(post_id, {"status": "draft", "published_at": None}), post_id)


@app.delete("/posts/{post_id}", status_code=204)
def delete_post(post_id: int, store: PostStore = Depends(get_store)):
    if not store.delete(post_id):
        raise HTTPException(status_code=404, detail=f"Post {post_id} not found")
    return Response(status_code=204)
