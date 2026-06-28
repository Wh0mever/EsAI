# Обновление EsAI (прод)

Стек работает в HTTPS-режиме (overlay `compose.yaml + compose.https.yaml`).
Поэтому все команды — с обоими `-f` файлами. Удобно завести алиас:

```bash
cd /opt/esai
alias dc='docker compose -f compose.yaml -f compose.https.yaml'
```

## Обычное обновление
```bash
cd /opt/esai
git pull origin main

# Бэкенд (код примонтирован, но при смене зависимостей/Dockerfile — пересборка):
dc build core            # если менялся requirements.txt/Dockerfile
dc up -d --force-recreate core
# Миграции применяются автоматически на старте core (entrypoint).
# Проверка, что миграции в порядке:
dc exec -T core python manage.py makemigrations --check --dry-run   # ждём "No changes detected"

# Фронтенд (всегда пересобирать образ — Next standalone):
dc build next
dc up -d --force-recreate next
```

## Применить миграции вручную (при необходимости)
```bash
dc exec -T core python manage.py migrate
```

## Полный перезапуск
```bash
bash scripts/up-https.sh          # down + up -d с HTTPS overlay
# (--build для пересборки образов: bash scripts/up-https.sh --build)
```

## Проверка после обновления
```bash
dc ps
curl -s -o /dev/null -w "%{http_code}\n" https://esai.kg/
curl -s https://esai.kg/api/ai/models/ | head -c 200
dc logs core --tail 50
```

> Перед крупным обновлением сделайте бэкап БД: `bash scripts/db-backup.sh`.
