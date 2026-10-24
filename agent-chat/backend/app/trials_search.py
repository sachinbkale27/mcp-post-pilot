"""Run the Clinical Trials agent on one search, for the chat UI's "Clinical Trials" view.

The trial cards come from the submit_trials result, and a final trials_report event carries the agent's report.
"""

from collections.abc import AsyncIterator
from typing import Any

from .view_agents import AgentUnavailable, run_view_agent, view_agent

TRIALS_AGENT = "trials"

PERSON = """
The search is for one person. Pass this description, unchanged, as submit_trials' person, so each trial's
criteria are checked against it:
{person}"""

TrialsUnavailable = AgentUnavailable


async def run_trials(question: str, person: str = "") -> AsyncIterator[dict[str, Any]]:
    """Yield UI events while the agent searches, reads and files trials."""
    spec = view_agent(TRIALS_AGENT, "Clinical Trials")
    task = question + (PERSON.format(person=person) if person else "")
    async for event in run_view_agent(spec, task, question, "trials_report"):
        yield event
