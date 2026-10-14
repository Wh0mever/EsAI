#!/usr/bin/env bash
set -euo pipefail

# Issue/expand certificates for all project domains (apex + www).
# Pass --staging to use Let's Encrypt staging.
# Uses scripts/issue-cert.sh internally (non-interactive).
# Usage: EMAIL=you@example.com ./scripts/issue-all.sh [--staging]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

: "${EMAIL:?Set EMAIL=you@example.com (ACME account contact e-mail)}"
export EMAIL

# Domain groups (separate cert per apex; the first name is the cert lineage)
DOMAINS_SET=(
  "esai.kg,www.esai.kg"
)

for entry in "${DOMAINS_SET[@]}"; do
  echo "==> Processing: ${entry}"
  DOMAINS="$entry" CERT_NAME="${entry%%,*}" EXPAND=1 ./scripts/issue-cert.sh "${1:-}"
done

echo "All domains processed. If nginx is already on HTTPS, just reload:"
echo "  docker compose exec nginx nginx -s reload"

