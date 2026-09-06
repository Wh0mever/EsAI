#!/usr/bin/env bash
# Добавить Telegram id в список тех, кому бот отвечает в режиме staff.
#   bash scripts/bot-staff.sh 123456789
# Узнать id постучавшегося: docker compose logs bot | grep "доступ закрыт"
set -euo pipefail
cd "$(dirname "$0")/.."
export COMPOSE_FILE=compose.yaml:compose.https.yaml
ID="$(printf '%s' "${1:-}" | tr -d '[:space:]')"
if ! printf '%s' "$ID" | grep -Eq '^[0-9]+$'; then
  echo "Нужен Telegram id цифрами: bash scripts/bot-staff.sh 123456789"; exit 1
fi
CURRENT="$(grep '^BOT_STAFF_IDS=' .env | cut -d= -f2- || true)"
case ",$CURRENT," in
  *",$ID,"*) NEW="$CURRENT" ;;
  *) NEW="${CURRENT:+$CURRENT,}$ID" ;;
esac
if grep -q '^BOT_STAFF_IDS=' .env; then
  awk -v v="$NEW" 'BEGIN{FS=OFS="="} $1=="BOT_STAFF_IDS"{print "BOT_STAFF_IDS=" v; next} {print}' .env > .env.tmp && mv .env.tmp .env
else
  printf 'BOT_STAFF_IDS=%s
' "$NEW" >> .env
fi
echo "BOT_STAFF_IDS=$NEW"
docker compose up -d --force-recreate --no-deps bot >/dev/null
echo "бот перезапущен"
