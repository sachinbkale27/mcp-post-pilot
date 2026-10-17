#!/usr/bin/env bash
# Start MCP Post Pilot:
#   Postgres (Docker) -> Blog API -> Blog MCP server -> Blog UI -> Agent API -> Chat UI
#
# Usage: ./startup.sh        start everything; Ctrl+C stops the app processes
#                            (Postgres keeps running: `docker compose down` to stop it)
# Logs:  ./logs/<service>.log
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
LOGS="$ROOT/logs"
mkdir -p "$LOGS"
PIDS=()

info() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

cleanup() {
  [ ${#PIDS[@]} -eq 0 ] && return
  info "Stopping services..."
  for pid in "${PIDS[@]}"; do
    # Kill the whole process group so npm's child vite process stops too.
    kill -- -"$pid" 2>/dev/null || kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
  info "Stopped. (Postgres is still running; 'docker compose down' to stop it.)"
}
trap cleanup EXIT
trap 'exit 130' INT TERM

# ---------------------------------------------------------------- checks
for cmd in docker uv npm curl; do
  command -v "$cmd" >/dev/null || fail "'$cmd' is not installed"
done
docker info >/dev/null 2>&1 || fail "Docker is not running - start Docker Desktop first"

for port in 8100 8101 8102 5173 5174; do
  if lsof -iTCP:"$port" -sTCP:LISTEN -t >/dev/null 2>&1; then
    fail "port $port is already in use (is the project already running? 'lsof -iTCP:$port -sTCP:LISTEN')"
  fi
done

if [ ! -f "$ROOT/agent-chat/.env" ]; then
  cp "$ROOT/agent-chat/.env.example" "$ROOT/agent-chat/.env"
  fail "created agent-chat/.env from the template - fill in OPENAI_API_KEY (and LANGSMITH_*), then rerun"
fi
grep -Eq '^OPENAI_API_KEY=.+' "$ROOT/agent-chat/.env" || fail "OPENAI_API_KEY is empty in agent-chat/.env"

# ---------------------------------------------------------- dependencies
for app in blog-app agent-chat; do
  if [ ! -d "$ROOT/$app/.venv" ]; then
    info "Creating Python venv for $app"
    (cd "$ROOT/$app" && uv venv -q --python 3.13)
  fi
  (cd "$ROOT/$app" && uv pip install -q -r pyproject.toml)
done
for ui in blog-app/frontend agent-chat/frontend; do
  if [ ! -d "$ROOT/$ui/node_modules" ]; then
    info "Installing npm packages for $ui"
    (cd "$ROOT/$ui" && npm install --silent)
  fi
done

# -------------------------------------------------------------- postgres
info "Starting Postgres"
(cd "$ROOT" && docker compose up -d --wait postgres >/dev/null 2>&1) || (cd "$ROOT" && docker compose up -d postgres >/dev/null)
for _ in $(seq 1 30); do
  docker exec mcp-post-pilot-postgres pg_isready -U blog -q 2>/dev/null && break
  sleep 1
done
docker exec mcp-post-pilot-postgres pg_isready -U blog -q || fail "Postgres did not become ready"

# -------------------------------------------------------------- services
# start <name> <dir> <command...>   runs in its own process group, logs to logs/<name>.log
start() {
  local name=$1 dir=$2; shift 2
  (cd "$ROOT/$dir" && exec "$@") >"$LOGS/$name.log" 2>&1 &
  PIDS+=($!)
}

# wait_for <name> <url>   polls until the URL answers
wait_for() {
  local name=$1 url=$2
  for _ in $(seq 1 60); do
    curl -s -o /dev/null "$url" && { info "$name is up"; return; }
    sleep 0.5
  done
  fail "$name did not start - see logs/$name.log"
}

set -m  # give each background job its own process group (for clean shutdown)

info "Starting Blog API"
start blog-api blog-app/backend ../.venv/bin/uvicorn app.main:app --port 8100
wait_for blog-api http://127.0.0.1:8100/posts

info "Starting Blog MCP server"
start blog-mcp blog-app .venv/bin/python mcp_server/server.py
wait_for blog-mcp http://127.0.0.1:8101/mcp

info "Starting Agent API"
start agent-api agent-chat/backend ../.venv/bin/uvicorn app.main:app --port 8102
wait_for agent-api http://127.0.0.1:8102/mcp/info

info "Starting UIs"
start blog-ui blog-app/frontend npm run dev
start chat-ui agent-chat/frontend npm run dev
wait_for blog-ui http://localhost:5173
wait_for chat-ui http://localhost:5174

cat <<EOF

  Blog UI        http://localhost:5173
  Agent chat UI  http://localhost:5174
  Blog API docs  http://localhost:8100/docs
  MCP server     http://127.0.0.1:8101/mcp   (try: npx @modelcontextprotocol/inspector)
  Agent API      http://localhost:8102/docs
  Logs           $LOGS/

  Press Ctrl+C to stop.
EOF

# Exit (and clean up everything) if any service dies.
while true; do
  for pid in "${PIDS[@]}"; do
    kill -0 "$pid" 2>/dev/null || fail "a service exited unexpectedly - check $LOGS/"
  done
  sleep 2
done
