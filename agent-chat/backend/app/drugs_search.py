"""Run the Drug Information agent on one question, for the chat UI's "Medicines" view.

The answer is the submit_drug_info report, in a final drug_report event.
"""

from collections.abc import AsyncIterator
from typing import Any

from .view_agents import run_view_agent, view_agent

DRUGS_AGENT = "drugs"


async def run_drugs(question: str) -> AsyncIterator[dict[str, Any]]:
    """Yield UI events while the agent reads FDA labels and files its answer."""
    spec = view_agent(DRUGS_AGENT, "Drug Information")
    async for event in run_view_agent(spec, question, question, "drug_report"):
        yield event
