"""Run the Clinical Trials agent on one search, for the chat UI's "Clinical Trials" view.

The view builds the question from its form, so the agent is called directly rather than through the
supervisor. Events use the chat's SSE format (agent_start, tool_call, tool_result, agent_end); the trial
cards come from the submit_trials result, and a final trials_report event carries the agent's report.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator
from typing import Any

from .agent import _model
from .specialists import AgentSpec, load_agents
from .specialists.runner import run_specialist

TRIALS_AGENT = "trials"

PERSON = """
The search is for one person. Pass this description, unchanged, as submit_trials' person, so each trial's
criteria are checked against it:
{person}"""


class TrialsUnavailable(RuntimeError):
    pass


def trials_agent() -> AgentSpec:
    spec = next((s for s in load_agents() if s.name == TRIALS_AGENT), None)
    if spec is None:
        raise TrialsUnavailable("The Clinical Trials agent isn't configured on this server.")
    return spec


async def run_trials(question: str, person: str = "") -> AsyncIterator[dict[str, Any]]:
    """Yield UI events while the agent searches, reads and files trials."""
    spec = trials_agent()
    queue: asyncio.Queue = asyncio.Queue()
    delegation = f"trials-{uuid.uuid4()}"
    emit = queue.put_nowait

    async def produce() -> None:
        emit({"type": "agent_start", "id": delegation, "agent": spec.name, "title": spec.title, "task": question})
        is_error = False
        try:
            report = await run_specialist(
                spec,
                model=_model(disable_streaming=True),
                task=question + (PERSON.format(person=person) if person else ""),
                user_text=question,
                images=[],
                delegation_id=delegation,
                emit=emit,
            )
            emit({"type": "trials_report", "report": report})
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
