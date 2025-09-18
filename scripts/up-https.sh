#!/usr/bin/env bash
set -euo pipefail

# Switch stack to HTTPS (443) using compose override.
# Always run `down` (no -v!) before `up`.
# If called with --build, rebuild images before starting.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

FILES=(-f compose.yaml -f compose.https.yaml)

docker compose "${FILES[@]}" down || true

if [[ "${1:-}" == "--build" ]]; then
  echo "Rebuilding images (--build flag detected)..."
  docker compose "${FILES[@]}" build
fi

docker compose "${FILES[@]}" up -d

echo "HTTPS stack is up on :443"
