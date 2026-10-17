# MCP Post Pilot

A blogging platform with an AI assistant that manages posts through the **Model Context Protocol (MCP)**.

- **Blog**: React + TypeScript UI, FastAPI REST API, PostgreSQL, and an MCP server that exposes the blog as tools, resources and prompts.
- **Agent chat**: a LangGraph agent (OpenAI) that discovers the blog's MCP tools at runtime and uses them to create, edit, publish and delete posts, streaming its answers over SSE.

```
┌──────────────────── Blog ─────────────────────────┐      ┌──────────────── Agent Chat ─────────────────┐
│                                                    │      │                                             │
│  React UI :5173 ──HTTP──► FastAPI :8100 ──► Postgres│      │  React chat UI :5174                         │
│                              ▲             :5433    │      │        │ POST /chat (SSE stream)            │
│                              │ HTTP                 │      │        ▼                                     │
│                     MCP server :8101/mcp ◄──────────┼──────┼── FastAPI :8102 ─ LangGraph agent ─► OpenAI │
│                     (tools/resources/prompts)       │ MCP  │        (MCP client)                          │
└────────────────────────────────────────────────────┘      └─────────────────────────────────────────────┘
```

| Path | What it is |
|---|---|
| `blog-app/backend/app/` | FastAPI REST API + SQLAlchemy models (create, update, publish, unpublish, view, delete) |
| `blog-app/mcp_server/server.py` | **MCP server**: wraps the REST API as MCP tools, resources and prompts |
| `blog-app/scripts/try_mcp_client.py` | A 30-line MCP client: discover the server and call tools by hand |
| `blog-app/frontend/` | React + TypeScript blog UI |
| `agent-chat/backend/app/agent.py` | **MCP client + LangGraph agent**: discovers tools over MCP, gives them to the OpenAI model, executes calls |
| `agent-chat/backend/app/main.py` | Chat API that streams the agent's steps and LLM tokens as Server-Sent Events |
| `agent-chat/frontend/` | React + TypeScript chat UI that shows every MCP tool call and result |

## Quick start

```bash
./startup.sh     # checks prerequisites, installs deps, starts Postgres + all 5 services
```

## Run services manually

Prereqs: Docker, [uv](https://docs.astral.sh/uv/), Node 20+, an OpenAI API key, and (optional) a LangSmith API key.

```bash
# 0. Database
docker compose up -d

# 1. Blog API (terminal 1)
cd blog-app && uv venv --python 3.13 && uv pip install -r pyproject.toml
cd backend && ../.venv/bin/uvicorn app.main:app --port 8100

# 2. Blog MCP server (terminal 2)
cd blog-app && .venv/bin/python mcp_server/server.py          # -> http://127.0.0.1:8101/mcp

# 3. Blog UI (terminal 3)
cd blog-app/frontend && npm install && npm run dev            # -> http://localhost:5173

# 4. Agent API (terminal 4)
cd agent-chat && uv venv --python 3.13 && uv pip install -r pyproject.toml
# fill in agent-chat/.env (gitignored): OPENAI_API_KEY, OPENAI_MODEL, LANGSMITH_*
cd backend && ../.venv/bin/uvicorn app.main:app --port 8102

# 5. Chat UI (terminal 5)
cd agent-chat/frontend && npm install && npm run dev          # -> http://localhost:5174
```

Poke the MCP server without any LLM:

```bash
cd blog-app && .venv/bin/python scripts/try_mcp_client.py
npx @modelcontextprotocol/inspector     # GUI: connect to http://127.0.0.1:8101/mcp (Streamable HTTP)
```

## How it works

1. **Transport.** The server speaks MCP over *Streamable HTTP*: JSON-RPC 2.0 messages POSTed to one
   endpoint (`/mcp`), with responses returned as JSON or an SSE stream. (The other standard transport is
   *stdio*, where a client launches the server as a subprocess, which is how Claude Desktop and Claude Code run local servers.)
2. **Handshake.** `Client(url)` sends `initialize`; the server replies with its name, protocol version,
   capabilities (tools/resources/prompts) and the `instructions` string.
3. **Discovery.** `tools/list` returns each tool's name, description and **JSON Schema** of its inputs.
   `MCPServer` generates these from the Python type hints and docstrings in `server.py`.
4. **Translation.** `mcp_tool_to_openai()` maps MCP tools 1:1 to OpenAI function definitions
   (`name`, `description`, `parameters` = the MCP `inputSchema`). The agent has no blog code of its own; it learns what it can do from the server.
5. **The loop (LangGraph).** `agent` node → the model decides to call e.g. `publish_post(post_id=3)` →
   `tools` node sends `tools/call` to the MCP server → the server calls `POST /posts/3/publish` →
   the result goes back to the model as a `ToolMessage` → repeat until the reply has no `tool_calls`.
   An `InMemorySaver` checkpointer keeps each conversation's messages, keyed by `thread_id`.
6. **Errors.** A tool that raises `ToolError` returns `isError: true` with the message (e.g. `404: Post 9 not found`);
   the agent passes it to the model, which can recover by looking up the right id.
7. **Streaming (SSE).** `graph.astream(..., stream_mode=["messages", "updates"])` yields LLM tokens
   (`messages`) and finished steps (`updates`). `POST /chat` sends them as Server-Sent Events
   (`event: token` / `tool_call` / `tool_result` / `done`, with JSON `data:`). The UI reads the stream with
   `fetch()` and parses the SSE format itself, because the browser's `EventSource` only supports GET.
   Try it raw: `curl -N -X POST localhost:8102/chat -H 'content-type: application/json' -d '{"message":"hi"}'`
8. **Tracing.** With `LANGSMITH_TRACING=true`, each chat turn appears in LangSmith as a `blog-agent` trace
   (agent node → LLM call with tool definitions → `mcp tools/call` spans), grouped into threads by conversation.

### The three MCP primitives (all in `server.py`)

| Primitive | Who decides to use it | Here |
|---|---|---|
| **Tools** | The model | `list_posts`, `search_posts`, `get_post`, `create_post`, `update_post`, `publish_post`, `unpublish_post`, `delete_post` |
| **Resources** | The application (attach as context) | `blog://posts`, `blog://posts/{post_id}` |
| **Prompts** | The user (pick a template) | `draft_blog_post`, `review_post` |

The agent uses only tools; the sidebar of the chat UI lists all three so you can see what the server advertises.
Tool **annotations** (`readOnlyHint`, `destructiveHint`, `idempotentHint`) are hints a client can use,
for example to ask for confirmation before `delete_post`.

## Roadmap

- Have the agent read **resources** (`client.read_resource("blog://posts/3")`) and offer **prompts** as slash-commands in the chat UI.
- Add human-in-the-loop approval for tools with `destructiveHint` (pause the LangGraph run before the `tools` node).
- Run the MCP server over **stdio** and connect it to Claude Desktop / Claude Code (`claude mcp add`).
- Add auth to the MCP server (`MCPServer(auth=..., token_verifier=...)`).
- Persist conversations with a Postgres checkpointer (`langgraph-checkpoint-postgres`) instead of `InMemorySaver`.

Versions this was built against: `mcp` 2.3 (where `FastMCP` was renamed `MCPServer`), `langgraph` 1.2,
`langchain-openai` 1.7, React 19, Vite 8. Set the model with `OPENAI_MODEL` in `agent-chat/.env`.
