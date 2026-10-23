"""Label one image with the Labeling agent, for the chat UI's "Label images" view.

    upload_image_from_url  (called here)    -> the image is in Image Label, with its size
    Labeling agent          (LLM + vision)  -> add_annotations as the instructions ask
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
image attached here: do not upload it again.

What to label: {instructions}
{labels}{grid}
Look at the image, then add all the annotations in one add_annotations call on image {image_id}, using
polygons (or circles for round objects) so they export as training data, with confidence "low" or "medium".
Report what you labeled and anything you were unsure about."""


GRID = """The attached copy has a yellow grid drawn on it, with lines every {step} pixels labelled with their
pixel values along the top and left edges. Use the grid to read off coordinates: for each object, find the
grid cell of each edge, then estimate within the cell. The grid is not part of the saved image.
"""


class LabelingUnavailable(RuntimeError):
    pass


def labeling_agent() -> AgentSpec:
    spec = next((s for s in load_agents() if s.name == LABEL_AGENT), None)
    if spec is None:
        raise LabelingUnavailable("The Labeling agent isn't configured on this server (LABELS_MCP_URL is not set).")
    return spec


def _decode(content: str) -> Any:
    try:
        value = json.loads(content)
    except ValueError:
        return content
    return value.get("result", value) if isinstance(value, dict) and set(value) == {"result"} else value


async def run_labeling(
    image: dict[str, str], instructions: str, labels: list[str], category: str, grid_step: int | None = None
) -> AsyncIterator[dict[str, Any]]:
    """Yield UI events while the image is uploaded, annotated and exported."""
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

    async def produce() -> None:
        url = spec.attachment_base_url + image["url"] if image["url"].startswith("/") else image["url"]
        task = "Upload the image, annotate it and export the result"
        emit({"type": "agent_start", "id": delegation, "agent": spec.name, "title": spec.title, "task": task})
        is_error = False
        try:
            async with connect(spec) as mcp:
                uploaded = await tool(
                    mcp, "upload_image_from_url", {"url": url, "name": image.get("name") or "image", "category": category}
                )
            image_id = uploaded["imageId"]
            label_line = f"Use exactly these label names: {', '.join(labels)}.\n" if labels else ""
            report = await run_specialist(
                spec,
                model=_model(disable_streaming=True),
                task=TASK.format(
                    image_id=image_id,
                    width=uploaded.get("width"),
                    height=uploaded.get("height"),
                    instructions=instructions,
                    labels=label_line,
                    grid=GRID.format(step=grid_step) if grid_step else "",
                ),
                user_text=instructions,
                images=[image],
                delegation_id=delegation,
                emit=emit,
            )
            async with connect(spec) as mcp:
                saved = await tool(mcp, "get_image", {"image_id": image_id})
                coco, yolo = await asyncio.gather(
                    tool(mcp, "export_annotations", {"image_id": image_id, "format": "coco"}),
                    tool(mcp, "export_annotations", {"image_id": image_id, "format": "yolo"}),
                )
            emit(
                {
                    "type": "label_result",
                    "image_id": image_id,
                    "width": saved.get("width"),
                    "height": saved.get("height"),
                    "annotations": saved.get("annotations") or [],
                    "report": report,
                    "exports": {"coco": coco, "yolo": yolo},
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
