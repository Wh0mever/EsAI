#!/usr/bin/env bash
set -euo pipefail

# Issue Let's Encrypt certificates via webroot challenge.
# Usage:
#   EMAIL=you@example.com scripts/issue-cert.sh            # production
#   EMAIL=you@example.com scripts/issue-cert.sh --staging  # staging (test-cert)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

# Contact e-mail for the Let's Encrypt account (required, no default).
EMAIL="${EMAIL:?Set EMAIL=you@example.com (ACME account contact e-mail)}"
# Lineage (certificate name) to ensure files land under /etc/letsencrypt/live/<CERT_NAME>
CERT_NAME="${CERT_NAME:-esai.kg}"

# Domains: one SAN certificate for all listed names (comma or space separated).
# Override with env DOMAINS to customize.
# Example: DOMAINS="esai.kg,www.esai.kg" CERT_NAME="esai.kg" EMAIL="you@example.com" ./scripts/issue-cert.sh
# Keep CERT_NAME in sync with the ssl paths in nginx/nginx-ssl.conf (/etc/letsencrypt/live/esai.kg/...).
IFS=', ' read -r -a DOMAINS <<< "${DOMAINS:-esai.kg,www.esai.kg}"
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

echo "Requesting certificates for: ${DOMAINS[*]} (cert-name: ${CERT_NAME})"

docker compose run --rm certbot \
  certonly --webroot -w "$WEBROOT" \
  "${DOMAIN_ARGS[@]}" \
  --cert-name "$CERT_NAME" \
  --agree-tos -m "$EMAIL" --no-eff-email --rsa-key-size 4096 $NONINT_FLAG $KEEP_FLAG $STAGING_FLAG $EXPAND_FLAG $FORCE_FLAG

echo "Certificates issued for: ${DOMAINS[*]}"
