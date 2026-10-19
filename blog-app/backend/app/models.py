from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class Post(Base):
    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text, default="")
    author: Mapped[str] = mapped_column(String(100), default="anonymous")
    # "draft" until published; only published posts appear on the public feed.
    status: Mapped[str] = mapped_column(String(20), default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Shown on post cards and at the top of the article; usually a /media/... URL.
    cover_image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Subject the post falls under (e.g. "Science"); shown in the blog's Topics panel.
    category: Mapped[str | None] = mapped_column(String(60), nullable=True)
