#!/usr/bin/env bash
# Regenerate the SVG sequence diagrams used in USECASES.md from the .mmd sources.
# Usage: docs/diagrams/render.sh    (needs Node.js; downloads Mermaid CLI on first run)
set -euo pipefail
cd "$(dirname "$0")"
for src in *.mmd; do
  npx -y @mermaid-js/mermaid-cli@11.4.2 -q -i "$src" -o "${src%.mmd}.svg" -b white -c config.json
  echo "rendered ${src%.mmd}.svg"
done
