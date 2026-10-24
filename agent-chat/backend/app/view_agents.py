"""Run one specialist directly for a page of the chat UI (Clinical Trials, Medicines).

These pages build the question from a form, so the agent is called directly rather than through the
supervisor. Events use the chat's SSE format (agent_start, tool_call, tool_result, agent_end), and a final
report event (e.g. trials_report) carries the agent's report.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator
from typing import Any

from .agent import _model
from .specialists import AgentSpec, load_agents
from .specialists.runner import run_specialist


class AgentUnavailable(RuntimeError):
    pass


def view_agent(name: str, title: str) -> AgentSpec:
    spec = next((s for s in load_agents() if s.name == name), None)
    if spec is None:
        raise AgentUnavailable(f"The {title} agent isn't configured on this server.")
    return spec


async def run_view_agent(spec: AgentSpec, task: str, user_text: str, report_event: str) -> AsyncIterator[dict[str, Any]]:
    """Yield UI events while the agent works, then its report as a report_event event."""
    queue: asyncio.Queue = asyncio.Queue()
    delegation = f"{spec.name}-{uuid.uuid4()}"
    emit = queue.put_nowait

    async def produce() -> None:
        emit({"type": "agent_start", "id": delegation, "agent": spec.name, "title": spec.title, "task": user_text})
        is_error = False
        try:
            report = await run_specialist(
                spec,
                model=_model(disable_streaming=True),
                task=task,
                user_text=user_text,
                images=[],
                delegation_id=delegation,
                emit=emit,
            )
            emit({"type": report_event, "report": report})
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

    task_ = asyncio.create_task(run())
    try:
        while (item := await queue.get()) is not None:
            if isinstance(item, BaseException):
                raise item
            yield item
    finally:
        if not task_.done():
            task_.cancel()  # the client went away (Stop)
        await asyncio.gather(task_, return_exceptions=True)
