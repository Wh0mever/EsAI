# Развёртывание EsAI

## Требования
- Linux-сервер (Ubuntu 24.04+), 2+ ядра / 4+ ГБ RAM
- Docker + Docker Compose plugin
- Домен, A-запись на IP сервера (+ `www` CNAME)
- Открытые порты 80 и 443

## 1. Код и переменные
```bash
git clone git@github.com:Wh0mever/EsAI.git /opt/esai
cd /opt/esai
cp .env.example .env
nano .env   # заполнить все значения (см. .env.example)
```
Обязательно укажите: `DJANGO_SECRET_KEY`, `POSTGRES_*`, `DJANGO_ALLOWED_HOSTS`,
`CSRF_TRUSTED_ORIGINS`, `CORS_ALLOWED_ORIGINS`, `SITE_BASE_URL`,
`OPENROUTER_API_KEY`, `FREEDOM_PAY_MERCHANT_ID` + `FREEDOM_PAY_TOKEN`,
`GOOGLE_CLIENT_*`, `TELEGRAM_BOT_*`.

## 2. Запуск (HTTP) и проверка
```bash
bash scripts/up-http.sh        # docker compose down + up -d (nginx на :80)
```
Откройте `http://<домен>` — сайт должен открыться. БД миграции и collectstatic
выполняются автоматически на старте контейнера `core` (entrypoint).

Если БД новая — данные восстановите из дампа (см. BACKUP_RESTORE.md). Если БД
уже была восстановлена, миграции применятся сами.

## 3. SSL и переключение на HTTPS
```bash
# выпуск сертификата (webroot), домены/почта через env:
DOMAINS="esai.kg,www.esai.kg" CERT_NAME="esai.kg" EMAIL="you@example.com" \
  bash scripts/issue-cert.sh
# переключение стека на HTTPS (nginx-ssl.conf + :443):
bash scripts/up-https.sh
```
> В HTTPS-режиме все команды управления стеком запускайте c обоими файлами:
> `docker compose -f compose.yaml -f compose.https.yaml <cmd>` (или через скрипты).
> Иначе nginx откатится на HTTP-конфиг.

nginx-ssl.conf настроен на `server_name esai.kg www.esai.kg` и сертификат
`/etc/letsencrypt/live/esai.kg/`. Для другого домена — поправьте `nginx/nginx-ssl.conf`.

## 4. Cron (автопродление серта + бэкап БД)
```bash
crontab -e
# продление сертификата (2×/день):
0 3,15 * * * cd /opt/esai && bash scripts/renew-certs.sh >> /opt/esai/logs/certbot-renew.log 2>&1
# ежедневный бэкап БД (хранит 7 копий):
30 2 * * * cd /opt/esai && bash scripts/db-backup.sh >> /opt/esai/logs/db-backup.log 2>&1
```

## 5. Внешние настройки
- **Google OAuth**: redirect URI `https://<домен>/api/users/accounts/google/login/callback/`;
  опубликовать OAuth consent screen (Testing → Production).
- **Telegram**: в @BotFather `/setdomain` → ваш домен.
- **FreedomPay** (кабинет магазина): RESULT URL `https://<домен>/api/payments/tokens/postback/`,
  SUCCESS URL `https://<домен>/api/payments/tokens/success/`, SITE URL `https://<домен>`.
- **OpenRouter**: пополнить баланс ключа перед публичным трафиком.
