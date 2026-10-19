"""A LangGraph agent whose tools come from an MCP server.

The graph is the classic tool-use loop, made explicit:

    START -> agent --(AI message has tool_calls)--> tools -> agent -> ... -> END

  agent : sends the conversation + tool definitions to the LLM (OpenAI)
  tools : executes each requested tool by calling the MCP server (tools/call)

The agent knows nothing about blogs. Everything it can do is discovered at
runtime from the MCP server (tools/list) and translated into OpenAI function
definitions; swapping MCP_SERVER_URL gives it a completely different skill set.

With LANGSMITH_TRACING=true every run is traced to LangSmith: one trace per
user turn, with child runs for each graph node, LLM call and MCP tool call.

Conversation history is loaded before each turn and saved after it (memory.py),
so the same code works for one local process and for stateless Lambda instances.
"""

import asyncio
import json
import os
from contextlib import asynccontextmanager
from typing import Any

from .settings import load_settings

# OPENAI_API_KEY, LANGSMITH_* etc.: from agent-chat/.env locally, Parameter Store on AWS.
load_settings()

from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tracers.langchain import wait_for_all_tracers
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, MessagesState, StateGraph
from langsmith import traceable
from mcp.client.client import Client
from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client
from mcp_types import Tool as MCPTool

from .memory import get_conversation_store

MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://127.0.0.1:8101/mcp")
# On AWS the MCP server only accepts requests carrying the shared origin secret.
ORIGIN_SECRET = os.getenv("ORIGIN_SECRET")
MODEL = os.getenv("OPENAI_MODEL", "gpt-5-mini")

SYSTEM_PROMPT = """You are a helpful assistant connected to a blog through MCP tools.
Use the tools to answer questions about posts and to create, edit, publish, unpublish
or delete them when asked. Look up post ids with list_posts or search_posts rather than
guessing. Before deleting a post, make sure the user clearly asked for that specific post.
When the user attaches images you can see them, and you are told their URLs. To use one in a
post, pass it as cover_image_url and/or embed it in the content as ![alt text](url), with alt
text that describes what the image shows. Use each URL exactly as given, a path starting with
/media/; never add a scheme or host. Only use image URLs the user provided or that
generate_image returned. When the user asks for a generated, AI-made or new illustration (or
wants an image but attached none), call generate_image once with a vivid, specific prompt and
use the URL it returns.
Keep answers concise and use Markdown."""



@asynccontextmanager
async def connect_mcp():
    """Open an MCP client session (connect, initialize) to the blog MCP server."""
    if not ORIGIN_SECRET:
        async with Client(MCP_SERVER_URL) as client:
            yield client
        return
    async with create_mcp_http_client(headers={"x-origin-secret": ORIGIN_SECRET}) as http:
        async with Client(streamable_http_client(MCP_SERVER_URL, http_client=http)) as client:
            yield client


def mcp_tool_to_openai(tool: MCPTool) -> dict[str, Any]:
    """MCP and OpenAI both describe tools with a name, a description and a JSON Schema."""
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description or "",
            "parameters": tool.input_schema,
        },
    }


@traceable(run_type="tool", name="mcp tools/call")
async def call_mcp_tool(mcp: Client, name: str, arguments: dict[str, Any]) -> tuple[str, bool]:
    """Call one tool on the MCP server. Returns (content, is_error)."""
    try:
        result = await mcp.call_tool(name, arguments)
    except Exception as exc:  # transport failure, unknown tool, ...
        return f"MCP call failed: {exc}", True
    # Prefer structuredContent (typed JSON) when the tool declares an output schema;
    # fall back to the plain text content blocks.
    if result.structured_content is not None:
        return json.dumps(result.structured_content), bool(result.is_error)
    return "\n".join(c.text for c in result.content if c.type == "text"), bool(result.is_error)


def build_graph(mcp: Client, tools: list[dict[str, Any]]):
    # Created per turn so a missing/changed key is reported as a chat error, not a startup crash.
    # streaming=True: tokens are emitted as they arrive, which LangGraph's "messages" stream mode picks up.
    model = ChatOpenAI(model=MODEL, streaming=True).bind_tools(tools)

    async def agent(state: MessagesState) -> dict:
        response = await model.ainvoke([SystemMessage(SYSTEM_PROMPT), *state["messages"]])
        return {"messages": [response]}

    async def call_tools(state: MessagesState) -> dict:
        tool_calls = state["messages"][-1].tool_calls

        async def run(call: dict) -> ToolMessage:
            content, is_error = await call_mcp_tool(mcp, call["name"], call["args"])
            return ToolMessage(
                content, tool_call_id=call["id"], name=call["name"], status="error" if is_error else "success"
            )

        # The model may request several tools at once; run them concurrently.
        return {"messages": await asyncio.gather(*(run(c) for c in tool_calls))}

    def route(state: MessagesState) -> str:
        return "tools" if state["messages"][-1].tool_calls else END

    graph = StateGraph(MessagesState)
    graph.add_node("agent", agent)
    graph.add_node("tools", call_tools)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", route, ["tools", END])
    graph.add_edge("tools", "agent")
    return graph.compile()


