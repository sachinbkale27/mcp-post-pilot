"""MCP server for the blog.

It exposes the three MCP primitives:
  - Tools     (model-controlled actions):  list_posts, get_post, create_post, ...
  - Resources (application-controlled data): blog://posts, blog://posts/{post_id}
  - Prompts   (user-controlled templates):  draft_blog_post, review_post

It is a thin adapter over the Blog REST API: every tool is one HTTP call.
That keeps the business rules in one place (the FastAPI app) and shows that
an MCP server is just another client of your existing system.

Run:  python mcp_server/server.py   ->  Streamable HTTP at http://127.0.0.1:8101/mcp
"""

import json
import os
from typing import Literal

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp_types import ToolAnnotations

BLOG_API_URL = os.getenv("BLOG_API_URL", "http://127.0.0.1:8100")

mcp = MCPServer(
    name="blog",
    instructions=(
        "Tools for managing a blog. Posts start as drafts; publish_post makes "
        "them public. Use list_posts or search_posts to find post ids."
    ),
)


class BlogAPIError(ToolError):
    """ToolError messages are shown to the model; any other exception is masked."""


async def _api(method: str, path: str, **kwargs) -> dict | list | None:
    async with httpx.AsyncClient(base_url=BLOG_API_URL, timeout=10) as client:
        resp = await client.request(method, path, **kwargs)
    if resp.status_code >= 400:
        # Raising inside a tool makes the server return a result with
        # isError=true, which the model sees and can recover from (e.g. retry with a valid id).
        detail = resp.json().get("detail", resp.text) if resp.content else resp.reason_phrase
        raise BlogAPIError(f"{resp.status_code}: {detail}")
    return resp.json() if resp.content else None


def _summary(post: dict) -> dict:
    return {k: post[k] for k in ("id", "title", "author", "status", "updated_at")}


# ---------------------------------------------------------------- tools

READ_ONLY = ToolAnnotations(readOnlyHint=True)


@mcp.tool(annotations=READ_ONLY)
async def list_posts(status: Literal["draft", "published"] | None = None) -> list[dict]:
    """List blog posts (without their full content), newest first.

    Args:
        status: Only return posts with this status. Omit to return all posts.
    """
    params = {"status": status} if status else {}
    return [_summary(p) for p in await _api("GET", "/posts", params=params)]


@mcp.tool(annotations=READ_ONLY)
async def search_posts(query: str) -> list[dict]:
    """Search posts whose title or content contains the query (case-insensitive)."""
    return [_summary(p) for p in await _api("GET", "/posts", params={"q": query})]


@mcp.tool(annotations=READ_ONLY)
async def get_post(post_id: int) -> dict:
    """Get one post, including its full content."""
    return await _api("GET", f"/posts/{post_id}")


@mcp.tool()
async def create_post(title: str, content: str, author: str = "anonymous") -> dict:
    """Create a new post as a draft. Content is Markdown."""
    return await _api("POST", "/posts", json={"title": title, "content": content, "author": author})


@mcp.tool(annotations=ToolAnnotations(idempotentHint=True))
async def update_post(
    post_id: int,
    title: str | None = None,
    content: str | None = None,
    author: str | None = None,
) -> dict:
    """Update fields of an existing post. Only the fields you pass are changed."""
    body = {k: v for k, v in {"title": title, "content": content, "author": author}.items() if v is not None}
    return await _api("PATCH", f"/posts/{post_id}", json=body)


@mcp.tool(annotations=ToolAnnotations(idempotentHint=True))
async def publish_post(post_id: int) -> dict:
    """Publish a draft post so it appears on the public blog."""
    return await _api("POST", f"/posts/{post_id}/publish")


@mcp.tool(annotations=ToolAnnotations(idempotentHint=True))
async def unpublish_post(post_id: int) -> dict:
    """Move a published post back to draft."""
    return await _api("POST", f"/posts/{post_id}/unpublish")


@mcp.tool(annotations=ToolAnnotations(destructiveHint=True))
async def delete_post(post_id: int) -> str:
    """Permanently delete a post. This cannot be undone."""
    await _api("DELETE", f"/posts/{post_id}")
    return f"Deleted post {post_id}"


# ------------------------------------------------------------ resources


@mcp.resource("blog://posts", name="all_posts", mime_type="application/json")
async def all_posts_resource() -> str:
    """Summary of every post on the blog."""
    return json.dumps([_summary(p) for p in await _api("GET", "/posts")], indent=2)


@mcp.resource("blog://posts/{post_id}", name="post", mime_type="text/markdown")
async def post_resource(post_id: str) -> str:
    """A single post rendered as Markdown."""
    p = await _api("GET", f"/posts/{post_id}")
    return f"# {p['title']}\n\n_by {p['author']} · {p['status']}_\n\n{p['content']}"


# -------------------------------------------------------------- prompts


@mcp.prompt()
def draft_blog_post(topic: str, tone: str = "friendly") -> str:
    """Ask the assistant to draft and save a new post on a topic."""
    return (
        f"Write a blog post about: {topic}. Use a {tone} tone, Markdown formatting, "
        "and 300-500 words. Save it as a draft with create_post, then show me the title and id."
    )


@mcp.prompt()
def review_post(post_id: int) -> str:
    """Ask the assistant to review an existing post and suggest edits."""
    return (
        f"Read post {post_id} with get_post. Review it for clarity, structure and typos. "
        "List concrete suggestions; do not change the post unless I ask."
    )


def _transport_security() -> TransportSecuritySettings | None:
    """DNS-rebinding protection: only accept requests whose Host header is listed.

    On 127.0.0.1 the SDK enables this for localhost automatically. In Docker the
    server binds 0.0.0.0, so set MCP_ALLOWED_HOSTS (e.g. "blog-mcp:*") to keep it on.
    """
    hosts = [h.strip() for h in os.getenv("MCP_ALLOWED_HOSTS", "").split(",") if h.strip()]
    if not hosts:
        return None
    return TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=hosts, allowed_origins=[])


if __name__ == "__main__":
    mcp.run(
        "streamable-http",
        host=os.getenv("MCP_HOST", "127.0.0.1"),
        port=int(os.getenv("MCP_PORT", "8101")),
        transport_security=_transport_security(),
    )
