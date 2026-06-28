# Бэкап и восстановление БД

БД — PostgreSQL в контейнере `db` (том `pgdata`). Креды берутся из `.env`.

## Автоматический бэкап
`scripts/db-backup.sh` делает `pg_dump | gzip` в `/opt/esai/backups/` и хранит
последние 7 копий. Ставится в cron (см. DEPLOY.md):
```
30 2 * * * cd /opt/esai && bash scripts/db-backup.sh >> /opt/esai/logs/db-backup.log 2>&1
```

## Ручной бэкап
```bash
cd /opt/esai
bash scripts/db-backup.sh
# -> backups/esai_db_YYYY-MM-DD_HHMM.sql.gz
```
Или напрямую:
```bash
docker compose -f compose.yaml -f compose.https.yaml exec -T db \
  sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --clean --if-exists' \
  | gzip > backup.sql.gz
```

## Восстановление
```bash
cd /opt/esai
# поднять только БД (если стек не запущен):
docker compose -f compose.yaml -f compose.https.yaml up -d --wait db
# восстановить из дампа:
gunzip -c backups/esai_db_YYYY-MM-DD_HHMM.sql.gz | \
  docker compose -f compose.yaml -f compose.https.yaml exec -T db \
  sh -c 'psql -q -v ON_ERROR_STOP=0 -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
# затем поднять/перезапустить приложение:
bash scripts/up-https.sh
```
Дамп создаётся с `--clean --if-exists`, поэтому корректно накатывается поверх
существующей схемы. После восстановления миграции применятся автоматически
(entrypoint `core`), на актуальной БД будет «No migrations to apply».

## Перенос на новый сервер
1. Сделать бэкап БД (выше) + скопировать `.env` и каталог `media/`.
2. На новом сервере: `git clone`, положить `.env`, поднять `db`, восстановить дамп,
   скопировать `media/`, затем `scripts/up-https.sh`.
