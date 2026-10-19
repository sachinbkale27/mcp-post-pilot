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

import base64
import json
import os
from typing import Literal

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp_types import ToolAnnotations

def _load_settings() -> None:
    """On AWS, read settings such as OPENAI_API_KEY from Parameter Store (SSM_PARAMETER_PATH)."""
    path = os.getenv("SSM_PARAMETER_PATH")
    if not path:
        return
    import boto3

    for page in boto3.client("ssm").get_paginator("get_parameters_by_path").paginate(Path=path, WithDecryption=True):
        for param in page["Parameters"]:
            os.environ.setdefault(param["Name"].rsplit("/", 1)[-1], param["Value"])


_load_settings()

BLOG_API_URL = os.getenv("BLOG_API_URL", "http://127.0.0.1:8100")
# Image generation (generate_image). OPENAI_IMAGE_API_URL only exists for testing against a stub.
IMAGE_API_URL = (os.getenv("OPENAI_IMAGE_API_URL") or "https://api.openai.com/v1").rstrip("/")
# gpt-image-2.5-flare: OpenAI's fast everyday model (gpt-image-2.5-sunburst is tuned for editing).
IMAGE_MODEL = os.getenv("OPENAI_IMAGE_MODEL") or "gpt-image-2.5-flare"
IMAGE_QUALITY = os.getenv("OPENAI_IMAGE_QUALITY") or "medium"
# On AWS the blog API only accepts requests carrying the shared origin secret.
ORIGIN_SECRET = os.getenv("ORIGIN_SECRET")

mcp = MCPServer(
    name="blog",
    instructions=(
        "Tools for managing a blog. Posts start as drafts; publish_post makes "
        "them public. Use list_posts or search_posts to find post ids. Content is "
        "Markdown; images are referenced by URL (![alt text](/media/...)). Use image "
        "URLs exactly as supplied (a path starting with /media/, no scheme or host). "
        "generate_image creates an AI illustration and returns such a URL."
    ),
)


class BlogAPIError(ToolError):
    """ToolError messages are shown to the model; any other exception is masked."""


async def _api(method: str, path: str, **kwargs) -> dict | list | None:
    headers = {"x-origin-secret": ORIGIN_SECRET} if ORIGIN_SECRET else {}
    async with httpx.AsyncClient(base_url=BLOG_API_URL, headers=headers, timeout=10) as client:
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
async def create_post(
    title: str,
    content: str,
    author: str = "anonymous",
    cover_image_url: str | None = None,
) -> dict:
    """Create a new post as a draft. Content is Markdown.

    Args:
        cover_image_url: Image shown on the post card and automatically at the top of the
            article, e.g. /media/abc.webp. Don't repeat the cover image inside the content.
            Other images go in the content as ![alt text](url).
    """
    body = {"title": title, "content": content, "author": author, "cover_image_url": cover_image_url}
    return await _api("POST", "/posts", json=body)


@mcp.tool(annotations=ToolAnnotations(idempotentHint=True))
async def update_post(
    post_id: int,
    title: str | None = None,
    content: str | None = None,
    author: str | None = None,
    cover_image_url: str | None = None,
) -> dict:
    """Update fields of an existing post. Only the fields you pass are changed.

    Args:
        cover_image_url: New cover image URL (one the user provided). Pass "" to remove the cover.
    """
    fields = {"title": title, "content": content, "author": author, "cover_image_url": cover_image_url}
    body = {k: v for k, v in fields.items() if v is not None}
    if body.get("cover_image_url") == "":
        body["cover_image_url"] = None
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


@mcp.tool(annotations=ToolAnnotations(openWorldHint=True))
async def generate_image(
    prompt: str,
    size: Literal["1536x1024", "1024x1024", "1024x1536"] = "1536x1024",
) -> dict:
    """Generate an illustration with an AI image model and store it on the blog.

    Returns {"url": "/media/..."}: use it as cover_image_url and/or inline as ![alt text](url).
    Each call costs money and can take up to a minute, so make one image per request unless the
    user asks for more. Describe subject, composition, style and mood; avoid asking for text in
    the image.

    Args:
        prompt: What the image should show.
        size: 1536x1024 (landscape, best for covers), 1024x1024 (square) or 1024x1536 (portrait).
    """
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise BlogAPIError("Image generation isn't configured: the MCP server has no OPENAI_API_KEY")

    # GPT Image models always return base64 image data.
    body = {"model": IMAGE_MODEL, "prompt": prompt, "n": 1, "size": size, "quality": IMAGE_QUALITY}

    async with httpx.AsyncClient(timeout=180) as client:
        resp = await client.post(f"{IMAGE_API_URL}/images/generations", headers={"Authorization": f"Bearer {key}"}, json=body)
    if resp.status_code >= 400:
        try:
            error = resp.json().get("error") or {}
        except ValueError:
            error = {}
        message = error.get("message", resp.text)
        # 403 model_not_found: the project may not use the model; 400 param=model: no such model.
        if resp.status_code in (403, 404) or error.get("code") == "model_not_found" or error.get("param") == "model":
            raise BlogAPIError(
                f"The image model '{IMAGE_MODEL}' isn't available to this OpenAI project. "
                "Enable it in the OpenAI dashboard (Settings > Limits / model access) to generate images."
            )
        raise BlogAPIError(f"Image generation failed (HTTP {resp.status_code}): {message}")

    image = base64.b64decode(resp.json()["data"][0]["b64_json"])
    content_type = "image/png"
    if image[:3] == b"\xff\xd8\xff":
        content_type = "image/jpeg"
    elif image[:4] == b"RIFF" and image[8:12] == b"WEBP":
        content_type = "image/webp"
    stored = await _api("POST", "/images", content=image, headers={"Content-Type": content_type})
    return {"url": stored["url"], "size": size, "model": IMAGE_MODEL}


# ------------------------------------------------------------ resources


@mcp.resource("blog://posts", name="all_posts", mime_type="application/json")
async def all_posts_resource() -> str:
    """Summary of every post on the blog."""
    return json.dumps([_summary(p) for p in await _api("GET", "/posts")], indent=2)


@mcp.resource("blog://posts/{post_id}", name="post", mime_type="text/markdown")
async def post_resource(post_id: str) -> str:
    """A single post rendered as Markdown."""
    p = await _api("GET", f"/posts/{post_id}")
    cover = f"![cover]({p['cover_image_url']})\n\n" if p.get("cover_image_url") else ""
    return f"# {p['title']}\n\n_by {p['author']} · {p['status']}_\n\n{cover}{p['content']}"


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
    import uvicorn

    from origin import OriginSecretMiddleware

    host = os.getenv("MCP_HOST", "127.0.0.1")
    app = mcp.streamable_http_app(
        host=host,
        transport_security=_transport_security(),
        # On Lambda each request may hit a different instance, so keep no session state
        # and answer with plain JSON instead of an SSE stream.
        stateless_http=os.getenv("MCP_STATELESS") == "1",
        json_response=os.getenv("MCP_STATELESS") == "1",
    )
    uvicorn.run(
        OriginSecretMiddleware(app, ORIGIN_SECRET) if ORIGIN_SECRET else app,
        host=host,
        port=int(os.getenv("MCP_PORT", "8101")),
    )
