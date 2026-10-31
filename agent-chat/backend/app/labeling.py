"""Label one image with the Image Annotation Agent, for the chat UI's "Label images" view.

    upload_image_from_url  (called here)    -> the image is in Image Label, with its size
    find_regions           (called here)    -> the objects Segment Anything finds by itself, numbered on a copy
    Image Annotation Agent          (LLM + vision)  -> chooses regions (or rough boxes) -> segment_objects traces them
    get_image, export_annotations (here)    -> the saved shapes and COCO / YOLO exports for the UI

Only the annotating is left to the model; uploading and reading the result back are done in code, so the
UI always gets the image id, the saved annotations and the exports. Events use the chat's SSE format
(agent_start, tool_call, tool_result, agent_end) plus one label_result.
"""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

from .agent import _model
from .specialists import AgentSpec, load_agents
from .specialists.runner import call_mcp_tool, connect, run_specialist

LABEL_AGENT = "labels"

TASK = """Annotate Image Label image {image_id} ({width} x {height} pixels). It is already uploaded and is the
image attached here: do not upload it again. It may already have annotations (for example nuclei from
detect_nuclei): keep them, and only add new ones.

What to label: {instructions}
{labels}{grid}{regions}
Look at the image, then outline every object to label with segment_objects on image {image_id} (model
"{model}", up to 20 objects per call): give each a box that contains the whole object, a little loose rather
than tight; the segmentation model traces the exact edges (it is already warming up: don't call warm_up).
If segment_objects fails, or fails for some objects, draw
those yourself with add_annotations (polygons, confidence "low") and say so.

Label names: unless label names are given above, name each object with a specific, descriptive term for
what it is, never the wording of the request: e.g. "car", "pedestrian", or for medical images standard
morphological terms such as "pigment-laden macrophage", "atypical cell cluster", "necrosis", "stroma",
"lymphocytic infiltrate". Reuse a name for objects of the same kind. Don't use diagnoses as labels.

Report what you labeled, the scores, and anything you were unsure about.{medical}"""

MEDICAL = """ For this medical image, end the report
with a short "Possible interpretation" section: the pattern you see and the most likely explanations,
stated as hypotheses, with what would confirm them (e.g. special stains, immunohistochemistry). It is for
research and dataset building, not a diagnosis."""


GRID = """The attached copy has a yellow grid drawn on it, with lines every {step} pixels labelled with their
pixel values along the top and left edges. Use the grid to read off coordinates: for each object, find the
grid cell of each edge, then estimate within the cell. The grid is not part of the saved image.
"""


REGIONS = """
Segment Anything has already found the distinct regions in the image by itself: the second attached copy
has them outlined in cyan and numbered (the number is at each outline's top-left corner). Their exact boxes
[x, y, width, height]:
{listing}
Decide which numbered regions are objects to label, and give segment_objects their boxes exactly as listed:
don't estimate boxes for those. Where one region lies inside another (e.g. a gland's lumen inside the whole
gland), choose the one that matches the whole object. Skip regions that are background, artefacts or other
structures. Only for an object no region matches, read a box off the grid yourself. List the region numbers
you used in your report.
"""


def _listing(regions: list[dict[str, Any]]) -> str:
    return "\n".join(f"{r['region']}: {r['box']}" for r in regions)


class LabelingUnavailable(RuntimeError):
    pass


def labeling_agent() -> AgentSpec:
    spec = next((s for s in load_agents() if s.name == LABEL_AGENT), None)
    if spec is None:
        raise LabelingUnavailable("The Image Annotation Agent isn't configured on this server (LABELS_MCP_URL is not set).")
    return spec


async def warm_up(model: str = "sam") -> bool:
    """Ask the label server to start loading the segmentation model (it takes a minute or two after a
    quiet spell). Best effort: returns whether the request was accepted."""
    try:
        spec = labeling_agent()
        async with asyncio.timeout(15), connect(spec) as mcp:
            (_, is_error), _ = await asyncio.gather(
                call_mcp_tool(mcp, "warm_up", {"model": model}),
                # The histology tools' nuclei model too: its first run in a new container is slow
                call_mcp_tool(mcp, "warm_up", {"model": "nuclei"}),
            )
        return not is_error
    except Exception:  # an older label server without the tool, or it's offline: labeling still works
        return False


async def share_link(image_id: str) -> str:
    """A 7-day link that opens the image and its saved annotations in the Image Label app, in anyone's browser."""
    spec = labeling_agent()
    async with connect(spec) as mcp:
        content, is_error = await call_mcp_tool(mcp, "share_image", {"image_id": image_id})
    if is_error:
        raise LabelingUnavailable(f"The image couldn't be shared: {content}"[:300])
    return _decode(content)["url"]


async def find_regions(mcp, image_id: str) -> tuple[list[dict[str, Any]], str]:
    """The regions Segment Anything finds by itself, and a data URL of the image with them numbered."""
    result = await mcp.call_tool("find_regions", {"image_id": image_id})
    info = json.loads(next(c.text for c in result.content if c.type == "text"))
    picture = next(c for c in result.content if c.type == "image")
    return info["regions"], f"data:{picture.mime_type};base64,{picture.data}"


