#!/usr/bin/env bash
set -euo pipefail

# Issue Let's Encrypt certificates via webroot challenge.
# Usage:
#   scripts/issue-cert.sh            # production
#   scripts/issue-cert.sh --staging  # staging (test-cert)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

EMAIL_DEFAULT="you@example.com"
EMAIL="${EMAIL:-$EMAIL_DEFAULT}"
DOMAINS=("vokalo.kg" "www.vokalo.kg")
WEBROOT="/var/www/certbot"

STAGING_FLAG=""
if [[ "${1:-}" == "--staging" ]]; then
  STAGING_FLAG="--test-cert"
fi

# Ensure nginx is up on :80 to serve the ACME challenge
docker compose up -d nginx

docker compose run --rm certbot \
  certbot certonly --webroot -w "$WEBROOT" \
  -d "${DOMAINS[0]}" -d "${DOMAINS[1]}" \
  --agree-tos -m "$EMAIL" --no-eff-email --rsa-key-size 4096 $STAGING_FLAG

echo "Certificates issued for: ${DOMAINS[*]}"

