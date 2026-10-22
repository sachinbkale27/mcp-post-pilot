"""Specialist agents the supervisor delegates to.

Each specialist is a LangGraph agent with its own instructions and its own MCP server. They are listed in
agents.json (path overridable with AGENTS_CONFIG); adding an agent means adding an entry and a prompt file:

    name         id, used in the supervisor's tool name ask_<name>
    title        shown in the chat UI
    description  what it can do; the supervisor routes tasks by this
    mcp_url      its MCP server (Streamable HTTP). ${VAR} and ${VAR:-default} read the environment;
                 an agent whose URL expands to "" is disabled
    headers      extra HTTP headers for its MCP server, e.g. a shared secret; empty values are dropped
    prompt_file  its instructions, relative to agents.json
    images       whether it sees images the user attaches (default false)
"""

import json
import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

DEFAULT_CONFIG = Path(__file__).with_name("agents.json")
ENV_VAR = re.compile(r"\$\{(\w+)(?::-([^}]*))?\}")
NAME = re.compile(r"^[a-z][a-z0-9_]{0,30}$")


def _expand(value: str) -> str:
    return ENV_VAR.sub(lambda m: os.getenv(m.group(1)) or m.group(2) or "", value)


@dataclass(frozen=True)
class AgentSpec:
    name: str
    title: str
    description: str
    mcp_url: str
    prompt: str
    headers: dict[str, str] = field(default_factory=dict)
    images: bool = False

    @property
    def tool_name(self) -> str:
        return f"ask_{self.name}"


def parse_agents(entries: list[dict], base_dir: Path) -> tuple[AgentSpec, ...]:
    specs: list[AgentSpec] = []
    for entry in entries:
        name = entry["name"]
        if not NAME.match(name):
            raise ValueError(f"Agent name {name!r} must be lowercase letters, digits or _")
        if any(s.name == name for s in specs):
            raise ValueError(f"Agent {name!r} is listed twice")
        url = _expand(entry["mcp_url"])
        if not url:
            continue
        headers = {key: _expand(value) for key, value in entry.get("headers", {}).items()}
        specs.append(
            AgentSpec(
                name=name,
                title=entry.get("title", name),
                description=entry["description"],
                mcp_url=url,
                prompt=(base_dir / entry["prompt_file"]).read_text().strip(),
                headers={key: value for key, value in headers.items() if value},
                images=bool(entry.get("images", False)),
            )
        )
    if not specs:
        raise ValueError("No agents are configured")
    return tuple(specs)


@lru_cache
def load_agents() -> tuple[AgentSpec, ...]:
    path = Path(os.getenv("AGENTS_CONFIG") or DEFAULT_CONFIG)
    return parse_agents(json.loads(path.read_text()), path.parent)
