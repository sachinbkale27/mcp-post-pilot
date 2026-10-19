from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PostCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = ""
    author: str = "anonymous"
    cover_image_url: str | None = Field(default=None, max_length=500)
    category: str | None = Field(default=None, max_length=60)


class PostUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    content: str | None = None
    author: str | None = None
    cover_image_url: str | None = Field(default=None, max_length=500)
    category: str | None = Field(default=None, max_length=60)


class PostOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    content: str
    author: str
    status: Literal["draft", "published"]
    created_at: datetime
    updated_at: datetime
    published_at: datetime | None
    cover_image_url: str | None = None
    category: str | None = None


class CategoryOut(BaseModel):
    name: str
    count: int
