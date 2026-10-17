#!/usr/bin/env bash
# Runs ON the EC2 instance (as root, via SSM Run Command) for every deploy.
# Usage: remote-deploy.sh <registry> <image-tag> <region>
set -euo pipefail
REGISTRY=$1 IMAGE_TAG=$2 REGION=$3
APP_DIR=/opt/mcp-post-pilot
export HOME=/root
cd "$APP_DIR"

# First boot: wait until user data has installed Docker.
cloud-init status --wait >/dev/null 2>&1 || true
docker compose version >/dev/null || { echo "docker compose is not installed"; exit 1; }

# Database password: generated once and kept on the instance (Postgres is never exposed).
[ -f db.secret ] || { openssl rand -hex 24 > db.secret; chmod 600 db.secret; }

umask 077
cat > .env <<ENV
REGISTRY=$REGISTRY
IMAGE_TAG=$IMAGE_TAG
POSTGRES_PASSWORD=$(cat db.secret)
ENV

# App settings and API keys from SSM Parameter Store (/mcp-post-pilot/NAME -> NAME=value).
aws ssm get-parameters-by-path --region "$REGION" --path /mcp-post-pilot/ --with-decryption \
  --query 'Parameters[].[Name,Value]' --output text |
  while IFS=$'\t' read -r name value; do echo "${name##*/}=$value"; done > app.env
echo "Loaded settings: $(cut -d= -f1 app.env | tr '\n' ' ')"

aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$REGISTRY" >/dev/null
docker compose pull --quiet
docker compose up -d --remove-orphans
docker image prune -af --filter "until=72h" >/dev/null || true

# Smoke test through nginx: blog API, and the agent API reaching the MCP server.
for url in http://localhost/api/posts http://localhost:8080/api/mcp/info; do
  for i in $(seq 1 30); do
    curl -fsS -o /dev/null "$url" && { echo "OK  $url"; continue 2; }
    sleep 2
  done
  echo "FAILED  $url"; docker compose ps; docker compose logs --tail 30; exit 1
done
docker compose ps
