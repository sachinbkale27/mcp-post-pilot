"""The supervisor's delegation flow, with a scripted model and stub specialists (no OpenAI or MCP calls)."""

import asyncio
import json
from pathlib import Path

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from app import agent
from app.memory import get_conversation_store
from app.specialists import AgentSpec, parse_agents


class ScriptedModel(BaseChatModel):
    """Returns the scripted AI messages in order, whatever it is asked."""

    script: list[AIMessage]

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=self.script.pop(0))])


def call(tool: str, task: str, id: str) -> dict:
    return {"name": tool, "args": {"task": task}, "id": id}


BLOG = AgentSpec(name="blog", title="Blog agent", description="posts", mcp_url="http://blog/mcp", prompt="p")
GENETICS = AgentSpec(name="genetics", title="Genetics agent", description="research", mcp_url="http://gen/mcp", prompt="p")


@pytest.fixture
def team(monkeypatch):
    monkeypatch.setattr(agent, "load_agents", lambda: (BLOG, GENETICS))
    monkeypatch.setattr(agent, "wait_for_all_tracers", lambda: None)
    get_conversation_store.cache_clear()
    calls = []

    async def fake_specialist(spec, *, task, delegation_id, emit, **_):
        calls.append((spec.name, task))
        if spec.name == "genetics" and "fail" in task:
            raise ExceptionGroup("mcp", [ConnectionError("server down")])
        emit({"type": "tool_call", "id": f"t-{spec.name}", "name": "lookup", "input": {}, "agent": spec.name, "delegation": delegation_id})
        await asyncio.sleep(0)
        emit({"type": "tool_result", "id": f"t-{spec.name}", "name": "lookup", "output": "ok", "is_error": False, "agent": spec.name, "delegation": delegation_id})
        return f"{spec.name} report"

    monkeypatch.setattr(agent, "run_specialist", fake_specialist)
    return calls


def use_script(monkeypatch, *messages: AIMessage):
    supervisor = ScriptedModel(script=list(messages))
    monkeypatch.setattr(agent, "_model", lambda **kwargs: supervisor)


async def collect(thread: str, text: str) -> list[dict]:
    return [event async for event in agent.run_turn(thread, text)]


async def test_parallel_delegation_streams_nested_events_and_saves_history(team, monkeypatch):
    use_script(
        monkeypatch,
        AIMessage("", tool_calls=[call("ask_genetics", "research F508del", "d1"), call("ask_blog", "find CF posts", "d2")]),
        AIMessage("Both agents reported."),
    )
    events = await collect("t1", "F508del and CF posts?")

    assert sorted(team) == [("blog", "find CF posts"), ("genetics", "research F508del")]
    starts = [e for e in events if e["type"] == "agent_start"]
    assert {(e["id"], e["agent"]) for e in starts} == {("d1", "genetics"), ("d2", "blog")}
    tool_calls = [e for e in events if e["type"] == "tool_call"]
    assert {(e["agent"], e["delegation"]) for e in tool_calls} == {("genetics", "d1"), ("blog", "d2")}
    for start in starts:  # every delegation's tool events come between its start and end
        end = next(i for i, e in enumerate(events) if e["type"] == "agent_end" and e["id"] == start["id"])
        assert events.index(start) < max(i for i, e in enumerate(events) if e.get("delegation") == start["id"]) < end
    assert "".join(e["text"] for e in events if e["type"] == "token") == "Both agents reported."

    history = get_conversation_store().load("t1")
    reports = {m.name: m.content for m in history if isinstance(m, ToolMessage)}
    assert reports == {"ask_genetics": "genetics report", "ask_blog": "blog report"}


async def test_failed_agent_is_reported_to_the_supervisor_not_raised(team, monkeypatch):
    use_script(
        monkeypatch,
        AIMessage("", tool_calls=[call("ask_genetics", "please fail", "d1")]),
        AIMessage("The genetics agent is unavailable."),
    )
    events = await collect("t2", "anything")

    end = next(e for e in events if e["type"] == "agent_end")
    assert end["is_error"] is True
    report = next(m for m in get_conversation_store().load("t2") if isinstance(m, ToolMessage))
    assert report.status == "error"
    assert "ConnectionError: server down" in report.content


