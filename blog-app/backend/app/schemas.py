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
    # Whether the current title and text passed the Fact-check agent, and its report
    fact_checked: bool = False
    fact_check_at: datetime | None = None
    fact_check_report: str | None = None


class FactCheckRecord(BaseModel):
    """A passing fact-check of a post's exact title and text, signed by the Fact-check agent."""

    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    checked_at: int = Field(description="Unix time of the check")
    report: str = Field(max_length=20000)
    signature: str = Field(pattern=r"^[0-9a-f]{64}$")


class CategoryOut(BaseModel):
    name: str
    count: int
