#!/usr/bin/env bash
set -euo pipefail

# Ежедневный бэкап БД ESAI. Хранит последние 7 копий.
# Ставится в cron (см. ниже). Запуск: bash scripts/db-backup.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

BACKUP_DIR="$PWD/backups"
mkdir -p "$BACKUP_DIR"

TS="$(date +%F_%H%M)"
OUT="$BACKUP_DIR/esai_db_${TS}.sql.gz"

docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --clean --if-exists' | gzip > "$OUT"

# Ротация: оставляем 7 последних
ls -1t "$BACKUP_DIR"/esai_db_*.sql.gz 2>/dev/null | tail -n +8 | xargs -r rm -f

echo "DB backup done: $OUT ($(du -h "$OUT" | cut -f1)); kept: $(ls -1 "$BACKUP_DIR"/esai_db_*.sql.gz | wc -l)"
