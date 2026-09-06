#!/usr/bin/env bash
# Включение Telegram-бота: спрашивает токен, дописывает .env, поднимает сервис.
#
# Токен нигде не сохраняется, кроме .env рядом с остальными секретами, и не
# печатается на экран. Служебный секрет (которым бот подписывает запросы к
# нашему API) скрипт генерирует сам — придумывать его не нужно.
set -euo pipefail

cd "$(dirname "$0")/.."
ENV_FILE=".env"
export COMPOSE_FILE=compose.yaml:compose.https.yaml

say() { printf '%s\n' "$*"; }
have() { grep -q "^$1=." "$ENV_FILE" 2>/dev/null; }

set_env() {
  local key="$1" value="$2"
  if grep -q "^${key}=" "$ENV_FILE" 2>/dev/null; then
    # Значение может содержать / и & — подставляем через awk, а не sed.
    awk -v k="$key" -v v="$value" 'BEGIN{FS=OFS="="}
      $1==k {print k "=" v; next} {print}' "$ENV_FILE" > "$ENV_FILE.tmp"
    mv "$ENV_FILE.tmp" "$ENV_FILE"
  else
    printf '%s=%s\n' "$key" "$value" >> "$ENV_FILE"
  fi
}

say "=== Включение бота EsAI ==="
cp "$ENV_FILE" "$ENV_FILE.bak.bot.$(date +%Y%m%d_%H%M)"

# 1. Токен бота
if have TELEGRAM_PRODUCT_BOT_TOKEN; then
  say "Токен бота уже задан — оставляю как есть."
else
  say ""
  say "Вставьте токен бота от @BotFather (ввод скрыт) и нажмите Enter:"
  read -rs TOKEN
  say ""
  if [ -z "${TOKEN:-}" ]; then
    say "Токен не введён — выхожу."; exit 1
  fi
  # Проверяем токен ДО записи: незачем класть в .env заведомо нерабочее.
  BOT_JSON="$(curl -s --max-time 20 "https://api.telegram.org/bot${TOKEN}/getMe" || true)"
  if ! printf '%s' "$BOT_JSON" | grep -q '"ok":true'; then
    say "Telegram не принял этот токен. Проверьте и запустите скрипт заново."
    exit 1
  fi
  USERNAME="$(printf '%s' "$BOT_JSON" | sed -n 's/.*"username":"\([^"]*\)".*/\1/p')"
  say "Бот принят: @${USERNAME}"
  set_env TELEGRAM_PRODUCT_BOT_TOKEN "$TOKEN"
  set_env TELEGRAM_PRODUCT_BOT_USERNAME "$USERNAME"
  unset TOKEN
fi

# 2. Служебный секрет — генерируем сами
if have BOT_SERVICE_SECRET; then
  say "Служебный секрет уже задан."
else
  SECRET="$(openssl rand -hex 32)"
  set_env BOT_SERVICE_SECRET "$SECRET"
  unset SECRET
  say "Служебный секрет сгенерирован."
fi

# 3. Кому отвечает бот
if ! have BOT_ACCESS; then
  set_env BOT_ACCESS staff
fi
if ! have BOT_STAFF_IDS; then
  say ""
  say "Ваш Telegram id (узнать: напишите @userinfobot). Пусто — пропустить:"
  read -r STAFF
  [ -n "${STAFF:-}" ] && set_env BOT_STAFF_IDS "$STAFF"
fi
say "Режим доступа: $(grep '^BOT_ACCESS=' "$ENV_FILE" | cut -d= -f2)"
say "  staff — отвечает только своим (для обкатки)"
say "  all   — отвечает всем; переключить: scripts/bot-open.sh"

# 4. Уведомления от сайта в бот
set_env TELEGRAM_NOTIFY_ENABLED 1

# 5. Поднимаем
say ""
say "Перезапускаю сервисы…"
docker compose up -d --force-recreate --no-deps core >/dev/null
docker compose up -d --build bot

say ""
say "Проверка окружения:"
docker compose exec -T bot python -m bot.selfcheck || true

say ""
say "Логи бота:  docker compose logs -f bot"
say "Открыть всем: scripts/bot-open.sh"
