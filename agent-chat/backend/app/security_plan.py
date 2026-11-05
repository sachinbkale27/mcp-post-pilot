"""Run the Auth Security agent on one request, for the chat UI's "App Security" view.

The answer is the agent's report, in a final security_report event. A test token, when given, is added to the
agent's task only: the task shown in the UI never repeats it.
"""

from collections.abc import AsyncIterator
from typing import Any

from .view_agents import run_view_agent, view_agent

AUTH_AGENT = "auth"


async def run_security(question: str, token: str = "") -> AsyncIterator[dict[str, Any]]:
    """Yield UI events while the agent checks the setup and writes its plan."""
    spec = view_agent(AUTH_AGENT, "Auth Security")
    task = question
    if token:
        task += f"\n\nTest token to inspect with inspect_jwt (never repeat it in your answer):\n{token}"
    async for event in run_view_agent(spec, task, question, "security_report"):
        yield event
