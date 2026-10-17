#!/usr/bin/env bash
# One-time (and occasional) infrastructure setup, run with YOUR AWS credentials -
# not the CI user's. Creates/updates the CloudFormation stack: EC2 instance,
# Elastic IP, security group, ECR repos, and the CI deploy policy.
#
# Usage: deploy/provision.sh [allowed-cidr]
#   allowed-cidr  who may open the UIs (default: your current public IP /32)
set -euo pipefail
REGION=${AWS_REGION:-ap-south-1}
STACK=mcp-post-pilot
cd "$(dirname "$0")"

CIDR=${1:-$(curl -fsS https://checkip.amazonaws.com | tr -d '[:space:]')/32}
params=("AllowedCidr=$CIDR")

# Pin the AMI only when creating the stack; on updates the stored value is kept,
# because a new AMI would replace the instance (and its database).
if ! aws cloudformation describe-stacks --region "$REGION" --stack-name "$STACK" >/dev/null 2>&1; then
  AMI=$(aws ssm get-parameter --region "$REGION" \
    --name /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64 \
    --query Parameter.Value --output text)
  params+=("ImageId=$AMI")
  echo "Creating stack $STACK in $REGION (AMI $AMI, UIs open to $CIDR)..."
else
  echo "Updating stack $STACK in $REGION (UIs open to $CIDR)..."
fi

aws cloudformation deploy --region "$REGION" --stack-name "$STACK" \
  --template-file cloudformation.yml --capabilities CAPABILITY_IAM \
  --no-fail-on-empty-changeset --parameter-overrides "${params[@]}"

aws cloudformation describe-stacks --region "$REGION" --stack-name "$STACK" \
  --query 'Stacks[0].Outputs[].[OutputKey,OutputValue]' --output table
