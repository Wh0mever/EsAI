# API EsAI (основные эндпоинты)

База: `https://<домен>/api/`. Авторизация — JWT (`Authorization: Bearer <access>`),
кроме публичных эндпоинтов. Фронт обращается по относительному `/api/`.

## Чат и модели (`/api/ai/`)
### POST `/api/ai/chat/`
Отправка сообщения. Тело:
```json
{ "message": "текст", "model": "openai/gpt-4o", "stream": true,
  "web_search": false, "attachments": [{"type":"document","name":"f.pdf","text":"...","url":"..."}] }
```
- **Авторизованный**: списывает токены `ceil(total_tokens × markup_coefficient)`.
  Недостаточно токенов → **402** `{"error":"insufficient_tokens","balance_tokens":N}`.
- **Гость** (без токена, заголовок `X-Guest-Id`): 3 бесплатных запроса; сверх →
  **401** `{"error":"guest_limit_reached"}`.
- `stream:true` → ответ `text/event-stream`: `data: {"delta":"..."}` … затем
  `data: {"done":true,"message":{...},"tokens_charged":N,"balance_tokens":M}`.
  Иначе обычный JSON `{response, message, tokens_charged, balance_tokens}`.
- `web_search:true` или online-модель → в ответе поле `sources: [{title,url}]`.

### GET `/api/ai/models/` (public)
Список активных моделей для селектора: `[{id,name,openrouter_id,description,sort_order}]`.

### POST `/api/ai/attachments/upload/` (auth)
Загрузка файла. Для документов (PDF/DOCX/XLSX/PPTX/TXT) извлекает текст:
`{url,name,type:"document",text}`. Для картинок: `{url,name,type:"image"}`.

### Прочее: `GET /api/ai/sessions/`, `GET /api/ai/sessions/<ref>/`,
`GET /api/ai/chat/history/`, `DELETE /api/ai/chat/history/`,
`GET /api/ai/templates/`, `GET /api/ai/providers/`.

## Токены и оплата (`/api/plans/`)
- `GET /api/plans/balance/` (auth) → `{"balance_tokens": N}`
- `GET /api/plans/packages/` (public) → `[{id,name,tokens,bonus_tokens,price,currency}]`
- `GET /api/plans/transactions/` (auth) → последние транзакции токенов
- `POST /api/plans/purchase/` (auth) `{"package_id":1}` → `{redirect_url, order_id, amount, currency}` (FreedomPay)

## Криптооплата (`/api/plans/`, `/api/payments/crypto/`)
Оплата USDT/BTC/ETH/TON через процессор (NOWPayments). Кредиты начисляются
только после того, как сервер сам перезапросил состояние счёта у процессора;
телу вебхука не доверяем. Способ включается в админке (режим off/staff/on).

- `GET /api/payments/crypto/currencies/` (public) →
  `{enabled, rate_kgs_to_usd, fee_paid_by_user, currencies:[{code,coin,network,label,extra_id_required,network_cost,popular,min_usd}]}`.
  `enabled:false` — метод выключен или не открыт этому человеку. `min_usd` —
  минимум процессора для этой монеты; витрина гасит монеты, у которых он выше
  цены пакета. `fee_paid_by_user` — комиссия процессора уже в сумме к переводу.
- `POST /api/plans/purchase/` (auth) `{"package_id":1,"pay_currency":"USD","crypto_currency":"usdttrc20"}`
  → счёт: `{kind:"crypto", order_id, ui_state, pay:{address,extra_id,amount,...},
  price:{kgs,usd,rate_kgs_to_usd}, credits:{total,credited}, expires_at, seconds_left}`.
  Счёт создаётся кликом по монете. Повторный клик по тому же пакету и монете
  возвращает тот же счёт (`resumed:true`); живых счетов у человека может быть до шести.
  Ошибки: 403 `crypto_disabled`, 400 `crypto_currency_not_supported`,
  400 `crypto_amount_below_min` (+`min_usd`), 429 `crypto_too_many_open_invoices`.
- `GET /api/plans/purchase/crypto/<order_id>/` (auth, только владелец, иначе 404) —
  то же тело; экран оплаты опрашивает его, пока идёт перевод.
- `GET /api/plans/purchase/pending/` (auth) → `{"pending": {...}}` с `kind: "card" | "crypto"`.
- `POST /api/payments/crypto/nowpayments/ipn/` (public) — уведомление процессора.
  Подпись HMAC-SHA512 в заголовке `x-nowpayments-sig`; неверная — 400,
  недоступный процессор — 503 (доставит ещё раз), повтор — 200 `duplicate`.

## FreedomPay callbacks (`/api/payments/`, public)
- `POST /api/payments/tokens/postback/` — RESULT URL (начисление токенов, идемпотентно)
- `GET/POST /api/payments/tokens/success/` — SUCCESS URL
- `.../tokens/failure/` — неуспех

## Авторизация (`/api/users/`)
- `GET /api/users/accounts/google/login/?process=login` — вход Google (allauth)
- Telegram Login Widget → `/api/users/accounts/telegram/login/callback/`
- `GET /api/users/telegram-config/` (public) → `{bot_username, bot_id}`
- После соц-входа: redirect на `<SITE_BASE_URL>/auth/callback?access&refresh&user`
- `POST /api/users/signin/` `{email}` → код на почту; `POST /api/users/signin/confirm/` `{email, code}` → JWT
- `POST /api/users/token/refresh/` — обновить JWT (SimpleJWT). Входа по паролю нет: `token/`, `signup/`
  и формы allauth с паролем закрыты (регистрация на чужой email без проверки владения)
- Код из письма: 5 попыток на один код (попытка считается до сравнения); на одну почту с одного IP —
  до 15 неверных кодов в сутки, после каждых 15 неверных по почте проверка делает паузу (15 мин, затем 1 ч)
- Страницы allauth `accounts/login|signup|password/*|email/|confirm-email/*|reauthenticate/|login/code/*`
  редиректят на `/auth/signin` (соцвход `accounts/google/*`, `accounts/telegram/*` работает)
- `auth/complete/` кладёт токены во фрагмент: `/auth/callback#access=…&refresh=…`; сессия Django после
  этого живёт 5 минут. DRF — только JWT (`Authorization: Bearer`), без входа ответ `401`
- `GET /api/users/transfer/` → `{transferable, balance}`; переводить можно только купленные,
  реферальные и полученные переводом кредиты
- `GET /api/users/profile/` (auth)

## Контент/SEO (`/api/content/`, public)
- `GET /api/content/site-settings/`
- `GET /api/content/page-seo/?path=/model/chatgpt`
- `GET /api/content/articles/`, `GET /api/content/articles/<slug>/`

## Лимиты
DRF throttling: аноним `30/min`, авторизованный `120/min` (настройка в `.env`:
`DRF_THROTTLE_ANON` / `DRF_THROTTLE_USER`).