async def test_answers_without_agents(team, monkeypatch):
    use_script(monkeypatch, AIMessage("Hi! I coordinate a blog agent and a genetics agent."))
    events = await collect("t3", "hello")
    assert not team
    assert [e["type"] for e in events] == ["agents", "token"]


def test_registry_expands_env_drops_empty_headers_and_disables_agents(tmp_path: Path, monkeypatch):
    (tmp_path / "p.md").write_text("Be helpful.\n")
    monkeypatch.setenv("BLOG_URL", "http://blog/mcp")
    monkeypatch.delenv("UNSET_SECRET", raising=False)
    monkeypatch.delenv("OFF_URL", raising=False)
    entries = [
        {"name": "blog", "description": "d", "mcp_url": "${BLOG_URL}", "prompt_file": "p.md",
         "headers": {"x-origin-secret": "${UNSET_SECRET}"}, "images": True},
        {"name": "genetics", "description": "d", "mcp_url": "${GEN_URL:-https://gen/mcp}", "prompt_file": "p.md"},
        {"name": "off", "description": "d", "mcp_url": "${OFF_URL}", "prompt_file": "p.md"},
    ]
    blog, genetics = parse_agents(entries, tmp_path)
    assert (blog.mcp_url, blog.headers, blog.images, blog.prompt, blog.tool_name) == (
        "http://blog/mcp", {}, True, "Be helpful.", "ask_blog"
    )
    assert genetics.mcp_url == "https://gen/mcp"


def test_registry_rejects_bad_names_and_duplicates(tmp_path: Path):
    (tmp_path / "p.md").write_text("x")
    entry = {"description": "d", "mcp_url": "http://x/mcp", "prompt_file": "p.md"}
    with pytest.raises(ValueError, match="lowercase"):
        parse_agents([{**entry, "name": "Blog Agent"}], tmp_path)
    with pytest.raises(ValueError, match="twice"):
        parse_agents([{**entry, "name": "a"}, {**entry, "name": "a"}], tmp_path)


def test_shipped_agents_json_is_valid(monkeypatch):
    path = Path(agent.__file__).parent / "specialists" / "agents.json"
    entries = json.loads(path.read_text())
    monkeypatch.delenv("LABELS_MCP_URL", raising=False)
    monkeypatch.delenv("LABELS_MCP_TOKEN", raising=False)
    assert [a.name for a in parse_agents(entries, path.parent)] == ["blog", "genetics", "factcheck", "trials"]  # labels not provisioned

    monkeypatch.setenv("LABELS_MCP_URL", "https://labels.test/mcp")
    monkeypatch.setenv("LABELS_MCP_TOKEN", "tok")
    labels = next(a for a in parse_agents(entries, path.parent) if a.name == "labels")
    assert (labels.name, labels.headers, labels.attachment_base_url) == (
        "labels", {"authorization": "Bearer tok"}, "https://blog.sachin-kale.com"
    )


def test_header_with_only_an_unset_variable_is_dropped(tmp_path: Path, monkeypatch):
    (tmp_path / "p.md").write_text("x")
    monkeypatch.delenv("NO_TOKEN", raising=False)
    [spec] = parse_agents(
        [{"name": "a", "description": "d", "mcp_url": "http://x/mcp", "prompt_file": "p.md",
          "headers": {"authorization": "Bearer ${NO_TOKEN}"}}],
        tmp_path,
    )
    assert spec.headers == {}


def test_attachments_get_absolute_urls_for_agents_that_download_them():
    from app.specialists.runner import task_message

    spec = AgentSpec(name="labels", title="L", description="d", mcp_url="u", prompt="p", images=True,
                     attachment_base_url="https://blog.test")
    message = task_message(spec, "upload it", "label this", [{"url": "/media/a.png", "data_url": "data:image/png;base64,x"}])
    assert "https://blog.test/media/a.png" in message.content[0]["text"]
    assert message.content[1]["image_url"]["url"] == "data:image/png;base64,x"
    assert "blog.test" not in task_message(BLOG, "t", "u", [{"url": "/media/a.png", "data_url": "d"}]).content
