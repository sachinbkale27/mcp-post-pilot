# MCP Post Pilot

A blogging platform with an AI assistant that manages posts through the **Model Context Protocol (MCP)**.

- **Blog**: React + TypeScript UI, FastAPI REST API, PostgreSQL, and an MCP server that exposes the blog as tools, resources and prompts.
- **Agent chat**: a multi-agent LangGraph app (OpenAI). A supervisor hands tasks to specialist agents, each an MCP client of its own server: the **Blog agent** (this blog's MCP server) and the **Genetics agent** ([genetics MCP server](https://genapi.sachin-kale.com/mcp): ClinVar, gnomAD, NCBI Gene, PubMed). Answers and every delegation and tool call stream over SSE. New agents are added in `agents.json`.

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
| `agent-chat/backend/app/agent.py` | **Supervisor**: a LangGraph agent whose tools are the specialist agents (`ask_blog`, `ask_genetics`, …) |
| `agent-chat/backend/app/specialists/` | **Specialist agents**: `agents.json` registry and prompts; `runner.py` runs one agent as an MCP client of its server |
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

## Deploy to AWS (serverless)

Nothing runs while nobody is using it: CloudFront and S3 serve the UIs, Lambda runs the
three Python services on demand, and DynamoDB stores posts and chat history. Idle cost is
close to $0; you pay per request (plus a few cents for stored images and data).

```
browser ──HTTPS──► CloudFront ── edge function: IP allow-list, /api routing, SPA fallback
                     ├─ /            S3   blog UI
                     ├─ /chat/       S3   agent chat UI
                     ├─ /api/blog/*  ──► Lambda: blog API ──────────────► DynamoDB (posts)
                     └─ /api/agent/* ──► Lambda: agent (SSE streaming) ─► DynamoDB (chats)
                                             │ MCP over HTTPS
                                             ▼
                                         Lambda: MCP server ──► blog API Lambda
```

- The same container images run locally and on Lambda: the [AWS Lambda Web Adapter](https://github.com/awslabs/aws-lambda-web-adapter)
  forwards each invocation to the unchanged uvicorn server, with response streaming for the chat.
- `STORAGE_BACKEND=dynamodb` and `CONVERSATION_BACKEND=dynamodb` switch storage; locally the
  defaults (Postgres, in-memory chat history) are used.
- Lambda function URLs are public, so CloudFront adds a secret `x-origin-secret` header and every
  service rejects requests without it. The MCP server runs stateless (`MCP_STATELESS=1`) because
  consecutive requests can reach different Lambda instances.

| File | Purpose |
|---|---|
| `deploy/cloudformation.yml` | Lambdas, function URLs, DynamoDB tables, S3, CloudFront + edge function, ECR, CI policy |
| `deploy/provision.sh` | Creates/updates the stacks (run by you, with your own AWS credentials) |
| `deploy/config.env` | Region and optional custom domains + Route 53 hosted zone |
| `deploy/certificate.yml` | TLS certificate for the custom domains (us-east-1, DNS-validated) |
| `.github/workflows/deploy.yml` | Build → push to ECR → update Lambdas → upload UIs → refresh CloudFront |

**Live:** blog at https://blog.sachin-kale.com, agent chat at https://agent.sachin-kale.com
(both CloudFront aliases; on the chat domain the edge function serves the chat app at `/`).

**One-time setup**

1. Set the region and (optionally) custom domains in `deploy/config.env`, then provision (needs an AWS CLI profile with admin-level rights, plus Docker for the first images):
   ```bash
   deploy/provision.sh                          # site usable only from your current IP
   deploy/provision.sh 203.0.113.0/24,0.0.0.0/0 # or other IPv4 ranges / everyone
   ```
2. Repository secrets (`gh secret set NAME` prompts for the value): `AWS_ACCESS_KEY_ID`,
   `AWS_SECRET_ACCESS_KEY` (the `github-actions-deployer` IAM user), `OPENAI_API_KEY`, optionally `LANGSMITH_API_KEY`.
3. Optional repository variables: `OPENAI_MODEL`, `LANGSMITH_PROJECT`, `LANGSMITH_TRACING`, `LANGSMITH_ENDPOINT`.
4. Push to `main` (or `gh workflow run deploy.yml`). The job summary shows the URLs.

**Notes**

- The blog API and chat have no login, so the edge function only admits the allowed IPv4 ranges.
  Allowing `0.0.0.0/0` lets anyone edit posts and spend your OpenAI credits. Rerun `provision.sh` when your IP changes.
- The first request after a while is a cold start (a few seconds).
- The posts table has point-in-time recovery and is kept even if the stack is deleted.
- Logs: CloudWatch log groups `/aws/lambda/mcp-post-pilot-{blog,mcp,agent}`.

## Posts with images

The agent can publish posts with pictures, in two ways:

- **Your photos.** Attach, paste or drop up to 4 images in the chat. The browser resizes them and
  uploads them to the blog API (`POST /images`: S3 on AWS, a local folder in development; served
  from `/media/...`). The agent receives each image (gpt-4o can see it) plus its URL, and uses the
  URL as the post's `cover_image_url` or inline as `![alt text](/media/...)`.
- **Generated illustrations.** Ask for an AI-made image and the agent calls the MCP tool
  `generate_image(prompt, size)`. The MCP server calls OpenAI's image API, stores the result through
  the same `/images` endpoint, and returns its URL. This needs an image model enabled for your
  OpenAI project (`OPENAI_IMAGE_MODEL`, default `gpt-image-2.5-flare`; `gpt-image-2.5-sunburst`
  also works). Each image costs a few cents. Without access, the tool returns a clear error instead
  of an image. To enable it: in the OpenAI dashboard, allow the model in the project's model limits
  (Settings > Project > Limits), and complete organization verification if OpenAI asks for it.

Image data never passes through MCP tool calls, only URLs: the UI (or the MCP server, for generated
images) uploads, and the agent references. The blog API stores links to uploaded images in one
canonical form, and the deploy never deletes `media/` from the bucket.

## Multiple agents

```
user ─▶ Supervisor ─┬─ ask_blog(task)      ─▶ Blog agent       ⇄ blog MCP server
                    ├─ ask_genetics(task)  ─▶ Genetics agent   ⇄ genetics MCP server
                    ├─ ask_labels(task)    ─▶ Labeling agent   ⇄ label-image MCP server
                    ├─ ask_factcheck(task) ─▶ Fact-check agent ⇄ research MCP server (in-process)
                    └─ ask_<name>(task)    ─▶ …any agent listed in agents.json
```

- **Routing.** Each specialist is one tool of the supervisor, described by its `description`. The
  supervisor calls independent agents in parallel and dependent ones in sequence ("research the
  variant, then write a draft post about it"), then writes the answer from their reports.
- **Isolation.** A specialist sees only its task and the user's latest message, and connects to its
  MCP server only when it is called. A failing agent comes back as an error report the supervisor
  relays; it doesn't end the turn.
- **Safety.** Agent reports are information, not instructions. Specialists only publish, unpublish or
  delete when the user's own message asks for it, so text from outside data (a paper's abstract, say)
  can't make the Blog agent delete posts.
- **Adding an agent.** Add an entry to `agent-chat/backend/app/specialists/agents.json` and a prompt file:

  ```json
  { "name": "labels", "title": "Labeling agent", "description": "Annotates images and exports COCO/YOLO datasets.",
    "mcp_url": "${LABELS_MCP_URL}", "headers": { "authorization": "Bearer ${LABELS_TOKEN}" },
    "prompt_file": "prompts/labels.md", "images": true }
  ```

  `${VAR}` and `${VAR:-default}` read the environment (Parameter Store on AWS); an agent whose URL
  is empty is disabled. The sidebar (`GET /agents`) shows each agent's MCP server and tools.
- **In-process servers.** `"mcp_url": "local:<name>"` runs an MCP server from `app/local_mcp/` inside the
  agent service, over an in-memory connection: no deployment of its own. Each delegation gets a fresh
  server instance, so it can keep state for that one task.
- **Checked reports.** `"report_tool": "<tool>"` makes an agent file its result through that tool. The
  agent is sent back (twice at most) until the tool accepts it, and the supervisor gets the tool's output
  instead of the agent's own wording.
- **Events.** `agent_start` / `agent_end` wrap each delegation, and specialist `tool_call` / `tool_result`
  events carry `agent` and `delegation`, so the UI nests them under the right agent.

## Fact-check agent

Checks a text (a draft post, an answer) claim by claim against sources it reads itself, using the
in-process research MCP server (`agent-chat/backend/app/local_mcp/research.py`):

| Tool | What it does |
|---|---|
| `web_search(query)` | Finds sources with OpenAI's web search tool (the agent's own key); the summary is only a lead |
| `fetch_page(url, focus?)` | Reads a page as text, or just the sentences about `focus`. PubMed, PMC, ClinVar and NCBI Gene links are read through NCBI E-utilities, because NCBI shows scripts a bot check. Other sites' bot checks are reported as "blocked", never read as content |
| `check_links(urls)` | Status and final URL of each link |
| `submit_report(claims, overall)` | Accepts a verdict that cites a source (supported, partly supported, contradicted, outdated) only if that page was fetched in this delegation, the evidence is an exact quote from it, and the quote is about the claim |

Pages are fetched from the public internet only: non-HTTP schemes, other ports, credentials in URLs and
private, loopback or link-local addresses are refused, and every redirect is checked again.

Try: *"Fact-check post 12 and tell me what needs fixing"*, or *"Fact-check post 12, fix what it finds,
and show me the changes"*. The supervisor fetches the text through the Blog agent first.

## How it works

Step-by-step sequence diagrams for every flow (blog CRUD, agent tool calls, error recovery, memory,
deploys) are in [USECASES.md](USECASES.md).

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
   Each conversation's messages are loaded before a turn and saved after it (`memory.py`): in memory locally, DynamoDB on AWS.
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
- Add authentication to the blog API, agent chat and MCP server (`MCPServer(auth=..., token_verifier=...)`), then HTTPS with a domain.

Versions this was built against: `mcp` 2.3 (where `FastMCP` was renamed `MCPServer`), `langgraph` 1.2,
`langchain-openai` 1.7, React 19, Vite 8. Set the model with `OPENAI_MODEL` in `agent-chat/.env`.
