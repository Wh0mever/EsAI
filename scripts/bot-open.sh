#!/usr/bin/env bash
# Открыть бота всем пользователям (после обкатки в режиме staff).
set -euo pipefail
cd "$(dirname "$0")/.."
export COMPOSE_FILE=compose.yaml:compose.https.yaml

if grep -q "^BOT_ACCESS=" .env; then
  awk 'BEGIN{FS=OFS="="} $1=="BOT_ACCESS"{print "BOT_ACCESS=all"; next} {print}' .env > .env.tmp
  mv .env.tmp .env
else
  echo "BOT_ACCESS=all" >> .env
fi

docker compose up -d --force-recreate --no-deps bot
echo "Бот отвечает всем. Вернуть обкатку: замените BOT_ACCESS на staff и повторите."
