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
# celery_media дорабатывает начатые съёмки и склейки до 25 минут, celery_vstudio
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
# каталоги media/ пишут и core, и воркеры Celery — ждём пустой вывод:
dc exec -T core find /app/media -type d ! -user appuser ! -perm -002
```

> Перед крупным обновлением сделайте бэкап БД: `bash scripts/db-backup.sh`.

## Склейка: свои видео (загрузка до 90 МБ, 21.10.2026)

Выкладка, в которой появилась загрузка своих видео в склейку (`/api/merge/uploads/`),
требует, кроме обычного обновления, пересоздать nginx: в `nginx/nginx-ssl.conf`
появился отдельный `location = /api/merge/uploads/` с `client_max_body_size 95m`
(остальной `/api/` — 25 МБ). Без этого nginx отвечает на загрузку больше 25 МБ
кодом 413, а приложение этого не видит. Там же новый `location ^~ /media/merge/uploads/`:
свои видео людей отдаются с `Cache-Control: private, no-store` (удалённое не живёт в
кэше Cloudflare и браузера).

```bash
# миграция merge/0002 (таблица своих видео) применится на старте core
dc up -d --force-recreate core
dc up -d --force-recreate --no-deps celery celery_beat celery_media celery_vstudio
# nginx: файл примонтирован одиночным bind-mount — только пересоздание, не reload.
# Сначала проверить НОВЫЙ файл во временном контейнере (рабочий nginx не трогается,
# порты run не публикует); ждём «syntax is ok» и «test is successful»:
dc run --rm --no-deps nginx nginx -t
dc up -d --force-recreate --no-deps nginx
# client_max_body_size — десятая строка блока, поэтому -A12 и отбор строки:
dc exec -T nginx nginx -T 2>/dev/null | grep -A12 'location = /api/merge/uploads/' | grep 95m   # ждём «client_max_body_size 95m;»
# свои видео — без кэша (404 несуществующего файла отдаёт тот же location):
curl -sI https://esai.kg/media/merge/uploads/0/00000000000000000000000000000000.mp4 | grep -i cache-control   # ждём «private, no-store»
# проверка без входа: 30 МБ мусора должны дойти до Django (401 от API), а не упасть в 413 nginx
head -c 31457280 /dev/urandom > /tmp/mu.bin
curl -s -o /dev/null -w "%{http_code}\n" -F "file=@/tmp/mu.bin;filename=x.mp4" https://esai.kg/api/merge/uploads/   # ждём 401
# (не 502: отказ дочитывает тело — merge.views.drain_body; 502 здесь — сообщить разработчику)
rm /tmp/mu.bin
# ffmpeg в образе core должен уметь HDR → SDR (zscale) и HEVC; без zscale склейка
# берёт запасной путь (цвета HDR-роликов бледнее), но не падает:
dc exec -T core sh -c "ffmpeg -hide_banner -filters | grep -c zscale; ffmpeg -hide_banner -decoders | grep -cE ' (hevc|vp9|av1|libdav1d) '"
# разбор своих видео идёт со списком декодеров (-codec_whitelist) и счётом кадров
# (-count_packets) — один раз прогнать проверку настоящим ffprobe внутри core
# (скрипт из заметок сборки, нужен core/settings_sqlitetest.py; ждём «ИТОГ: N из N»):
#   dc cp real_ffmpeg_check.py core:/tmp/ && dc exec -T -e MU_CORE=/app core python /tmp/real_ffmpeg_check.py
```

Свои видео лежат в `media/merge/uploads/<id пользователя>/`, 30 дней (уборка — та же
ежедневная задача `merge:purge_expired`). Квота — 10 файлов и 600 МБ на человека;
при свободном месте на диске меньше 2 ГБ загрузка отвечает 503 и ничего не пишет.

## Склейка: звук — голос за кадром, музыка, звук роликов (22.10.2026)

Миграции `merge/0003_merge_audio` и `plans/0026_reason_merge_audio` применятся на
старте core (свой трек — до 20 МБ, общий лимит `/api/` — 25 МБ, отдельного location
не нужно). Обязательно пересоздать воркеры: музыку делает новая задача
`merge.tasks.make_music` в очереди media (`celery_media`). И nginx: в обоих
`nginx/nginx*.conf` новый `location ^~ /media/merge/audio/` — звук склейки отдаётся с
`Cache-Control: private, no-store`, как свои видео (удалённая дорожка не живёт неделю
в кэше Cloudflare и браузера). Файл примонтирован одиночным bind-mount — сначала
проверка, потом только пересоздание (не reload).
Голос и музыка по описанию идут через ключ ElevenLabs мультстудии (runtime
`ELEVENLABS_API_KEY`) и по её ценам (`studio_voice_credits_per_1k`,
`studio_voice_min_credits`, `studio_music_credits_per_min`); без ключа кнопки
«Озвучить»/«Создать» скрыты, загрузка своего трека работает.

```bash
dc up -d --force-recreate core
dc up -d --force-recreate --no-deps celery celery_beat celery_media celery_vstudio
# задача музыки видна воркеру media (ждём строку с merge.tasks.make_music):
dc exec -T celery_media celery -A core inspect registered | grep make_music
# nginx: проверить НОВЫЙ файл во временном контейнере (ждём «syntax is ok» и «test is successful»),
# потом пересоздать; звук склейки — без кэша (404 несуществующего файла отдаёт тот же location):
dc run --rm --no-deps nginx nginx -t
dc up -d --force-recreate --no-deps nginx
curl -sI https://esai.kg/media/merge/audio/0/00000000000000000000000000000000.mp3 | grep -i cache-control   # ждём «private, no-store»
# сведение звука — один раз прогнать настоящим ffmpeg/ffprobe внутри core (скрипт из
# заметок сборки, нужен core/settings_sqlitetest.py; ElevenLabs в нём подменён; ждём «ИТОГ: N из N»):
#   dc cp real_mix_check.py core:/tmp/ && dc exec -T -e MA_CORE=/app core python /tmp/real_mix_check.py
```

Файлы звука лежат в `media/merge/audio/<id пользователя>/` и живут столько же, сколько
склейка (30 дней; уборка — та же `merge:purge_expired`).

Музыка по описанию держит место в `celery_media` до 540 с ожидания ElevenLabs, поэтому
разом на весь сайт делается не больше двух (заказ сверх этого получает «Сейчас готовится
много музыки — попробуйте через минуту», кредиты не трогаются). Предел — runtime-ключ
`merge_music_concurrency` (1…8, без выкладки; в панели его пока нет — из shell, действует
сразу: `set_runtime` сбрасывает кэш), без него — `MERGE_MUSIC_CONCURRENCY` в `.env`
(по умолчанию 2). Места живут в Redis-кэше (`merge:music-slot:<n>`, 12 минут): после
падения воркера они освобождаются сами, чистить руками ничего не нужно. Голос за кадром
склейки — до 2000 знаков (у мультстудии на сцену — по-прежнему 1000).

```bash
# поднять предел до трёх (вернуть — delete_runtime):
dc exec -T core python manage.py shell -c "from adminapi.runtime import set_runtime; set_runtime('merge_music_concurrency', 3)"
```

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