async def list_mcp_capabilities() -> dict[str, Any]:
    """What the MCP server advertises (shown in the chat UI's sidebar)."""
    async with connect_mcp() as mcp:
        tools = await mcp.list_tools()
        resources = await mcp.list_resources()
        templates = await mcp.list_resource_templates()
        prompts = await mcp.list_prompts()
    return {
        "server_url": MCP_SERVER_URL,
        "model": MODEL,
        "tools": [{"name": t.name, "description": t.description, "input_schema": t.input_schema} for t in tools.tools],
        "resources": [str(r.uri) for r in resources.resources],
        "resource_templates": [t.uri_template for t in templates.resource_templates],
        "prompts": [{"name": p.name, "description": p.description} for p in prompts.prompts],
    }


def _user_message(text: str, images: list[dict[str, str]]) -> tuple[HumanMessage, HumanMessage]:
    """Build (message for the model, message for the saved history).

    The model gets the images inline so it can see them; the history keeps only their URLs,
    so stored conversations stay small.
    """
    if not images:
        return HumanMessage(text), HumanMessage(text)
    listing = "\n".join(f"- {img['url']}" + (f" ({img['name']})" if img.get("name") else "") for img in images)
    note = f"{text}\n\n[Attached {len(images)} image(s), uploaded at:\n{listing}]"
    parts: list[dict[str, Any]] = [{"type": "text", "text": note}]
    parts += [{"type": "image_url", "image_url": {"url": img["data_url"]}} for img in images]
    return HumanMessage(parts), HumanMessage(note)


async def run_turn(thread_id: str, user_text: str, images: list[dict[str, str]] | None = None):
    """Run one user turn, yielding UI events as the graph progresses.

    Two LangGraph stream modes are combined:
      "messages" -> (chunk, metadata) for every LLM token: streamed to the UI as `token` events
      "updates"  -> each node's state change once it finishes: tool calls and tool results
    """
    conversations = get_conversation_store()
    history = conversations.load(thread_id)
    model_message, history_message = _user_message(user_text, images or [])
    new_messages: list[BaseMessage] = [model_message]

    # One MCP session per turn: connect, initialize, discover tools.
    async with connect_mcp() as mcp:
        listed = await mcp.list_tools()
        tools = [mcp_tool_to_openai(t) for t in listed.tools]
        yield {"type": "mcp_connected", "server_url": MCP_SERVER_URL, "tools": [t["function"]["name"] for t in tools]}

        graph = build_graph(mcp, tools)
        config = {
            # recursion_limit caps agent<->tools round trips.
            "recursion_limit": 25,
            # LangSmith: name the trace and group a conversation's turns into one thread.
            "run_name": "blog-agent",
            "metadata": {"thread_id": thread_id},
        }
        stream = graph.astream({"messages": [*history, *new_messages]}, config, stream_mode=["messages", "updates"])
        async for mode, chunk in stream:
            if mode == "messages":
                message, metadata = chunk
                if metadata.get("langgraph_node") == "agent" and isinstance(message, AIMessageChunk) and message.text:
                    yield {"type": "token", "text": message.text}
            else:
                for delta in chunk.values():
                    for message in delta["messages"]:
                        new_messages.append(message)
                        for event in _events_for(message):
                            yield event

    # Save only after a completed turn, so a failed one never leaves half a tool exchange.
    conversations.save(thread_id, [*history, history_message, *new_messages[1:]])
    # Lambda freezes the process once the response ends; send pending LangSmith traces first.
    wait_for_all_tracers()


def reset_thread(thread_id: str) -> None:
    get_conversation_store().delete(thread_id)


def _events_for(message: BaseMessage):
    if isinstance(message, AIMessage):
        # The AI message's text was already sent token by token; only report its tool calls.
        for call in message.tool_calls:
            yield {"type": "tool_call", "id": call["id"], "name": call["name"], "input": call["args"]}
    elif isinstance(message, ToolMessage):
        content = message.content
        try:
            content = json.loads(content)
        except (TypeError, ValueError):
            pass
        yield {
            "type": "tool_result",
            "id": message.tool_call_id,
            "name": message.name,
            "output": content,
            "is_error": message.status == "error",
        }
