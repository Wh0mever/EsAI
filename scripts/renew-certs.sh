#!/usr/bin/env bash
set -euo pipefail

# Renew Let's Encrypt certificates via webroot and reload nginx.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

WEBROOT="/var/www/certbot"

docker compose run --rm certbot renew --webroot -w "$WEBROOT"

# Reload nginx (works for both HTTP and HTTPS modes)
docker compose exec nginx nginx -s reload || true

echo "Renewal complete and nginx reloaded"
