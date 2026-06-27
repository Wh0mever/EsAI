#!/usr/bin/env sh
set -e

: "${POSTGRES_HOST:=db}"
: "${POSTGRES_PORT:=5432}"
: "${APP_USER:=appuser}"
: "${APP_GROUP:=appuser}"
: "${APP_LOG_DIR:=/app/logs}"
: "${RUN_MIGRATIONS:=1}"
: "${RUN_COLLECTSTATIC:=1}"
export APP_LOG_DIR

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

mkdir -p /app/static /app/media "$APP_LOG_DIR"
touch "$APP_LOG_DIR/django.log" "$APP_LOG_DIR/celery.log" "$APP_LOG_DIR/celery_beat.log" || true

# When running as root we can fix ownership; otherwise just continue.
if [ "$(id -u)" -eq 0 ]; then
    chown -R "$APP_USER":"$APP_GROUP" /app/static /app/media "$APP_LOG_DIR" || \
        echo "Warning: unable to chown static/media/logs, continuing..." >&2
else
    echo "Skipping chown; container not running as root." >&2
fi

if [ "$RUN_MIGRATIONS" = "1" ]; then
    python manage.py migrate --noinput || true
fi

if [ "$RUN_COLLECTSTATIC" = "1" ]; then
    python manage.py collectstatic --noinput || true
fi

exec "$@"
