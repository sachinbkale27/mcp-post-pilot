"""Chat API for the multi-agent supervisor. Streams agent events to the UI as Server-Sent Events (SSE)."""

import os
import re
import time
import uuid
from collections.abc import AsyncIterable
from typing import Literal

import openai
from fastapi import FastAPI, Header, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel, Field, field_validator

from . import admin, analytics
from .agent import list_agents, reset_thread, run_turn
from .diagnose import run_diagnosis
from .image_url import ImageUrlError, download_image
from .labeling import LabelingUnavailable, run_labeling, share_link, warm_up
from .pathology import PathologyError, run_pathology
from .handoff import HandoffError, ResultsHandoff, hand_off
from .drugs_search import run_drugs
from .security_plan import run_security
from .trials_search import TrialsUnavailable, run_trials
from .view_agents import AgentUnavailable
from .origin import OriginSecretMiddleware
from .viewer import ViewerMiddleware

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
app.add_middleware(ViewerMiddleware)  # the visitor's place, for Image Label's usage counts


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
    instructions: str = Field(default="", max_length=2000)  # empty: outline everything distinct
    labels: list[str] = Field(default_factory=list, max_length=20)
    category: str = Field(default="agent-chat", max_length=60)
    grid_step: int | None = Field(default=None, ge=10, le=1000)  # the model's copy has a pixel grid this far apart
    model: Literal["sam", "medsam"] = "sam"  # Segment Anything, or MedSAM for medical images
    image_id: str | None = Field(default=None, pattern=r"^[0-9a-f-]{36}$")  # add to this Image Label image
    history: str = Field(default="", max_length=1000)  # the specimen's clinical history (optional)
    other_info: str = Field(default="", max_length=1000)

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


class SecurityRequest(BaseModel):
    question: str = Field(min_length=10, max_length=3000)  # the request, in words (the view builds it from its form)
    token: str = Field(default="", max_length=8000, pattern=r"^[A-Za-z0-9_\-.= ]*$")  # a test JWT, optional


class ImageUrlRequest(BaseModel):
    url: str = Field(min_length=8, max_length=2000)


@app.post("/fetch-image")
async def fetch_image(req: ImageUrlRequest) -> Response:
    """Download an image from a public web address and return its bytes (the file name is in X-Image-Name),
    so the UI can treat it like a file the user picked."""
    try:
        data, media_type, name = await download_image(req.url.strip())
    except ImageUrlError as exc:
        analytics.record("fetch_image", {"ok": False, "status": exc.status})
        raise HTTPException(status_code=exc.status, detail=str(exc))
    analytics.record("fetch_image", {"ok": True})
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
        turn = run_turn(conversation_id, req.message, images)
        async for event in analytics.tracked("chat_turn", turn, images=len(images), followup=req.conversation_id is not None):
            yield _sse(event)
    except Exception as exc:
        yield _sse({"type": "error", "message": _error_message(exc)})
    yield _sse({"type": "done"})


class ShareRequest(BaseModel):
    image_id: str = Field(pattern=r"^[0-9a-f-]{36}$")


class WarmupRequest(BaseModel):
    model: Literal["sam", "medsam"] = "sam"


class DiagnoseRequest(BaseModel):
    image: ChatImage
    context: str = Field(default="", max_length=2000)
    history: str = Field(default="", max_length=1000)  # about the specimen: site, age, duration, appearance
    other_info: str = Field(default="", max_length=1000)  # anything else: prior diagnoses, the clinical question


@app.post("/diagnose", response_class=EventSourceResponse)
async def diagnose(req: DiagnoseRequest) -> AsyncIterable[ServerSentEvent]:
    """Stream an AI interpretation of one image (research and education, not a diagnosis)."""
    try:
        run = run_diagnosis(req.image.model_dump(), req.context, req.history, req.other_info)
        async for event in analytics.tracked("diagnose", run, history=bool(req.history.strip())):
            yield _sse(event)
    except Exception as exc:
        yield _sse({"type": "error", "message": _error_message(exc)})
    yield _sse({"type": "done"})


@app.post("/label/share")
async def label_share(req: ShareRequest):
    """A link that opens the image and its annotations in Image Label, where anyone can edit them further."""
    try:
        url = await share_link(req.image_id)
    except LabelingUnavailable as exc:
        analytics.record("share", {"ok": False})
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    analytics.record("share", {"ok": True})
    return {"url": url}


@app.post("/label/warmup")
async def label_warmup(req: WarmupRequest):
    """Start loading the segmentation model, so it is ready by the time someone labels an image."""
    return {"warming": await warm_up(req.model)}


@app.post("/label", response_class=EventSourceResponse)
async def label(req: LabelRequest) -> AsyncIterable[ServerSentEvent]:
    """Upload one image to Image Label, have the Image Annotation Agent annotate it, and stream the progress and
    a final label_result event (saved annotations and COCO / YOLO exports)."""
    try:
        run = run_labeling(
            req.image.model_dump(),
            req.instructions,
            req.labels,
            req.category.strip() or "agent-chat",
            req.grid_step,
            req.model,
            req.image_id,
            req.history,
            req.other_info,
        )
        props = {"model": req.model, "labels": len(req.labels), "instructions": bool(req.instructions.strip())}
        async for event in analytics.tracked("label", run, **props):
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
        url = await hand_off(results)
    except HandoffError as exc:
        analytics.record("handoff", {"ok": False})
        raise HTTPException(status_code=502, detail=str(exc))
    except Exception as exc:
        analytics.record("handoff", {"ok": False})
        raise HTTPException(status_code=502, detail=f"Could not reach the genetics assistant ({type(exc).__name__})")
    analytics.record("handoff", {"ok": True, "findings": len(results.findings)})
    return {"url": url}


