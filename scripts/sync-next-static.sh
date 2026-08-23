#!/usr/bin/env bash
# Скопировать статику свежей сборки Next в накопительную папку.
#
# Имена файлов Next содержат хэш содержимого, и при каждой выкладке контейнер
# пересоздаётся — файлы прошлой сборки пропадают. У пользователя же страница
# могла остаться от прошлой сборки: кэш браузера, service worker, предзагрузка
# из поиска Google. Он запрашивал свой css, получал 404 и видел сайт вообще без
# стилей (в логах nginx — 159 разных адресов с такими 404).
#
# Поэтому статика лежит на диске и только ДОПОЛНЯЕТСЯ: старые сборки остаются
# рабочими, пока их не подчистит ротация ниже.
#
# Запускать после `docker compose up -d next`.
set -euo pipefail

cd "$(dirname "$0")/.."

DEST="./next-static"
KEEP_DAYS="${KEEP_DAYS:-14}"

mkdir -p "$DEST"

# Копируем во временную папку, оттуда переносим: так nginx не увидит
# полускопированный файл.
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

docker compose cp next:/app/.next/static/. "$TMP/" >/dev/null
cp -rn "$TMP/." "$DEST/"

# Ротация: файлы, которых не касались две недели, почти наверняка уже никому не
# нужны — за это время страница переживёт и кэш браузера, и service worker.
find "$DEST" -type f -mtime "+$KEEP_DAYS" -delete 2>/dev/null || true
find "$DEST" -type d -empty -delete 2>/dev/null || true

echo "next-static: $(find "$DEST" -type f | wc -l) файлов, $(du -sh "$DEST" | cut -f1)"
