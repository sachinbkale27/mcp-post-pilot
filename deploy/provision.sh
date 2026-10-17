#!/usr/bin/env bash
# Create or update the serverless stack, run with YOUR AWS credentials (not the CI user's).
#
# Usage: deploy/provision.sh [allowed-cidrs]
#   allowed-cidrs  comma-separated IPv4 ranges allowed to use the site
#                  (default: your current public IP /32; 0.0.0.0/0 = everyone)
#
# Day-to-day code changes are deployed by GitHub Actions; rerun this only to change
# infrastructure or the allowed IPs. It keeps the image version CI last deployed.
set -euo pipefail
REGION=${AWS_REGION:-ap-south-1}
STACK=mcp-post-pilot
SECRET_PARAM=/mcp-post-pilot-infra/origin-secret
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export AWS_REGION=$REGION

CIDRS=${1:-$(curl -fsS https://checkip.amazonaws.com | tr -d '[:space:]')/32}

# Shared secret between CloudFront and the Lambdas: generated once, kept in Parameter Store.
if ! SECRET=$(aws ssm get-parameter --name "$SECRET_PARAM" --with-decryption --query Parameter.Value --output text 2>/dev/null); then
  SECRET=$(openssl rand -hex 32)
  aws ssm put-parameter --name "$SECRET_PARAM" --type SecureString --value "$SECRET" >/dev/null
  echo "Generated origin secret ($SECRET_PARAM)"
fi

deploy() {  # deploy <image-tag>
  aws cloudformation deploy --stack-name "$STACK" --template-file "$ROOT/deploy/cloudformation.yml" \
    --capabilities CAPABILITY_IAM --no-fail-on-empty-changeset \
    --parameter-overrides "ImageTag=$1" "AllowedCidrs=$CIDRS" "OriginSecret=$SECRET"
}

push_images() {  # build HEAD for Lambda (x86_64) and push; sets TAG
  local registry image
  TAG=$(git -C "$ROOT" rev-parse HEAD)
  registry=$(aws sts get-caller-identity --query Account --output text).dkr.ecr.$REGION.amazonaws.com
  aws ecr get-login-password | docker login --username AWS --password-stdin "$registry" >/dev/null
  for app in blog:blog-app agent:agent-chat; do
    image="$registry/mcp-post-pilot/${app%%:*}:$TAG"
    docker build -q --platform linux/amd64 --provenance=false -t "$image" "$ROOT/${app#*:}" >/dev/null
    for attempt in 1 2 3; do  # pushes over slow or proxied connections can drop
      docker push -q "$image" >/dev/null && continue 2
      echo "Push of $image failed (attempt $attempt), retrying..." >&2
      sleep 5
    done
    echo "Could not push $image" >&2
    exit 1
  done
}

if TAG=$(aws lambda get-function --function-name mcp-post-pilot-agent --query Code.ImageUri --output text 2>/dev/null); then
  TAG=${TAG##*:}
  echo "Updating $STACK in $REGION (images $TAG, allowed: $CIDRS)..."
else
  # No functions yet: make sure the ECR repositories exist, then push the first images.
  if ! aws cloudformation describe-stacks --stack-name "$STACK" >/dev/null 2>&1; then
    echo "Creating $STACK in $REGION (ECR repositories first)..."
    deploy ""
  fi
  [ -z "$(git -C "$ROOT" status --porcelain)" ] || echo "Note: uncommitted changes are included in the first images."
  echo "Building and pushing the first images..."
  push_images
  echo "Deploying $STACK (images $TAG, allowed: $CIDRS)..."
fi
deploy "$TAG"

aws cloudformation describe-stacks --stack-name "$STACK" \
  --query 'Stacks[0].Outputs[].[OutputKey,OutputValue]' --output table
echo "The UIs appear after the first GitHub Actions deploy uploads them (push to main, or: gh workflow run deploy.yml)."
