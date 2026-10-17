from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PostCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = ""
    author: str = "anonymous"


class PostUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    content: str | None = None
    author: str | None = None


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
