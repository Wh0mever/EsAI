#!/usr/bin/env bash
set -e

# wait for db
python - <<'PY'
import os, time, sys, psycopg2
from urllib.parse import urlparse
url = urlparse(os.environ.get("DATABASE_URL", ""))
for _ in range(60):
    try:
        conn = psycopg2.connect(
            dbname=url.path[1:], user=url.username, password=url.password,
            host=url.hostname, port=url.port or 5432, connect_timeout=2
        )
        conn.close(); break
    except Exception:
        time.sleep(1)
else:
    sys.exit("DB not ready")
PY

python manage.py migrate --noinput
python manage.py collectstatic --noinput

exec "$@"
