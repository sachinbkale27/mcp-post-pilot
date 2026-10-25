"""Chat API for the multi-agent supervisor. Streams agent events to the UI as Server-Sent Events (SSE)."""

import os
import uuid
from collections.abc import AsyncIterable
from typing import Literal

import openai
from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel, Field, field_validator

from .agent import list_agents, reset_thread, run_turn
from .diagnose import run_diagnosis
from .image_url import ImageUrlError, download_image
from .labeling import LabelingUnavailable, run_labeling, warm_up
from .pathology import PathologyError, run_pathology
from .handoff import HandoffError, ResultsHandoff, hand_off
from .drugs_search import run_drugs
from .trials_search import TrialsUnavailable, run_trials
from .view_agents import AgentUnavailable
from .origin import OriginSecretMiddleware

app = FastAPI(title="MCP Agent Chat")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5174"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["x-image-name"],  # /fetch-image's file name, read by the UI
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


MAX_LABEL = 80  # medical terms run long, e.g. "melanophages (pigment-laden macrophages)"


class LabelRequest(BaseModel):
    image: ChatImage
    instructions: str = Field(min_length=3, max_length=2000)
    labels: list[str] = Field(default_factory=list, max_length=20)
    category: str = Field(default="agent-chat", max_length=60)
    grid_step: int | None = Field(default=None, ge=10, le=1000)  # the model's copy has a pixel grid this far apart
    model: Literal["sam", "medsam"] = "sam"  # Segment Anything, or MedSAM for medical images
    image_id: str | None = Field(default=None, pattern=r"^[0-9a-f-]{36}$")  # add to this Image Label image

    @field_validator("labels")
    @classmethod
    def _clean_labels(cls, value: list[str]) -> list[str]:
        labels = list(dict.fromkeys(label.strip() for label in value if label.strip()))
        for label in labels:
            if len(label) > MAX_LABEL:
                raise ValueError(f"label names must be at most {MAX_LABEL} characters: {label!r} is {len(label)}")
        return labels


class PathologyRequest(BaseModel):
    image: ChatImage
    action: Literal["nuclei", "quality", "normalize", "cells"]
    image_id: str | None = Field(default=None, pattern=r"^[0-9a-f-]{36}$")  # already in Image Label: don't upload again
    category: str = Field(default="agent-chat", max_length=60)


class TrialsRequest(BaseModel):
    question: str = Field(min_length=5, max_length=1500)  # the search, in words (the view builds it from its form)
    person: str = Field(default="", max_length=1500)  # what is known about the person, for the eligibility screen


class DrugsRequest(BaseModel):
    question: str = Field(min_length=5, max_length=1500)  # the question, in words (the view builds it from its form)


class ImageUrlRequest(BaseModel):
    url: str = Field(min_length=8, max_length=2000)


@app.post("/fetch-image")
async def fetch_image(req: ImageUrlRequest) -> Response:
    """Download an image from a public web address and return its bytes (the file name is in X-Image-Name),
    so the UI can treat it like a file the user picked."""
    try:
        data, media_type, name = await download_image(req.url.strip())
    except ImageUrlError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc))
    return Response(data, media_type=media_type, headers={"x-image-name": name, "cache-control": "no-store"})


@app.get("/agents")
async def agents():
    """Every specialist agent and what its MCP server offers; an offline server is reported, not raised."""
    try:
        return await list_agents()
    except Exception as exc:  # e.g. a broken agents.json
        raise HTTPException(status_code=500, detail=f"Cannot load agents: {exc}")


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


class WarmupRequest(BaseModel):
    model: Literal["sam", "medsam"] = "sam"


class DiagnoseRequest(BaseModel):
    image: ChatImage
    context: str = Field(default="", max_length=2000)


@app.post("/diagnose", response_class=EventSourceResponse)
async def diagnose(req: DiagnoseRequest) -> AsyncIterable[ServerSentEvent]:
    """Stream an AI interpretation of one image (research and education, not a diagnosis)."""
    try:
        async for event in run_diagnosis(req.image.model_dump(), req.context):
            yield _sse(event)
    except Exception as exc:
        yield _sse({"type": "error", "message": _error_message(exc)})
    yield _sse({"type": "done"})


@app.post("/label/warmup")
async def label_warmup(req: WarmupRequest):
    """Start loading the segmentation model, so it is ready by the time someone labels an image."""
    return {"warming": await warm_up(req.model)}


@app.post("/label", response_class=EventSourceResponse)
async def label(req: LabelRequest) -> AsyncIterable[ServerSentEvent]:
    """Upload one image to Image Label, have the Image Annotation Agent annotate it, and stream the progress and
    a final label_result event (saved annotations and COCO / YOLO exports)."""
    try:
        async for event in run_labeling(
            req.image.model_dump(),
            req.instructions,
            req.labels,
            req.category.strip() or "agent-chat",
            req.grid_step,
            req.model,
            req.image_id,
        ):
            yield _sse(event)
    except LabelingUnavailable as exc:
        yield _sse({"type": "error", "message": str(exc)})
    except Exception as exc:
        yield _sse({"type": "error", "message": _error_message(exc)})
    yield _sse({"type": "done"})


@app.post("/handoff")
async def handoff(results: ResultsHandoff):
    """Ask AI: hand an image analysis to the genetics assistant; returns the address of a chat about it."""
    try:
        return {"url": await hand_off(results)}
    except HandoffError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not reach the genetics assistant ({type(exc).__name__})")


@app.post("/label/pathology", response_class=EventSourceResponse)
async def label_pathology(req: PathologyRequest) -> AsyncIterable[ServerSentEvent]:
    """Run one histopathology tool (nuclei outlines, quality check or stain normalization) on an image and
    stream the tool calls and the result."""
    try:
        async for event in run_pathology(req.image.model_dump(), req.action, req.image_id, req.category.strip() or "agent-chat"):
            yield _sse(event)
    except LabelingUnavailable as exc:
        yield _sse({"type": "error", "message": str(exc)})
    except Exception as exc:
        yield _sse({"type": "error", "message": _error_message(exc)})
    yield _sse({"type": "done"})


@app.post("/trials", response_class=EventSourceResponse)
async def trials(req: TrialsRequest) -> AsyncIterable[ServerSentEvent]:
    """Run the Clinical Trials agent on one search and stream its progress; the trial cards are in the
    submit_trials result, and a final trials_report event has the agent's report."""
    try:
        async for event in run_trials(req.question.strip(), req.person.strip()):
            yield _sse(event)
    except TrialsUnavailable as exc:
        yield _sse({"type": "error", "message": str(exc)})
    except Exception as exc:
        yield _sse({"type": "error", "message": _error_message(exc)})
    yield _sse({"type": "done"})


@app.post("/drugs", response_class=EventSourceResponse)
async def drugs(req: DrugsRequest) -> AsyncIterable[ServerSentEvent]:
    """Run the Drug Information agent on one question and stream its progress; a final drug_report event has
    its answer."""
    try:
        async for event in run_drugs(req.question.strip()):
            yield _sse(event)
    except AgentUnavailable as exc:
        yield _sse({"type": "error", "message": str(exc)})
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
    if isinstance(exc, PathologyError):
        return str(exc)
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
