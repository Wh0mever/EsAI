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

# Воркеры Celery тоже читают код с диска (./core:/app), но всегда
# ПЕРЕСОЗДАЁМ их, а не `restart`: restart поднимает контейнер с прежними
# настройками и не видит правок compose.yaml (монтирование кода, env,
# stop_grace_period, logging). Контейнер, созданный до монтирования, так и
# крутил бы старый код из образа — без новых задач beat и фиксов биллинга.
# --no-deps — чтобы заодно не пересоздались core и redis. При смене
# requirements/Dockerfile добавить --build.
# celery_media дорабатывает начатые съёмки до 12 минут, celery_vstudio
# (воркер видеостудии) — до 5 минут (stop_grace_period): команда может ждать,
# это нормально. Забыть celery_vstudio — значит оставить видеостудию на
# прежнем коде до следующей выкладки.
dc up -d --force-recreate --no-deps celery celery_beat celery_media celery_vstudio

# Фронтенд (всегда пересобирать образ — Next standalone):
dc build next
dc up -d --force-recreate next
# nginx спрашивает адреса core/next у docker-DNS на каждый запрос, рестарт
# nginx после пересоздания контейнеров больше не нужен. После правки
# nginx/nginx-ssl.conf — только пересоздание (файл примонтирован одиночным
# bind-mount, reload внутри контейнера видит старый файл):
# dc up -d --force-recreate --no-deps nginx
```

## Открытие видеостудии всем

У `/video-studio` два независимых выключателя, и порядок важен.

1. **Режим на бэкенде** — ключ `vstudio_mode=on`. Меняется без выкладки и
   действует сразу: admin-new → Настройки → «Видеостудия» → «Для всех» →
   «Сохранить». Значения: `off` — студии нет, `staff` — только сотрудники (так
   по умолчанию), `on` — все. Ключ сильнее `VSTUDIO_MODE` из `.env`; «Как в
   окружении» убирает его. У кого страница студии уже открыта, увидит её после
   обновления страницы.
2. **Сборка фронтенда** с `NEXT_PUBLIC_VSTUDIO_NAV=1` — пункт меню, ссылки на
   студию с главной и из чата, sitemap и индексация. Значение вшивается при
   сборке, поэтому образ пересобираем:
   ```bash
   # в /opt/esai/.env: NEXT_PUBLIC_VSTUDIO_NAV=1
   dc build next
   dc up -d --force-recreate next
   bash scripts/sync-next-static.sh
   ```

Сначала режим, потом сборка. Наоборот нельзя: людей приведёт в студию меню, а
там — «скоро откроется», и эту же страницу проиндексирует поиск.

До шага 1 проверить:
- `dc ps` — работают `celery_vstudio` (сами генерации), `celery` и
  `celery_beat` (снимают зависшие генерации и резервы кредитов);
- у нужных моделей стоит «Показывать в видеостудии» (Django-админка `/admin/`
  → GPT модели), а на счёте OpenRouter больше `VSTUDIO_MIN_PROVIDER_USD`;
- витрина первого экрана собрана: admin-new → «Витрина»
  (`/admin-new/vstudio-showcase`). Пока она пуста, первый экран показывает
  только сцены мультстудии. Ставятся в неё только работы сотрудников: в
  адресах файлов виден номер аккаунта автора.

Лёгкую копию ролика для лент первого экрана (480 px, без звука) собирает
воркер `celery` через несколько секунд после добавления работы в витрину; до
этого и при сбое сборки играет исходник. Собралась ли копия — Django-админка
`/admin/` → «Витрина видеостудии», колонка «Лёгкая копия»; там же действие
«Пересобрать лёгкую копию ролика».

Откат. Режим — там же, «Только сотрудники» или «Выключена»: действует сразу.
Уже запущенные генерации при этом доезжают и оплачиваются как обычно. Меню и
индексация уходят только новой сборкой: `NEXT_PUBLIC_VSTUDIO_NAV=` (пусто) и те
же три команды.

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
# /media/ показывает в браузере только картинки, звук, видео и PDF, остальное —
# на скачивание в песочнице (защита от скриптов в загруженных файлах):
echo '<rss/>' > media/_hdrcheck.rss
curl -sI https://esai.kg/media/_hdrcheck.rss | grep -i '^content-disposition'   # ждём attachment
rm media/_hdrcheck.rss
```

## Разово: старые вложения чата

До проверки расширений загрузка чата сохраняла файл под любым именем от
клиента, так что в `media/uploads/chat` могут лежать `.html`, `.svg`, `.rss`,
`.atom` и т. п. nginx их уже отдаёт только на скачивание, но лучше убрать их из
`/media` совсем. Не удаляем, а переносим в карантин вне `/media` — на них
ссылается старая история чатов (там они станут 404).

```bash
cd /opt/esai
# 1) посмотреть, что не проходит нынешний allowlist загрузки чата:
find media/uploads/chat -type f ! -iregex '.*\.\(jpe?g\|png\|gif\|webp\|bmp\|heic\|heif\|pdf\|docx?\|xlsx?\|pptx?\|txt\)' -print
# 2) перенести их в карантин с сохранением путей:
find media/uploads/chat -type f ! -iregex '.*\.\(jpe?g\|png\|gif\|webp\|bmp\|heic\|heif\|pdf\|docx?\|xlsx?\|pptx?\|txt\)' \
  -exec sh -c 'q=$0; for f; do mkdir -p "$q/$(dirname "$f")" && mv "$f" "$q/$f"; done' /opt/esai-quarantine {} +
# 3) остальной /media — только просмотреть (там могут быть законные SVG, их не трогать вслепую):
find media -type f -iregex '.*\.\(rss\|atom\|kml\|xspf\|mml\|x?html?\|shtml\|xht\|svgz?\|xml\|xsl\|m?js\)' -print
```

# 4) После выкладки nginx и карантина — сбросить кэш Cloudflare (Caching →
# Configuration → Purge Everything или Custom Purge по адресам из шага 1).
# SVG Cloudflare кэширует, а `/media/` отдаётся с `expires 7d`: без сброса
# старый ответ (без attachment и песочницы) ещё до недели живёт на краю сети,
# в том числе у перенесённых в карантин файлов.

> Перед крупным обновлением сделайте бэкап БД: `bash scripts/db-backup.sh`.

## Бот и очередь генераций

```bash
# бэкенд бота живёт в core (миграции botapi/ai/payments/plans применятся на старте core)
docker compose up -d --force-recreate --no-deps core
# воркеры читают код с диска, но именно пересоздаём (restart не применяет
# правки compose.yaml, см. «Обычное обновление»); при смене зависимостей — ещё --build
docker compose up -d --force-recreate --no-deps celery celery_beat celery_media
# сам бот
docker compose up -d --build bot
docker compose exec -T bot python -m bot.selfcheck
```

Включение с нуля — `scripts/bot-up.sh`; подробности и чек-лист — `docs/BOT.md`.
