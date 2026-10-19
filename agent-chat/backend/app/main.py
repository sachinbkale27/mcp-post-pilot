"""Chat API for the MCP agent. Streams agent events to the UI as Server-Sent Events (SSE)."""

import os
import uuid
from collections.abc import AsyncIterable

import openai
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel, Field, field_validator

from .agent import list_mcp_capabilities, reset_thread, run_turn
from .origin import OriginSecretMiddleware

app = FastAPI(title="MCP Agent Chat")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5174"],
    allow_methods=["*"],
    allow_headers=["*"],
)
# On AWS only CloudFront knows this secret; direct calls to the Lambda URL are rejected.
if secret := os.getenv("ORIGIN_SECRET"):
    app.add_middleware(OriginSecretMiddleware, secret=secret)


MAX_IMAGE_DATA_URL = 2_800_000  # ~2 MB image; the UI resizes before sending


class ChatImage(BaseModel):
    url: str = Field(pattern=r"^/media/[\w.-]+$")  # where the blog serves the uploaded image
    data_url: str = Field(max_length=MAX_IMAGE_DATA_URL)  # small copy for the model to look at
    name: str | None = Field(default=None, max_length=200)

    @field_validator("data_url")
    @classmethod
    def _is_image(cls, value: str) -> str:
        if not value.startswith(("data:image/jpeg;base64,", "data:image/png;base64,", "data:image/webp;base64,", "data:image/gif;base64,")):
            raise ValueError("data_url must be a base64 JPEG, PNG, WebP or GIF data URL")
        return value


class ChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None
    images: list[ChatImage] = Field(default_factory=list, max_length=4)


@app.get("/mcp/info")
async def mcp_info():
    try:
        return await list_mcp_capabilities()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Cannot reach MCP server: {exc}")


@app.post("/chat", response_class=EventSourceResponse)
async def chat(req: ChatRequest) -> AsyncIterable[ServerSentEvent]:
    """Stream one chat turn as SSE. Each event's name is its type, e.g.

        event: token
        data: {"text": "Hello"}

    POST (not GET) because the message goes in the body, so the browser reads the
    stream with fetch() rather than EventSource, which only supports GET.
    """
    # The conversation id keys the stored history and groups turns into one LangSmith thread.
    conversation_id = req.conversation_id or str(uuid.uuid4())
    yield _sse({"type": "conversation", "id": conversation_id})
    try:
        images = [img.model_dump() for img in req.images]
        async for event in run_turn(conversation_id, req.message, images):
            yield _sse(event)
    except Exception as exc:
        yield _sse({"type": "error", "message": _error_message(exc)})
    yield _sse({"type": "done"})


@app.delete("/chat/{conversation_id}")
async def reset(conversation_id: str):
    reset_thread(conversation_id)
    return {"ok": True}


def _error_message(exc: BaseException) -> str:
    # The MCP client runs inside an anyio TaskGroup, which wraps errors in ExceptionGroups.
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    if isinstance(exc, openai.AuthenticationError):
        return "OpenAI authentication failed - set OPENAI_API_KEY in agent-chat/.env."
    if isinstance(exc, openai.RateLimitError):
        return "Rate limited by the OpenAI API - try again shortly."
    if isinstance(exc, openai.APIStatusError):
        return f"OpenAI API error {exc.status_code}: {exc.message}"
    if isinstance(exc, openai.APIConnectionError):
        return "Could not connect to the OpenAI API."
    return f"{type(exc).__name__}: {exc}"


def _sse(event: dict) -> ServerSentEvent:
    event_type, payload = event["type"], {k: v for k, v in event.items() if k != "type"}
    return ServerSentEvent(event=event_type, data=payload)
