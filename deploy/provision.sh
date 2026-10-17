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

push_images() {  # build HEAD for Lambda (x86_64) and push; prints the tag
  local tag registry
  tag=$(git -C "$ROOT" rev-parse HEAD)
  registry=$(aws sts get-caller-identity --query Account --output text).dkr.ecr.$REGION.amazonaws.com
  aws ecr get-login-password | docker login --username AWS --password-stdin "$registry" >/dev/null
  for app in blog:blog-app agent:agent-chat; do
    docker build -q --platform linux/amd64 --provenance=false -t "$registry/mcp-post-pilot/${app%%:*}:$tag" "$ROOT/${app#*:}" >/dev/null
    docker push -q "$registry/mcp-post-pilot/${app%%:*}:$tag" >/dev/null
  done
  echo "$tag"
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
  TAG=$(push_images)
  echo "Deploying $STACK (images $TAG, allowed: $CIDRS)..."
fi
deploy "$TAG"

aws cloudformation describe-stacks --stack-name "$STACK" \
  --query 'Stacks[0].Outputs[].[OutputKey,OutputValue]' --output table
echo "The UIs appear after the first GitHub Actions deploy uploads them (push to main, or: gh workflow run deploy.yml)."
