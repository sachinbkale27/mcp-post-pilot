"""Blog REST API. The React UI and the MCP server are both clients of this API."""

from datetime import datetime, timezone
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .db import Base, engine, get_db
from .models import Post
from .schemas import PostCreate, PostOut, PostUpdate

Base.metadata.create_all(engine)

app = FastAPI(title="Blog API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _get_or_404(db: Session, post_id: int) -> Post:
    post = db.get(Post, post_id)
    if post is None:
        raise HTTPException(status_code=404, detail=f"Post {post_id} not found")
    return post


@app.get("/posts", response_model=list[PostOut])
def list_posts(
    status: Literal["draft", "published"] | None = None,
    q: str | None = None,
    db: Session = Depends(get_db),
):
    stmt = select(Post).order_by(Post.updated_at.desc())
    if status:
        stmt = stmt.where(Post.status == status)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Post.title.ilike(like), Post.content.ilike(like)))
    return db.scalars(stmt).all()


@app.post("/posts", response_model=PostOut, status_code=201)
def create_post(body: PostCreate, db: Session = Depends(get_db)):
    post = Post(**body.model_dump())
    db.add(post)
    db.commit()
    db.refresh(post)
    return post


@app.get("/posts/{post_id}", response_model=PostOut)
def get_post(post_id: int, db: Session = Depends(get_db)):
    return _get_or_404(db, post_id)


@app.patch("/posts/{post_id}", response_model=PostOut)
def update_post(post_id: int, body: PostUpdate, db: Session = Depends(get_db)):
    post = _get_or_404(db, post_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(post, field, value)
    db.commit()
    db.refresh(post)
    return post


@app.post("/posts/{post_id}/publish", response_model=PostOut)
def publish_post(post_id: int, db: Session = Depends(get_db)):
    post = _get_or_404(db, post_id)
    post.status = "published"
    post.published_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(post)
    return post


@app.post("/posts/{post_id}/unpublish", response_model=PostOut)
def unpublish_post(post_id: int, db: Session = Depends(get_db)):
    post = _get_or_404(db, post_id)
    post.status = "draft"
    post.published_at = None
    db.commit()
    db.refresh(post)
    return post


@app.delete("/posts/{post_id}", status_code=204)
def delete_post(post_id: int, db: Session = Depends(get_db)):
    post = _get_or_404(db, post_id)
    db.delete(post)
    db.commit()
    return Response(status_code=204)
