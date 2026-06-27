#!/usr/bin/env bash
set -euo pipefail

# Bring up the stack in HTTP-only mode (port 80).
# Always run `down` first (no -v!) before `up`.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

docker compose down || true
docker compose up -d

echo "HTTP stack is up on :80"

