"""Histopathology tools for the Annotate Images view: nuclei outlines, a quality check and stain normalization.

Unlike labeling, no model decides anything here: the view asks for one tool and this module calls the label
server's MCP tools directly (uploading the image first unless it is already in Image Label), streaming the
calls in the chat's event format:

  nuclei     detect_nuclei, then get_image and the exports -> label_result (with nuclei_summary)
  cells      classify_cells on the nuclei already found (a background job on the label server, checked with
             get_image until it ends), then get_image and the exports -> label_result (with cell_types)
  quality    check_image_quality -> quality_result
  normalize  normalize_stain -> normalized (the new image's id and a viewing URL)
"""

import asyncio
import uuid
from collections.abc import AsyncIterator
from typing import Any

from .labeling import _decode, labeling_agent
from .specialists.runner import call_mcp_tool, connect

TITLES = {"nuclei": "Detect nuclei", "quality": "Check image quality", "normalize": "Normalize stain", "cells": "Find cell types"}
CELLS_POLL_SECONDS = 5
CELLS_LIMIT_SECONDS = 360


async def run_pathology(
    image: dict[str, str], action: str, image_id: str | None = None, category: str = "agent-chat"
) -> AsyncIterator[dict[str, Any]]:
    spec = labeling_agent()
    queue: asyncio.Queue = asyncio.Queue()
    delegation = f"pathology-{uuid.uuid4()}"
    emit = queue.put_nowait

    async def tool(mcp, name: str, arguments: dict[str, Any]) -> Any:
        call_id = f"{name}-{uuid.uuid4()}"
        emit({"type": "tool_call", "id": call_id, "name": name, "input": arguments, "agent": spec.name, "delegation": delegation})
        content, is_error = await call_mcp_tool(mcp, name, arguments)
        output = _decode(content)
        emit({"type": "tool_result", "id": call_id, "name": name, "output": output, "is_error": is_error, "agent": spec.name, "delegation": delegation})
        if is_error:
            raise RuntimeError(f"{name} failed: {content}"[:300])
        return output

    async def produce() -> None:
        emit({"type": "agent_start", "id": delegation, "agent": spec.name, "title": spec.title, "task": TITLES[action]})
        is_error = False
        try:
            async with connect(spec) as mcp:
                target = image_id
                if not target:
                    url = spec.attachment_base_url + image["url"] if image["url"].startswith("/") else image["url"]
                    uploaded = await tool(
                        mcp, "upload_image_from_url", {"url": url, "name": image.get("name") or "image", "category": category}
                    )
                    target = uploaded["imageId"]
                emit({"type": "label_image", "image_id": target})
                if action == "quality":
                    emit({"type": "quality_result", **await tool(mcp, "check_image_quality", {"image_id": target})})
                elif action == "normalize":
                    done = await tool(mcp, "normalize_stain", {"image_id": target})
                    copy = await tool(mcp, "get_image", {"image_id": done["normalized"]["imageId"]})
                    emit({"type": "normalized", "image_id": copy["imageId"], "name": copy.get("filename"), "url": copy.get("url")})
                elif action == "cells":
                    await tool(mcp, "classify_cells", {"image_id": target, "wait_seconds": 0})
                    waited = 0
                    while True:
                        # Quiet checks: one call each, not shown as steps
                        content, is_error = await call_mcp_tool(mcp, "get_image", {"image_id": target})
                        cells = (_decode(content) or {}).get("cellTypes") or {} if not is_error else {}
                        if cells.get("status") in ("done", "failed") or waited >= CELLS_LIMIT_SECONDS:
                            break
                        await asyncio.sleep(CELLS_POLL_SECONDS)
                        waited += CELLS_POLL_SECONDS
                    if cells.get("status") != "done":
                        raise RuntimeError(cells.get("error") or "Finding cell types took too long. Try again in a minute.")
                    await emit_result(mcp, target, cell_types=cells)
                else:
                    found = await tool(mcp, "detect_nuclei", {"image_id": target})
                    await emit_result(mcp, target, nuclei_summary=found.get("summary"))
        except Exception:
            is_error = True
            raise
        finally:
            emit({"type": "agent_end", "id": delegation, "agent": spec.name, "is_error": is_error})

    async def emit_result(mcp, target: str, **extra: Any) -> None:
        """The image's saved annotations and their exports, as the view shows them."""
        saved = await tool(mcp, "get_image", {"image_id": target})
        coco, yolo, qupath = await asyncio.gather(
            *(tool(mcp, "export_annotations", {"image_id": target, "format": f}) for f in ("coco", "yolo", "qupath"))
        )
        emit({
            "type": "label_result",
            "image_id": target,
            "width": saved.get("width"),
            "height": saved.get("height"),
            "annotations": saved.get("annotations") or [],
            "report": "",
            "exports": {"coco": coco, "yolo": yolo, "qupath": qupath},
            **extra,
        })

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
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
