#!/usr/bin/env bash
# Print the blog owner's key: enter it at <blog URL>/owner to edit, unpublish or delete published posts, or to
# publish without a fact-check. It is derived from the origin secret (blog-app/backend/app/publishing.py), so
# it changes when provision.sh rotates that secret. Run it yourself; don't paste the key into chats or tickets.
set -euo pipefail
export AWS_REGION=${AWS_REGION:-ap-south-1}
SECRET=$(aws ssm get-parameter --name /mcp-post-pilot-infra/origin-secret --with-decryption --query Parameter.Value --output text)
SECRET="$SECRET" python3 -c '
import hashlib, hmac, os
print(hmac.new(os.environ["SECRET"].encode(), b"post-pilot blog owner v1", hashlib.sha256).hexdigest())'
