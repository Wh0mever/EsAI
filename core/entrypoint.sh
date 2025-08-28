#!/usr/bin/env sh
set -e

: "${POSTGRES_HOST:=db}"
: "${POSTGRES_PORT:=5432}"
: "${APP_USER:=appuser}"
: "${APP_GROUP:=appuser}"

python - <<'PY'
import os,socket,time,sys
h=os.getenv("POSTGRES_HOST","db"); p=int(os.getenv("POSTGRES_PORT","5432"))
for _ in range(60):
    try:
        with socket.create_connection((h,p),1.5): sys.exit(0)
    except OSError:
        time.sleep(1)
sys.exit(1)
PY

mkdir -p /app/static /app/media
chown -R "$APP_USER":"$APP_GROUP" /app/static /app/media

python manage.py migrate --noinput || true
python manage.py collectstatic --noinput || true

exec "$@"
