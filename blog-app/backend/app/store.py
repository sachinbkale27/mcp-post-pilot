"""Where posts are stored.

STORAGE_BACKEND selects the implementation:
  postgres (default) - SQLAlchemy + PostgreSQL, used for local development
  dynamodb           - Amazon DynamoDB, used by the serverless deployment on AWS

Both return posts as plain dicts with the fields of schemas.PostOut.
"""

import os
from datetime import datetime, timezone
from decimal import Decimal
from functools import lru_cache
from typing import Any, Protocol

Post = dict[str, Any]


class PostStore(Protocol):
    def list(self, status: str | None = None, q: str | None = None) -> list[Post]: ...
    def create(self, fields: dict[str, Any]) -> Post: ...
    def get(self, post_id: int) -> Post | None: ...
    def update(self, post_id: int, fields: dict[str, Any]) -> Post | None: ...
    def delete(self, post_id: int) -> bool: ...


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SqlPostStore:
    def __init__(self):
        from .db import Base, SessionLocal, engine

        Base.metadata.create_all(engine)
        self._sessions = SessionLocal

    @staticmethod
    def _to_dict(post) -> Post:
        return {c.name: getattr(post, c.name) for c in post.__table__.columns}

    def list(self, status=None, q=None):
        from sqlalchemy import or_, select

        from .models import Post as PostRow

        stmt = select(PostRow).order_by(PostRow.updated_at.desc())
        if status:
            stmt = stmt.where(PostRow.status == status)
        if q:
            like = f"%{q}%"
            stmt = stmt.where(or_(PostRow.title.ilike(like), PostRow.content.ilike(like)))
        with self._sessions() as db:
            return [self._to_dict(p) for p in db.scalars(stmt)]

    def create(self, fields):
        from .models import Post as PostRow

        with self._sessions() as db:
            post = PostRow(**fields)
            db.add(post)
            db.commit()
            db.refresh(post)
            return self._to_dict(post)

    def get(self, post_id):
        from .models import Post as PostRow

        with self._sessions() as db:
            post = db.get(PostRow, post_id)
            return self._to_dict(post) if post else None

    def update(self, post_id, fields):
        from .models import Post as PostRow

        with self._sessions() as db:
            post = db.get(PostRow, post_id)
            if post is None:
                return None
            for field, value in fields.items():
                setattr(post, field, value)
            db.commit()
            db.refresh(post)
            return self._to_dict(post)

    def delete(self, post_id):
        from .models import Post as PostRow

        with self._sessions() as db:
            post = db.get(PostRow, post_id)
            if post is None:
                return False
            db.delete(post)
            db.commit()
            return True


class DynamoPostStore:
    """One item per post, keyed by a numeric id.

    Ids come from an atomic counter kept in the same table under id 0.
    Listing scans the table, which is fine for a blog-sized dataset.
    """

    COUNTER_ID = 0

    def __init__(self, table_name: str):
        import boto3

        self._table = boto3.resource("dynamodb").Table(table_name)
        from botocore.exceptions import ClientError

        self._ClientError = ClientError

    @staticmethod
    def _from_item(item: dict[str, Any]) -> Post:
        return {k: int(v) if isinstance(v, Decimal) else v for k, v in item.items()}

    @staticmethod
    def _iso(value: Any) -> Any:
        return value.isoformat() if isinstance(value, datetime) else value

    def _is_missing(self, exc) -> bool:
        return exc.response["Error"]["Code"] == "ConditionalCheckFailedException"

    def list(self, status=None, q=None):
        items, kwargs = [], {}
        while True:
            page = self._table.scan(**kwargs)
            items.extend(page["Items"])
            if "LastEvaluatedKey" not in page:
                break
            kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
        posts = [self._from_item(i) for i in items if i["id"] != self.COUNTER_ID]
        if status:
            posts = [p for p in posts if p["status"] == status]
        if q:
            needle = q.lower()
            posts = [p for p in posts if needle in p["title"].lower() or needle in p["content"].lower()]
        return sorted(posts, key=lambda p: p["updated_at"], reverse=True)

    def create(self, fields):
        counter = self._table.update_item(
            Key={"id": self.COUNTER_ID},
            UpdateExpression="ADD next_id :one",
            ExpressionAttributeValues={":one": 1},
            ReturnValues="UPDATED_NEW",
        )
        now = _now().isoformat()
        post = {
            "id": int(counter["Attributes"]["next_id"]),
            "status": "draft",
            "created_at": now,
            "updated_at": now,
            "published_at": None,
            **fields,
        }
        self._table.put_item(Item=post)
        return post

    def get(self, post_id):
        item = self._table.get_item(Key={"id": post_id}).get("Item")
        return self._from_item(item) if item else None

    def update(self, post_id, fields):
        values = {**fields, "updated_at": _now()}
        names = {f"#{k}": k for k in values}  # "status" etc. are DynamoDB reserved words
        try:
            result = self._table.update_item(
                Key={"id": post_id},
                UpdateExpression="SET " + ", ".join(f"#{k} = :{k}" for k in values),
                ExpressionAttributeNames=names,
                ExpressionAttributeValues={f":{k}": self._iso(v) for k, v in values.items()},
                ConditionExpression="attribute_exists(id)",
                ReturnValues="ALL_NEW",
            )
        except self._ClientError as exc:
            if self._is_missing(exc):
                return None
            raise
        return self._from_item(result["Attributes"])

    def delete(self, post_id):
        try:
            self._table.delete_item(Key={"id": post_id}, ConditionExpression="attribute_exists(id)")
        except self._ClientError as exc:
            if self._is_missing(exc):
                return False
            raise
        return True


@lru_cache
def get_store() -> PostStore:
    if os.getenv("STORAGE_BACKEND", "postgres") == "dynamodb":
        return DynamoPostStore(os.environ["POSTS_TABLE"])
    return SqlPostStore()
