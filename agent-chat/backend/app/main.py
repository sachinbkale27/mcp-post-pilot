"""Chat API for the MCP agent. Streams agent events to the UI as Server-Sent Events (SSE)."""

import uuid
from collections.abc import AsyncIterable

import openai
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel

from .agent import list_mcp_capabilities, reset_thread, run_turn

app = FastAPI(title="MCP Agent Chat")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5174"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None


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
    # The conversation id doubles as the LangGraph thread_id (memory + LangSmith thread).
    conversation_id = req.conversation_id or str(uuid.uuid4())
    yield _sse({"type": "conversation", "id": conversation_id})
    try:
        async for event in run_turn(conversation_id, req.message):
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
