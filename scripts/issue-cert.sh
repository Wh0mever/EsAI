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

# Domains: by default only apex domain; override with env DOMAINS
# Example: DOMAINS="vokalo.kg,www.vokalo.kg" ./scripts/issue-cert.sh
if [[ -n "${DOMAINS:-}" ]]; then
  # split by comma or space
  IFS=', ' read -r -a DOMAINS <<< "${DOMAINS}"
else
  DOMAINS=("vokalo.kg")
fi
WEBROOT="/var/www/certbot"

STAGING_FLAG=""
if [[ "${1:-}" == "--staging" ]]; then
  STAGING_FLAG="--test-cert"
fi

# Optional non-interactive flags
EXPAND_FLAG=""
if [[ "${EXPAND:-}" == "1" ]]; then
  EXPAND_FLAG="--expand"
fi

FORCE_FLAG=""
if [[ "${FORCE:-}" == "1" ]]; then
  FORCE_FLAG="--force-renewal"
fi

# Run non-interactively; by default keep existing until expiring.
NONINT_FLAG="--non-interactive"
KEEP_FLAG="--keep-until-expiring"
# If expanding or forcing, drop keep-until-expiring to allow immediate issuance
if [[ -n "$EXPAND_FLAG" || -n "$FORCE_FLAG" ]]; then
  KEEP_FLAG=""
fi

# Ensure nginx is up on :80 to serve the ACME challenge
docker compose up -d nginx

DOMAIN_ARGS=()
for d in "${DOMAINS[@]}"; do
  DOMAIN_ARGS+=( -d "$d" )
done

echo "Requesting certificates for: ${DOMAINS[*]}"

docker compose run --rm certbot \
  certonly --webroot -w "$WEBROOT" \
  "${DOMAIN_ARGS[@]}" \
  --agree-tos -m "$EMAIL" --no-eff-email --rsa-key-size 4096 $NONINT_FLAG $KEEP_FLAG $STAGING_FLAG $EXPAND_FLAG $FORCE_FLAG

echo "Certificates issued for: ${DOMAINS[*]}"
