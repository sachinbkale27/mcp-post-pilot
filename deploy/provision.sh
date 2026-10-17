#!/usr/bin/env bash
# Create or update the serverless stack, run with YOUR AWS credentials (not the CI user's).
#
# Usage: deploy/provision.sh [allowed-cidrs]
#   allowed-cidrs  comma-separated IPv4 ranges allowed to use the site
#                  (default: your current public IP /32; 0.0.0.0/0 = everyone)
#
# Day-to-day code changes are deployed by GitHub Actions; rerun this only to change
# infrastructure, domains or the allowed IPs. It keeps the image version CI last deployed.
# Region and custom domains come from deploy/config.env.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=config.env
source "$ROOT/deploy/config.env"
REGION=${AWS_REGION:-ap-south-1}
STACK=mcp-post-pilot
SECRET_PARAM=/mcp-post-pilot-infra/origin-secret
export AWS_REGION=$REGION

CIDRS=${1:-$(curl -fsS https://checkip.amazonaws.com | tr -d '[:space:]')/32}

# Shared secret between CloudFront and the Lambdas: generated once, kept in Parameter Store.
if ! SECRET=$(aws ssm get-parameter --name "$SECRET_PARAM" --with-decryption --query Parameter.Value --output text 2>/dev/null); then
  SECRET=$(openssl rand -hex 32)
  aws ssm put-parameter --name "$SECRET_PARAM" --type SecureString --value "$SECRET" >/dev/null
  echo "Generated origin secret ($SECRET_PARAM)"
fi

# Custom domains: CloudFront needs the certificate in us-east-1, so it is its own stack.
CERT_ARN=""
if [ -n "${BLOG_DOMAIN:-}" ] && [ -n "${CHAT_DOMAIN:-}" ]; then
  echo "Certificate for $BLOG_DOMAIN and $CHAT_DOMAIN (us-east-1; first run waits for DNS validation)..."
  aws cloudformation deploy --region us-east-1 --stack-name "$STACK-certificate" \
    --template-file "$ROOT/deploy/certificate.yml" --no-fail-on-empty-changeset \
    --parameter-overrides "BlogDomain=$BLOG_DOMAIN" "ChatDomain=$CHAT_DOMAIN" "HostedZoneId=$HOSTED_ZONE_ID"
  CERT_ARN=$(aws cloudformation describe-stacks --region us-east-1 --stack-name "$STACK-certificate" \
    --query "Stacks[0].Outputs[?OutputKey=='CertificateArn'].OutputValue" --output text)
fi

deploy() {  # deploy <image-tag>
  aws cloudformation deploy --stack-name "$STACK" --template-file "$ROOT/deploy/cloudformation.yml" \
    --capabilities CAPABILITY_IAM --no-fail-on-empty-changeset \
    --parameter-overrides "ImageTag=$1" "AllowedCidrs=$CIDRS" "OriginSecret=$SECRET" \
      "BlogDomain=${BLOG_DOMAIN:-}" "ChatDomain=${CHAT_DOMAIN:-}" \
      "HostedZoneId=${HOSTED_ZONE_ID:-}" "CertificateArn=$CERT_ARN"
}

push_images() {  # build HEAD for Lambda (x86_64) and push; sets TAG
  local registry image
  TAG=$(git -C "$ROOT" rev-parse HEAD)
  registry=$(aws sts get-caller-identity --query Account --output text).dkr.ecr.$REGION.amazonaws.com
  aws ecr get-login-password | docker login --username AWS --password-stdin "$registry" >/dev/null
  for app in blog:blog-app agent:agent-chat; do
    image="$registry/mcp-post-pilot/${app%%:*}:$TAG"
    # Already pushed (e.g. by the GitHub Actions workflow)? Then there is nothing to do.
    if aws ecr describe-images --repository-name "mcp-post-pilot/${app%%:*}" --image-ids "imageTag=$TAG" >/dev/null 2>&1; then
      echo "Using existing image $image"; continue
    fi
    docker build -q --platform linux/amd64 --provenance=false -t "$image" "$ROOT/${app#*:}" >/dev/null
    for attempt in 1 2 3; do  # pushes over slow or proxied connections can drop
      docker push -q "$image" >/dev/null && continue 2
      echo "Push of $image failed (attempt $attempt), retrying..." >&2
      sleep 5
    done
    echo "Could not push $image. Alternative: push this commit to main; the GitHub Actions" >&2
    echo "workflow builds and pushes the images, then rerun deploy/provision.sh." >&2
    exit 1
  done
}

FIRST_RUN=false
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
  echo "Preparing the first images..."
  push_images
  FIRST_RUN=true
  echo "Deploying $STACK (images $TAG, allowed: $CIDRS)..."
fi
deploy "$TAG"

aws cloudformation describe-stacks --stack-name "$STACK" \
  --query 'Stacks[0].Outputs[].[OutputKey,OutputValue]' --output table
if $FIRST_RUN; then
  echo "The UIs appear after the first GitHub Actions deploy uploads them (push to main, or: gh workflow run deploy.yml)."
fi