def _decode(content: str) -> Any:
    try:
        value = json.loads(content)
    except ValueError:
        return content
    return value.get("result", value) if isinstance(value, dict) and set(value) == {"result"} else value


async def run_labeling(
    image: dict[str, str],
    instructions: str,
    labels: list[str],
    category: str,
    grid_step: int | None = None,
    model: str = "sam",
    image_id: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Yield UI events while the image is uploaded, annotated and exported. With image_id (an image already
    in Image Label, e.g. from an earlier run or a histology tool), the new annotations are added to it."""
    spec = labeling_agent()
    queue: asyncio.Queue = asyncio.Queue()
    delegation = f"label-{uuid.uuid4()}"
    emit = queue.put_nowait

    async def tool(mcp, name: str, arguments: dict[str, Any]) -> Any:
        """Call a label-server tool from code, shown in the UI like the agent's own calls."""
        call_id = f"{name}-{uuid.uuid4()}"
        emit({"type": "tool_call", "id": call_id, "name": name, "input": arguments, "agent": spec.name, "delegation": delegation})
        content, is_error = await call_mcp_tool(mcp, name, arguments)
        output = _decode(content)
        emit({"type": "tool_result", "id": call_id, "name": name, "output": output, "is_error": is_error, "agent": spec.name, "delegation": delegation})
        if is_error:
            raise RuntimeError(f"{name} failed: {content}"[:300])
        return output

    async def regions_of(mcp, image_id: str) -> tuple[list[dict[str, Any]], str | None]:
        """find_regions, shown in the UI like the other calls. Best effort: without regions the agent places
        boxes itself, as before."""
        call_id = f"find_regions-{uuid.uuid4()}"
        arguments = {"image_id": image_id}
        emit({"type": "tool_call", "id": call_id, "name": "find_regions", "input": arguments, "agent": spec.name, "delegation": delegation})
        try:
            regions, marked = await find_regions(mcp, image_id)
        except Exception as exc:  # an older label server, or the model is busy
            print(f"find_regions failed: {exc!r}")
            emit({"type": "tool_result", "id": call_id, "name": "find_regions", "output": f"No regions: {exc}"[:300], "is_error": True, "agent": spec.name, "delegation": delegation})
            return [], None
        emit({"type": "tool_result", "id": call_id, "name": "find_regions", "output": {"regions": regions}, "is_error": False, "agent": spec.name, "delegation": delegation})
        return regions, marked if regions else None

    async def produce() -> None:
        url = spec.attachment_base_url + image["url"] if image["url"].startswith("/") else image["url"]
        task = "Upload the image, annotate it and export the result"
        emit({"type": "agent_start", "id": delegation, "agent": spec.name, "title": spec.title, "task": task})
        is_error = False
        try:
            # Start loading the segmentation models now: SAM finds the regions, then traces (or MedSAM does)
            warming = asyncio.gather(*(warm_up(m) for m in dict.fromkeys(["sam", model])))
            async with connect(spec) as mcp:
                if image_id:
                    uploaded = await tool(mcp, "get_image", {"image_id": image_id})
                else:
                    uploaded = await tool(
                        mcp, "upload_image_from_url", {"url": url, "name": image.get("name") or "image", "category": category}
                    )
                await warming
                target = uploaded["imageId"]
                regions, marked = await regions_of(mcp, target)
            pictures = [image] + ([{**image, "data_url": marked, "name": "the regions, numbered"}] if marked else [])
            label_line = f"Use exactly these label names: {', '.join(labels)}.\n" if labels else ""
            report = await run_specialist(
                spec,
                model=_model(disable_streaming=True),
                task=TASK.format(
                    image_id=target,
                    width=uploaded.get("width"),
                    height=uploaded.get("height"),
                    instructions=instructions,
                    labels=label_line,
                    grid=GRID.format(step=grid_step) if grid_step else "",
                    regions=REGIONS.format(listing=_listing(regions)) if marked else "",
                    model=model,
                    medical=MEDICAL if model == "medsam" else "",
                ),
                user_text=instructions,
                images=pictures,
                delegation_id=delegation,
                emit=emit,
            )
            async with connect(spec) as mcp:
                saved = await tool(mcp, "get_image", {"image_id": target})
                coco, yolo, qupath = await asyncio.gather(
                    *(tool(mcp, "export_annotations", {"image_id": target, "format": f}) for f in ("coco", "yolo", "qupath"))
                )
            emit(
                {
                    "type": "label_result",
                    "image_id": target,
                    "width": saved.get("width"),
                    "height": saved.get("height"),
                    "annotations": saved.get("annotations") or [],
                    "report": report,
                    "exports": {"coco": coco, "yolo": yolo, "qupath": qupath},
                }
            )
        except Exception:
            is_error = True
            raise
        finally:
            emit({"type": "agent_end", "id": delegation, "agent": spec.name, "is_error": is_error})

    async def run() -> None:
        try:
            await produce()
            emit(None)
        except BaseException as exc:
            emit(exc)
            raise

    task = asyncio.create_task(run())
    try:
        while (item := await queue.get()) is not None:
            if isinstance(item, BaseException):
                raise item
            yield item
    finally:
        if not task.done():
            task.cancel()  # the client went away (Stop)
        await asyncio.gather(task, return_exceptions=True)