@app.post("/label/pathology", response_class=EventSourceResponse)
async def label_pathology(req: PathologyRequest) -> AsyncIterable[ServerSentEvent]:
    """Run one histopathology tool (nuclei outlines, quality check or stain normalization) on an image and
    stream the tool calls and the result."""
    try:
        run = run_pathology(req.image.model_dump(), req.action, req.image_id, req.category.strip() or "agent-chat")
        async for event in analytics.tracked("pathology", run, action=req.action):
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
        run = run_trials(req.question.strip(), req.person.strip())
        async for event in analytics.tracked("trials", run, profile=bool(req.person.strip())):
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
        async for event in analytics.tracked("drugs", run_drugs(req.question.strip())):
            yield _sse(event)
    except AgentUnavailable as exc:
        yield _sse({"type": "error", "message": str(exc)})
    except Exception as exc:
        yield _sse({"type": "error", "message": _error_message(exc)})
    yield _sse({"type": "done"})


@app.post("/security", response_class=EventSourceResponse)
async def security(req: SecurityRequest) -> AsyncIterable[ServerSentEvent]:
    """Run the Auth Security agent on one request and stream its progress; a final security_report event has
    its plan."""
    try:
        run = run_security(req.question.strip(), req.token.strip().removeprefix("Bearer ").strip())
        async for event in analytics.tracked("security", run, token=bool(req.token.strip())):
            yield _sse(event)
    except AgentUnavailable as exc:
        yield _sse({"type": "error", "message": str(exc)})
    except Exception as exc:
        yield _sse({"type": "error", "message": _error_message(exc)})
    yield _sse({"type": "done"})


PROP_KEY = re.compile(r"^[a-z_]{1,24}$")
PROP_VALUE = re.compile(r"^[\w .:/+#-]{0,60}$")


class ClientEvent(BaseModel):
    """One event from the browser (views and actions only it sees). Small and strict: anyone can send these."""

    name: Literal["view", "upload", "download"]
    props: dict[str, str | int | bool] = Field(default_factory=dict, max_length=6)
    session: str = Field(default="", pattern=r"^[0-9a-f]{0,32}$")  # per browser tab, from sessionStorage
    referrer: str = Field(default="", max_length=500)  # the first view's document.referrer; only its host is kept
    utm_source: str = Field(default="", max_length=60, pattern=r"^[\w .-]*$")

    @field_validator("props")
    @classmethod
    def _small_props(cls, value: dict) -> dict:
        for key, item in value.items():
            if not PROP_KEY.match(key):
                raise ValueError(f"bad property name {key!r}")
            if isinstance(item, str) and not PROP_VALUE.match(item):
                raise ValueError(f"bad value for {key!r}")
            if isinstance(item, int) and not isinstance(item, bool) and not 0 <= item <= 1_000_000:
                raise ValueError(f"{key!r} is out of range")
        return value


@app.post("/events", status_code=204)
def track_event(event: ClientEvent) -> Response:
    """Record a view or an action from the browser (best effort: never an error the visitor would notice)."""
    props = dict(event.props)
    if host := analytics.referrer_host(event.referrer):
        props["referrer"] = host
    if event.utm_source:
        props["utm_source"] = event.utm_source.lower()
    analytics.record(event.name, props, source="client", session=event.session)
    return Response(status_code=204)


class AdminLogin(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)


@app.post("/admin/login")
def admin_login(req: AdminLogin, response: Response):
    """Sign in to the admin pages (as Image Label's /admin/login); returns a signed session token."""
    response.headers["cache-control"] = "no-store"
    try:
        session = admin.login(req.username, req.password)
    except admin.AdminUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    if session is None:
        time.sleep(1)  # slows password guessing
        raise HTTPException(status_code=401, detail="Invalid username or password")
    return session


def _admin_session(authorization: str, x_admin_session: str) -> dict:
    """The signed-in admin, or a 401 (no or bad session) / 403 (not an admin), as Image Label's admin routes.
    The browser sends the token in X-Admin-Session, a custom header CloudFront always forwards to the
    Lambda; Authorization: Bearer works too (curl, local)."""
    token = x_admin_session or authorization.removeprefix("Bearer ").strip()
    try:
        session = admin.get_session(token) if token else None
    except admin.AdminUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    if session is None:
        raise HTTPException(status_code=401, detail="Sign in to see this page")
    if not session["admin"]:
        raise HTTPException(status_code=403, detail="Admin access required")
    return session


@app.get("/admin/usage")
def admin_usage(
    response: Response,
    days: int = Query(7, ge=1, le=analytics.MAX_STATS_DAYS),
    internal: bool = False,  # include the owner's own browsers (?internal=1 on the site)
    authorization: str = Header(default=""),
    x_admin_session: str = Header(default=""),
):
    """The site's usage analytics for the admin page (#admin): the only way to read them."""
    _admin_session(authorization, x_admin_session)
    response.headers["cache-control"] = "no-store"
    return analytics.stats(days, internal)


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
