#!/usr/bin/env bash
set -euo pipefail

# Issue/expand certificates for all project domains (apex + www).
# Pass --staging to use Let's Encrypt staging.
# Uses scripts/issue-cert.sh internally (non-interactive).

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

# Domain groups (separate cert per apex)
DOMAINS_SET=(
  "vokalo.kg,www.vokalo.kg"
  "vokalo.online,www.vokalo.online"
  "vokalo.ru,www.vokalo.ru"
)

for entry in "${DOMAINS_SET[@]}"; do
  echo "==> Processing: ${entry}"
  DOMAINS="$entry" EXPAND=1 ./scripts/issue-cert.sh "${1:-}"
done

echo "All domains processed. If nginx is already on HTTPS, just reload:"
echo "  docker compose exec nginx nginx -s reload"

