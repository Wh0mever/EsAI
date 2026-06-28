# EsAI — AI-чат-агрегатор

EsAI — веб-сервис «Все AI в одном месте»: чат с ведущими нейросетями (ChatGPT,
DeepSeek, Gemini, Claude, Grok, Mistral, Perplexity) через единый интерфейс,
оплата токенов в кыргызских сомах. Прод: https://esai.kg

## Стек
- **Backend:** Django 5 + DRF + Celery + Redis + PostgreSQL 16
- **Frontend:** Next.js 16 (App Router, React 19, TypeScript, Tailwind, i18n ru/kg/en)
- **LLM:** OpenRouter (модели управляются из админки, без хардкода)
- **Оплата:** FreedomPay (KGS)
- **Инфра:** Docker Compose, nginx, Let's Encrypt (certbot)

## Ключевые возможности
- Мультимодельный чат + выбор модели; **streaming (SSE)**; Markdown + копирование кода
- **Токен-баланс**: списание по факту `total_tokens × коэффициент модели`; пакеты пополнения
- **Гостевой режим**: 3 бесплатных запроса без регистрации
- Вход **Google / Telegram** (без паролей/капчи)
- **RAG**: анализ документов (PDF/DOCX/XLSX/PPTX/TXT)
- **Веб-поиск** с источниками (OpenRouter online)
- **PWA** (установка как приложение, офлайн-оболочка)
- **SEO**: llms.txt, robots, динамический sitemap, страницы моделей/функций, JSON-LD, блог
- **Админка**: дашборд аналитики, no-code управление (модели/промпты/настройки/SEO/статьи), логирование

## Структура
```
core/      Django backend (apps: ai, plans, payments, users, content, mails, audit)
next/      Next.js frontend
nginx/     nginx.conf (HTTP) + nginx-ssl.conf (HTTPS)
scripts/   up-http.sh, up-https.sh, issue-cert.sh, renew-certs.sh, db-backup.sh
compose.yaml + compose.https.yaml   Docker Compose (HTTP / HTTPS overlay)
docs/      Документация (деплой/обновление/бэкап/админка/API)
```

## Быстрый старт (локально / HTTP)
```bash
cp .env.example .env   # заполнить значения
docker compose up -d --build
# приложение: http://localhost  (nginx → next + core)
```

## Документация
- [docs/DEPLOY.md](docs/DEPLOY.md) — развёртывание на сервере (домен + HTTPS)
- [docs/UPDATE.md](docs/UPDATE.md) — обновление прода
- [docs/BACKUP_RESTORE.md](docs/BACKUP_RESTORE.md) — бэкап и восстановление БД
- [docs/ADMIN.md](docs/ADMIN.md) — админ-панель (no-code управление)
- [docs/API.md](docs/API.md) — основные API-эндпоинты

Переменные окружения — см. [.env.example](.env.example).
