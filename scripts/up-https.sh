#!/usr/bin/env bash
set -euo pipefail

# Switch stack to HTTPS (443) using compose override.
# Always run `down` (no -v!) before `up`.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

docker compose -f compose.yaml -f compose.https.yaml down || true
docker compose -f compose.yaml -f compose.https.yaml up -d

echo "HTTPS stack is up on :443"

