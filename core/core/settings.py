from pathlib import Path
from datetime import timedelta
import os
import environ

# --- Base paths & env ---
BASE_DIR = Path(__file__).resolve().parent.parent
env = environ.Env()
environ.Env.read_env(os.path.join(BASE_DIR, ".env"))

# --- Core settings ---
SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = env.bool("DJANGO_DEBUG", default=False)

# Brand / site display name (used in emails, admin, etc.)
SITE_NAME = "EsAI"

ALLOWED_HOSTS = env.list(
    "DJANGO_ALLOWED_HOSTS",
    default=["localhost", "127.0.0.1"],
)

# Behind nginx reverse proxy: trust X-Forwarded-Proto
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Приветственный бонус новым пользователям (кредиты). После нормализации ÷1000
# масштаб мелкий: 3 кредита (≈ старые 3000). Тюнится через env (читают core+celery).
WELCOME_BONUS_TOKENS = env.int("WELCOME_BONUS_TOKENS", default=3)

# Реферальный бонус: сколько КРЕДИТОВ получает пригласивший за каждого нового
# пользователя, зарегистрированного по его реф-коду. Меняется ТОЛЬКО здесь/в .env,
# на сайте размер нигде не показывается (требование клиента).
REFERRAL_BONUS_TOKENS = env.int("REFERRAL_BONUS_TOKENS", default=3)

# Реферальный revenue-share: ПОЖИЗНЕННЫЙ % от КУПЛЕННЫХ кредитов приглашённого,
# который получает пригласивший при КАЖДОМ его пополнении. Дефолт 10%.
# Значение можно переопределить в рантайме через админку (AppSetting
# "REFERRAL_PERCENT", см. adminapi.runtime) — env здесь лишь fallback.
REFERRAL_PERCENT = env.int("REFERRAL_PERCENT", default=10)

# Скидка при попытке ухода со страницы тарифов (exit-intent discount).
# Реализована как СНИЖЕНИЕ СУММЫ ОПЛАТЫ за тот же пакет (не бонусные кредиты).
# EXIT_DISCOUNT_PERCENT — размер скидки в %, EXIT_DISCOUNT_MINUTES — время
# жизни окна оффера с момента показа (сервер источник истины), EXIT_DISCOUNT_ENABLED —
# общий выключатель. Значения переопределяемы в рантайме через админку
# (AppSetting, см. adminapi.runtime) — env здесь лишь fallback.
EXIT_DISCOUNT_PERCENT = env.int("EXIT_DISCOUNT_PERCENT", default=20)
EXIT_DISCOUNT_MINUTES = env.int("EXIT_DISCOUNT_MINUTES", default=15)
EXIT_DISCOUNT_ENABLED = env.bool("EXIT_DISCOUNT_ENABLED", default=True)

# Курс для ВИТРИННОГО пересчёта цен KGS -> RUB (задача клиента: ЮKassa попросила
# показывать цены и в рублях; реальная оплата пока всё равно идёт через
# FreedomPay в сомах — см. plans/views.py CurrencyRateView и next/src/lib/currency.ts).
# Это НЕ платёжный курс и НЕ связан со старой CurrencyRate/selected_currency
# моделью (та — мёртвый остаток подписочной модели Vokalo, USD-базис). Значение
# переопределяемо в рантайме через админку (AppSetting "currency_kgs_to_rub_rate",
# см. adminapi.runtime) — env/это значение здесь лишь дефолт-фолбэк.
# ⚠️ ПРИМЕРНОЕ значение на момент внедрения (лето 2026, ~1 сом ≈ 0.95 руб. по
# кросс-курсу через USD) — АДМИН ОБЯЗАН проверить и обновить его под актуальный
# рыночный курс перед тем, как показывать рублёвые цены реальным пользователям.
CURRENCY_KGS_TO_RUB_RATE = env.float("CURRENCY_KGS_TO_RUB_RATE", default=0.95)

# CSRF trusted origins
_DEFAULT_CSRF_TRUSTED = [
    "https://esai.kg",
    "https://www.esai.kg",
]
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=_DEFAULT_CSRF_TRUSTED)

# --- Applications ---
INSTALLED_APPS = [
    # Django
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sites",

    # Task queue
    "django_celery_results",
    "django_celery_beat",

    # API
    "rest_framework",
    "rest_framework.authtoken",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",

    # Auth (Social)
    "corsheaders",
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.google",
    "allauth.socialaccount.providers.facebook",
    "allauth.socialaccount.providers.telegram",
    "allauth.socialaccount.providers.instagram",

    # Project apps
    "mails.apps.MailsConfig",
    "users.apps.UsersConfig",
    "content.apps.ContentConfig",
    "ai.apps.AiConfig",
    "plans.apps.PlansConfig",
    "payments.apps.PaymentsConfig",
    "audit.apps.AuditConfig",
    "adminapi.apps.AdminapiConfig",
    "cartoon.apps.CartoonConfig",
]

SITE_ID = 1

# --- Auth backends ---
AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]

AUTH_USER_MODEL = "users.User"

# --- Middleware ---
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    # Аудит: ловит необработанные исключения вью → EventLog(error_server)
    "audit.middleware.AuditExceptionMiddleware",
]

# --- URL / WSGI ---
ROOT_URLCONF = "core.urls"
WSGI_APPLICATION = "core.wsgi.application"

# --- Templates ---
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [
            BASE_DIR / "templates",
            BASE_DIR / "mails" / "templates",
            BASE_DIR / "core" / "templates",
        ],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# --- Database ---
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("POSTGRES_DB"),
        "USER": env("POSTGRES_USER"),
        "PASSWORD": env("POSTGRES_PASSWORD"),
        "HOST": env("POSTGRES_HOST", default="db"),
        "PORT": env("POSTGRES_PORT", default="5432"),
        "CONN_MAX_AGE": 60,
        "ATOMIC_REQUESTS": True,
    }
}

# --- Password validation ---
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --- Internationalization ---
LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Bishkek"
USE_I18N = True
USE_TZ = True
LANGUAGES = [
    ("ru", "Русский"),
    ("en", "English"),
]
DATE_FORMAT = "d.m.Y"
DATETIME_FORMAT = "d.m.Y H:i:s"
TIME_FORMAT = "H:i:s"

# --- Static & media ---
STATIC_URL = "/static/"
STATIC_ROOT = os.path.join(BASE_DIR, "static")
STATICFILES_DIRS = [BASE_DIR / "core" / "static"]
MEDIA_URL = "/media/"
MEDIA_ROOT = os.path.join(BASE_DIR, "media")
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- REST framework (Session + JWT) ---
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    # --- Throttling (ТЗ 8: защита от abuse) ---
    # Глобальные классы троттлинга: аноним по IP, авторизованный по user id.
    # Ставки переопределяемы через env (anon/user), дефолты ниже.
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": env.str("DRF_THROTTLE_ANON", default="30/min"),
        "user": env.str("DRF_THROTTLE_USER", default="120/min"),
    },
}

# --- Cache (use shared Redis to avoid per-process cache issues) ---
CACHE_URL = env.str("REDIS_CACHE_URL", default="redis://redis:6379/2")
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": CACHE_URL,
        "KEY_PREFIX": env.str("CACHE_KEY_PREFIX", default="core"),
        "TIMEOUT": None,  # Let per-call timeouts control expiry
    }
}

# --- JWT ---
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=12),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=15),
    # Ротация refresh-токенов + чёрный список старых (token_blacklist в INSTALLED_APPS)
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
}

# --- Security, CSRF & CORS ---
# Base (prod) CORS allowlist for our domains
_DEFAULT_CORS_ALLOWED = [
    "https://esai.kg",
    "https://www.esai.kg",
]

# Allow override via env, otherwise use defaults above
CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=_DEFAULT_CORS_ALLOWED)

# Dev-only relaxations
if DEBUG:
    CSRF_TRUSTED_ORIGINS = list(set(CSRF_TRUSTED_ORIGINS + [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://127.0.0.1",
    ]))
    CORS_ALLOWED_ORIGINS = list(set(CORS_ALLOWED_ORIGINS + [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://127.0.0.1",
    ]))

CORS_ALLOW_CREDENTIALS = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"

# Дополнительные заголовки безопасности
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"

# Включать редирект на https по флагу окружения, чтоб не ломать http-only стенды
SECURE_SSL_REDIRECT = env.bool("DJANGO_SECURE_SSL_REDIRECT", default=False)
SECURE_HSTS_SECONDS = 31536000 if not DEBUG else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_HSTS_PRELOAD = not DEBUG

# --- Allauth (Social) ---
# After successful social auth, allauth redirects here (Django path)
# We expose users.urls under "/api/users/", so include that prefix
LOGIN_REDIRECT_URL = "/api/users/auth/complete/"
ACCOUNT_EMAIL_VERIFICATION = "none"
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*", "password2*"]
SOCIALACCOUNT_PROVIDERS = {
    "google": {
        "APP": {
            "client_id": env("GOOGLE_CLIENT_ID", default=""),
            "secret": env("GOOGLE_CLIENT_SECRET", default=""),
            "key": "",
        },
        "SCOPE": ["openid", "email", "profile"],
    },
    "facebook": {
        "METHOD": "oauth2",
        "SCOPE": ["email", "public_profile"],
        "FIELDS": ["id", "email", "name", "first_name", "last_name"],
        "APP": {
            "client_id": env("FACEBOOK_CLIENT_ID", default=""),
            "secret": env("FACEBOOK_CLIENT_SECRET", default=""),
            "key": "",
        },
    },
    "telegram": {
        "APP": {
            "client_id": env("TELEGRAM_BOT_ID", default=""),
            "secret": env("TELEGRAM_BOT_TOKEN", default=""),
            "key": "",
        },
        "AUTH_PARAMS": {
            "auth_date_validity": env.int("TELEGRAM_AUTH_DATE_VALIDITY", default=30),
        },
    },
    "instagram": {
        "APP": {
            "client_id": env("INSTAGRAM_CLIENT_ID", default=""),
            "secret": env("INSTAGRAM_CLIENT_SECRET", default=""),
            "key": "",
        },
    },
}
SOCIALACCOUNT_ADAPTER = "users.adapters.SocialAccountAdapter"
SOCIALACCOUNT_LOGIN_ON_GET = True
# Соц-вход создаёт аккаунт СРАЗУ, без промежуточной формы allauth (Telegram без email).
SOCIALACCOUNT_AUTO_SIGNUP = True
SOCIALACCOUNT_EMAIL_REQUIRED = False
SOCIALACCOUNT_EMAIL_VERIFICATION = "none"

# --- Telegram login (exposed to the frontend widget) ---
# These mirror the values used inside SOCIALACCOUNT_PROVIDERS["telegram"]["APP"].
TELEGRAM_BOT_ID = env("TELEGRAM_BOT_ID", default="")
TELEGRAM_BOT_USERNAME = env("TELEGRAM_BOT_USERNAME", default="")

# --- Email ---
# Почта на домене esai.kg (хостинг satcom). Всё из env, чтобы менять почтовый
# ящик/сервер без правок кода. ВАЖНО: порт 465 = неявный SSL (НЕ STARTTLS), значит
# EMAIL_USE_SSL=True и EMAIL_USE_TLS=False (в Django они взаимоисключающие).
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = env('EMAIL_HOST', default="hosting.satcom.kg")
EMAIL_PORT = env.int('EMAIL_PORT', default=465)
EMAIL_USE_SSL = env.bool('EMAIL_USE_SSL', default=True)
EMAIL_USE_TLS = env.bool('EMAIL_USE_TLS', default=False)
EMAIL_HOST_USER = env('EMAIL_HOST_USER', default="support@esai.kg")
EMAIL_HOST_PASSWORD = env('EMAIL_HOST_PASSWORD')
DEFAULT_FROM_EMAIL = env('DEFAULT_FROM_EMAIL', default="EsAI <support@esai.kg>")

# --- Logging ---
LOG_DIR = Path(os.environ.get("APP_LOG_DIR") or os.environ.get("DJANGO_LOG_DIR") or (BASE_DIR / "logs"))
LOG_FILE = LOG_DIR / "django.log"
LOG_DIR.mkdir(parents=True, exist_ok=True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "%(asctime)s [%(levelname)s] %(name)s:%(lineno)d %(message)s",
        },
        "simple": {
            "format": "%(levelname)s %(message)s",
        },
    },
    "handlers": {
        "file": {
            "level": "WARNING",
            "class": "logging.handlers.RotatingFileHandler",
            "filename": str(LOG_FILE),
            "maxBytes": 5 * 1024 * 1024,
            "backupCount": 5,
            "formatter": "verbose",
            "encoding": "utf-8",
        },
    },
    "root": {
        "handlers": ["file"],
        "level": "WARNING",
    },
    "loggers": {
        "django": {
            "handlers": ["file"],
            "level": "WARNING",
            "propagate": False,
        },
        "django.request": {
            "handlers": ["file"],
            "level": "WARNING",
            "propagate": False,
        },
        "payments.freedompay": {
            "handlers": ["file"],
            "level": "WARNING",
            "propagate": False,
        },
        "audit": {
            "handlers": ["file"],
            "level": "WARNING",
            "propagate": False,
        },
    },
}

# --- Audit / dashboard ---
# ОЦЕНОЧНАЯ ставка стоимости OpenRouter (USD за 1 токен) для дашборда.
# Реальной per-token цены в БД нет — расход считается приблизительно.
AUDIT_OPENROUTER_USD_PER_TOKEN = env.str(
    "AUDIT_OPENROUTER_USD_PER_TOKEN", default="0.0000005"
)

# === DEBUG mode: extra console logging ===
if DEBUG:
    LOGGING["handlers"]["console"] = {
        "level": "DEBUG",
        "class": "logging.StreamHandler",
        "formatter": "simple",
    }
    # ensure file captures DEBUG as well
    LOGGING["handlers"]["file"]["level"] = "DEBUG"
    LOGGING["root"]["handlers"].append("console")
    LOGGING["root"]["level"] = "DEBUG"
    LOGGING["loggers"]["django"]["handlers"].append("console")
    LOGGING["loggers"]["django"]["level"] = "DEBUG"
    LOGGING["loggers"]["payments.freedompay"]["handlers"].append("console")
    LOGGING["loggers"]["payments.freedompay"]["level"] = "DEBUG"

# --- Celery ---
CELERY_BROKER_URL = env.str(
    "CELERY_BROKER_URL", default="redis://redis:6379/0")
CELERY_RESULT_BACKEND = env.str(
    "CELERY_RESULT_BACKEND", default=CELERY_BROKER_URL)
CELERY_TASK_ALWAYS_EAGER = False
CELERY_RESULT_EXTENDED = True
CELERY_RESULT_EXPIRES = 60 * 60 * 24
CELERY_TASK_TIME_LIMIT = env.int("CELERY_TASK_TIME_LIMIT", default=60 * 10)
CELERY_TASK_SOFT_TIME_LIMIT = env.int("CELERY_TASK_SOFT_TIME_LIMIT", default=60 * 9)
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_IMPORTS = ("mails.tasks", "plans.tasks", "users.tasks",)
CELERY_BEAT_SCHEDULE = {
    # Refresh currency rates hourly (kept small; adjust as you prefer)
    "plans:refresh_currency_rates": {
        "task": "plans.tasks.refresh_currency_rates",
        "schedule": timedelta(hours=1),
        "args": (),
    },
    # 3.3 Daily Retention Bonus (ТЗ): раз/24ч доводим баланс не-платных до 800, если <300.
    "plans:apply_daily_retention_bonus": {
        "task": "plans.tasks.apply_daily_retention_bonus",
        "schedule": timedelta(hours=24),
    },
    # 4.3 Анти-фрод: обработка отложенных (pending) welcome-бонусов раз в час.
    "users:process_pending_bonuses": {
        "task": "users.tasks.process_pending_bonuses",
        "schedule": timedelta(hours=1),
    },
    # Сверка оплат: постбэк FreedomPay ненадёжен (для нашего мерчанта не приходит),
    # поэтому каждые 2 мин сами спрашиваем статус у оплаченных, но не начисленных
    # token-заказов и начисляем подтверждённые (идемпотентно). Без этого кредиты
    # после реальной оплаты не поступают. См. payments/tasks.py.
    # Балансы OpenRouter: раз в 5 минут обновляем и, если на рабочем аккаунте
    # кончились деньги, включаем запасной. Без этого сайт встаёт целиком и
    # ждёт, пока человек заметит (см. ai/tasks.py openrouter_autoswitch).
    "ai:openrouter_autoswitch": {
        "task": "ai.tasks.openrouter_autoswitch",
        "schedule": timedelta(minutes=5),
    },
    "payments:reconcile_token_payments": {
        "task": "payments.tasks.reconcile_pending_token_payments",
        "schedule": timedelta(minutes=2),
    },
}

# Подписки отключены: задача plans.tasks.process_due_subscriptions снята с
# расписания beat, а guard внутри самой задачи читает этот флаг и выходит
# раньше времени, если её всё-таки вызовут вручную.
SUBSCRIPTIONS_ENABLED = False

# Public base URL for absolute links in emails
SITE_BASE_URL = env.str("SITE_BASE_URL", default="")

# --- External APIs ---
EXCHANGE_API_BASE = env.str("EXCHANGE_API_BASE",
                            default="https://v6.exchangerate-api.com/v6")
EXCHANGE_API_KEY = env.str("EXCHANGE_API_KEY")

# --- OpenAI timeouts ---
OPENAI_TIMEOUT_SECONDS = env.int("OPENAI_TIMEOUT_SECONDS", default=480)

# === Генерация ВИДЕО в чате (OpenRouter POST /api/v1/videos) ===
# Рядом с image-генерацией: image-модели рисуют в том же чат-потоке, video-модели
# (GPTModels.category == "video") уходят в отдельный submit+poll-эндпоинт.
# VIDEO_GEN_DURATION — длительность ролика в СЕКУНДАХ (уходит в API как duration).
#   Биллинг: у video-моделей markup_coefficient = КРЕДИТОВ ЗА СЕКУНДУ видео
#   (не за 1000 токенов!), списание = ceil(duration * coeff).
# VIDEO_GEN_RESOLUTION — разрешение ролика ("720p").
# VIDEO_GEN_TIMEOUT_S — потолок ожидания poll-цикла, сек (генерация 30–180 с,
#   держим запас; по истечении — ошибка без списания кредитов).
VIDEO_GEN_DURATION = env.int("VIDEO_GEN_DURATION", default=5)
VIDEO_GEN_RESOLUTION = env.str("VIDEO_GEN_RESOLUTION", default="720p")
VIDEO_GEN_TIMEOUT_S = env.int("VIDEO_GEN_TIMEOUT_S", default=480)

# --- Guest (anonymous) chat free quota ---
# Number of free chat requests an unauthenticated visitor gets before being
# asked to sign in. Counted in the cache backend (Redis) keyed by guest id / IP.
GUEST_FREE_REQUESTS = env.int("GUEST_FREE_REQUESTS", default=3)


# === EsAI: тарифные правила / биллинг (Этап 3, ТЗ клиента) ===
# Тиры: guest (аноним) / free (вошёл, не платил) / paid (>=1 оплата). См. plans/tiers.py.

# 4.1 «Бесплатная» модель — теперь задаётся ЯВНЫМ флагом GPTModels.free_tier
#     (админка), а НЕ коэффициентом. markup_coefficient теперь = ТАРИФ (кредитов за
#     1000 токенов), и у бесплатной модели он может быть >1 (напр. Gemini=11).
#     FREE_MODEL_MAX_COEFF оставлен как legacy-фолбэк (если у модели нет флага).
FREE_MODEL_MAX_COEFF = env.float("FREE_MODEL_MAX_COEFF", default=1.0)

# НОРМАЛИЗАЦИЯ БИЛЛИНГА (тариф владельца продукта): markup_coefficient — кредитов за 1000 токенов,
# поэтому списание = ceil(total_tokens * coeff / TOKEN_CREDIT_DIVISOR). Делитель
# единый для ВСЕХ конвертаций токены→кредиты (списание, пред-чек баланса, cap
# вывода, estimated_min_charge), иначе гейты разъедутся со списанием.
TOKEN_CREDIT_DIVISOR = env.int("TOKEN_CREDIT_DIVISOR", default=1000)

# 1.3 Пред-оценка стоимости запроса (анти-«кассовый разрыв»): минимально
#     резервируемое число токенов. Блок ДО запроса, если баланс < estimate*coeff.
MIN_REQUEST_ESTIMATE_TOKENS = env.int("MIN_REQUEST_ESTIMATE_TOKENS", default=600)

# === Калькулятор ценности кредитов ("На что хватит пакета", plans/credit_value.py) ===
# Эталонные модели для перевода "кредиты пакета" -> "единицы результата"
# (сообщений/картинок/видео/страниц). Каждое значение — openrouter_id модели
# из GPTModels; переопределяемо в рантайме через админку (adminapi.runtime,
# ключи credit_calc_*_model) БЕЗ рестарта — эти env-константы лишь фолбэк.
#
# CREDIT_CALC_TEXT_MODEL_ID: эталон для категории "текст" — сама GPT-5.4 mini
# (openai/gpt-5.4-mini, markup_coefficient=0.426) — самая дешёвая/бытовая
# модель из линейки GPT-5.4, точное совпадение с пожеланием клиента.
CREDIT_CALC_TEXT_MODEL_ID = env.str(
    "CREDIT_CALC_TEXT_MODEL_ID", default="openai/gpt-5.4-mini")

# CREDIT_CALC_IMAGE_MODEL_ID: эталон для категории "изображения" — FLUX Pro
# (black-forest-labs/flux.2-pro, markup_coefficient=4.000, плоское списание
# max(1, int(coeff)) кредитов/картинку) — точное совпадение с пожеланием клиента.
CREDIT_CALC_IMAGE_MODEL_ID = env.str(
    "CREDIT_CALC_IMAGE_MODEL_ID", default="black-forest-labs/flux.2-pro")

# CREDIT_CALC_VIDEO_MODEL_ID: эталон для категории "видео" — САМАЯ ДЕШЁВАЯ
# по markup_coefficient среди активных видео-моделей на момент написания —
# Grok Video (x-ai/grok-imagine-video, markup_coefficient=15.000 кр/сек),
# дешевле Veo 3.1 Lite/Hailuo 2.3 (17.000). Показываем клиенту "минимум,
# на что хватит", а не оптимистичную/дорогую модель.
CREDIT_CALC_VIDEO_MODEL_ID = env.str(
    "CREDIT_CALC_VIDEO_MODEL_ID", default="x-ai/grok-imagine-video")

# CREDIT_CALC_DOCUMENT_MODEL_ID: эталон для категории "документы/страницы" —
# та же текстовая модель (документ биллится по той же токенной формуле,
# что и обычный текст, см. credits_per_unit('document')).
CREDIT_CALC_DOCUMENT_MODEL_ID = env.str(
    "CREDIT_CALC_DOCUMENT_MODEL_ID", default=CREDIT_CALC_TEXT_MODEL_ID)

# Сколько токенов в одной "странице" документа для расчёта credits_per_unit
# категории 'document'. ~500 слов/страница — стандартная оценка книгоиздания,
# ~1.3 токена/слово (GPT-семейство) -> ~650 токенов/страница.
CREDIT_CALC_DOCUMENT_TOKENS_PER_PAGE = env.int(
    "CREDIT_CALC_DOCUMENT_TOKENS_PER_PAGE", default=650)

# CREDIT_CALC_TEXT_TOKENS_PER_REPLY: "типичный" размер ОДНОГО текстового
# сообщения (вход+выход) для расчёта credits_per_unit('text'/'document') —
# НЕ используем estimated_min_charge() (plans/wallet.py) для этого: та функция
# считает МИНИМАЛЬНУЮ пред-оценку для гейта "хватит ли баланса вообще" (её
# собственный докстринг это прямо говорит), а не типичную стоимость сообщения
# в развивающемся диалоге с историей (до 10 пар Q/A уходят в промпт, см.
# ai/handlers.py MAX_HISTORY_MESSAGES) — с ней per_unit_text занижался почти
# до 1 кредита/"ответ" на дешёвых моделях, завышая обещанное число ответов.
#
# ЭТО ОЦЕНКА, не измеренное значение: на момент введения (2026-07-15) реальных
# исторических списаний по эталонной модели (openai/gpt-5.4-mini, см.
# CREDIT_CALC_TEXT_MODEL_ID) в леджере TokenTransaction практически нет (1
# запись, 550 токенов) — недостаточно для медианы/среднего. Ориентир —
# АГРЕГИРОВАННАЯ статистика total_tokens по ВСЕМ моделям за последние ~2000
# списаний reason='chat' (p75 ≈ 2128 токенов, median ≈ 817, mean ≈ 1698).
# Дефолт 2500 — верхняя граница согласованного диапазона 2000-2500, а не p75
# как есть: у markup_coefficient=0.426 (самый дешёвый тариф в линейке) ceil()
# округляет к 1 кредиту вплоть до ~2348 токенов включительно — то есть более
# "экономные" оценки внутри диапазона (2000-2350) визуально ничем не
# отличались бы от старой заниженной оценки (estimated_min_charge), которую
# как раз чиним. Берём с запасом, чтобы результат ощутимо отражал реальный
# многоходовый диалог с историей (до 10 пар Q/A уходят в промпт, см.
# ai/handlers.py MAX_HISTORY_MESSAGES; контекстное окно до 8000 токенов, см.
# CONTEXT_HISTORY_TOKEN_BUDGET), а не первое короткое сообщение.
# ПЕРЕСМОТРЕТЬ, когда по gpt-5.4-mini накопится достаточно собственной
# истории (см. project_esai_platform_ux).
CREDIT_CALC_TEXT_TOKENS_PER_REPLY = env.int(
    "CREDIT_CALC_TEXT_TOKENS_PER_REPLY", default=2500)

# CREDIT_CALC_IMAGE_*_TOKENS_ESTIMATE: оценка вход/выход-токенов для
# НЕ-FLUX image-моделей (Nano Banana family: google/gemini-2.5-flash-image,
# google/gemini-3-pro-image), которые билятся ТОКЕННОЙ формулой как текст
# (см. ai/handlers.py _call_chat_completions_with_fallback: "картинка ~1300
# output-токенов, cap 1000 его обрежет" — та же цифра переиспользована здесь).
# PROMPT — короткий промпт генерации картинки ("нарисуй кота в стиле ..."),
# заведомо короче типичного текстового сообщения с историей чата.
CREDIT_CALC_IMAGE_OUTPUT_TOKENS_ESTIMATE = env.int(
    "CREDIT_CALC_IMAGE_OUTPUT_TOKENS_ESTIMATE", default=1300)
CREDIT_CALC_IMAGE_PROMPT_TOKENS_ESTIMATE = env.int(
    "CREDIT_CALC_IMAGE_PROMPT_TOKENS_ESTIMATE", default=150)

# CREDIT_CALC_<CATEGORY>_MIN_COUNT: пороги "разумно полезного объёма" для
# калькулятора "На что хватит?" (Этап 3, п.14) — используются, чтобы решить,
# какой пакет РЕКОМЕНДОВАТЬ под выбранный клиентом сценарий использования (см.
# plans/credit_value.py _mark_recommended). Пакет считается "достаточным" для
# категории, если его value.<category>.count >= порога; из достаточных
# выбирается САМЫЙ ДЕШЁВЫЙ, а если ни один не достиг порога — САМЫЙ ДОРОГОЙ
# активный пакет (обычно "Максимум"). Переопределяемо в рантайме из админки
# без рестарта (adminapi.runtime, ключи credit_calc_<category>_min_count) —
# эти env-константы лишь фолбэк. Согласовано с клиентом 2026-07-16.
CREDIT_CALC_TEXT_MIN_COUNT = env.int("CREDIT_CALC_TEXT_MIN_COUNT", default=200)
CREDIT_CALC_IMAGE_MIN_COUNT = env.int("CREDIT_CALC_IMAGE_MIN_COUNT", default=100)
CREDIT_CALC_VIDEO_MIN_COUNT = env.int("CREDIT_CALC_VIDEO_MIN_COUNT", default=5)
CREDIT_CALC_DOCUMENT_MIN_COUNT = env.int("CREDIT_CALC_DOCUMENT_MIN_COUNT", default=200)

# 4.2 Контекстное окно: макс. длина ОДНОГО ответа (символы) для не-платных.
FREE_MAX_OUTPUT_CHARS = env.int("FREE_MAX_OUTPUT_CHARS", default=1200)

# === Контекст диалога: токен-бюджет окна + rolling-резюме ===
# Свежие сообщения уходят в модель ДОСЛОВНО, пока влезают в этот бюджет (токены).
# Всё, что старше, представлено компактным резюме (context_summary сессии),
# которое обновляется фоном дешёвой моделью. Так чат может расти до тысяч
# сообщений без потери контекста и без роста стоимости/задержки ответа.
CONTEXT_SUMMARY_ENABLED = env.bool("CONTEXT_SUMMARY_ENABLED", default=True)
# Бюджет «свежего окна» в токенах (эвристика ~chars/3, как в _estimate_prompt_tokens).
CONTEXT_HISTORY_TOKEN_BUDGET = env.int("CONTEXT_HISTORY_TOKEN_BUDGET", default=8000)
# Сколько последних строк истории вообще грузить из БД (страховка от тысяч строк).
CONTEXT_MAX_HISTORY_ROWS = env.int("CONTEXT_MAX_HISTORY_ROWS", default=400)
# Дешёвая модель для сворачивания старой части (та же, что у памяти).
CONTEXT_SUMMARY_MODEL = env.str("CONTEXT_SUMMARY_MODEL", default="google/gemini-2.5-flash")
# Потолок длины резюме (символы) — держим его компактным и предсказуемым.
CONTEXT_SUMMARY_MAX_CHARS = env.int("CONTEXT_SUMMARY_MAX_CHARS", default=4000)
# Страховка от неограниченного роста несвёрнутого «хвоста» в summarize_session_context
# (ai/tasks.py): если фоновая задача отстаёт (сбои LLM-вызова, простой celery,
# временное выключение CONTEXT_SUMMARY_ENABLED), хвост не должен расти без предела —
# иначе один payload суммаризации рано или поздно превысит контекстное окно модели
# и вызов начнёт падать на каждом прогоне, навсегда застряв. Обрабатываем backlog
# порциями (самые старые сообщения сначала) — за несколько прогонов он рассосётся.
CONTEXT_SUMMARY_MAX_TAIL_ROWS = env.int("CONTEXT_SUMMARY_MAX_TAIL_ROWS", default=500)

# Жёсткий потолок длины ответа (токены) — биллинг чата использует его как
# верхнюю границу max_output_tokens, чтобы один запрос не выжег баланс.
MAX_OUTPUT_TOKENS_HARD_CAP = env.int("MAX_OUTPUT_TOKENS_HARD_CAP", default=1000)

# 3.3 Daily Retention Bonus: если у не-платного баланс < THRESHOLD → довести до TARGET.
# После нормализации ÷1000: довести до 1 кредита (≈ старые 800). Тюнится через env.
DAILY_RETENTION_THRESHOLD = env.int("DAILY_RETENTION_THRESHOLD", default=1)
DAILY_RETENTION_TARGET = env.int("DAILY_RETENTION_TARGET", default=1)

# 5.1 Дневные лимиты запросов: free / paid (soft).
FREE_DAILY_REQUESTS = env.int("FREE_DAILY_REQUESTS", default=20)
PAID_DAILY_REQUESTS = env.int("PAID_DAILY_REQUESTS", default=300)

# Тестовый вход платёжной системы (users/views.py): фикс. email+код без письма.
# ВЫКЛЮЧЕН по умолчанию (пустая строка = бэкдор не активен). Включать ТОЛЬКО
# явно в .env тестового/dev-окружения — никогда не оставлять дефолт непустым,
# иначе это боевой обход OTP под угадываемой парой email/код.
TEST_LOGIN_EMAIL = env.str("TEST_LOGIN_EMAIL", default="")
TEST_LOGIN_CODE = env.str("TEST_LOGIN_CODE", default="")

# 4.3 Анти-фрод: порог регистраций с одного IP за 24ч → welcome-бонус в pending.
ANTIFRAUD_SIGNUPS_PER_IP_24H = env.int("ANTIFRAUD_SIGNUPS_PER_IP_24H", default=3)
ANTIFRAUD_BONUS_PENDING_HOURS = env.int("ANTIFRAUD_BONUS_PENDING_HOURS", default=24)

# Веб-поиск (OpenRouter :online / Perplexity) тарифицируется ОТДЕЛЬНО (~$0.005/запрос)
# и НЕ ловится токенной формулой → фикс. надбавка в кредитах за запрос с веб-поиском.
# После нормализации ÷1000 масштаб кредитов мелкий (ответ ~2..30 кр), поэтому старая
# надбавка 1000 здесь огромна — приведена к новому масштабу. Тюнится через env.
WEB_SEARCH_SURCHARGE_CREDITS = env.int("WEB_SEARCH_SURCHARGE_CREDITS", default=2)

# === Память пользователя (как у ChatGPT/Anthropic) ===
# MEMORY_MAX_FACTS — кап числа хранимых фактов на пользователя (лишние режутся по
#   наименьшей важности / самым старым). MEMORY_INJECT_MAX_CHARS — бюджет символов
#   блока памяти, инъектируемого в системный промпт. MEMORY_EXTRACT_MODEL — дешёвая
#   модель OpenRouter для фонового извлечения фактов (см. users/tasks.extract_user_memory).
MEMORY_MAX_FACTS = env.int("MEMORY_MAX_FACTS", default=50)
MEMORY_INJECT_MAX_CHARS = env.int("MEMORY_INJECT_MAX_CHARS", default=1500)
MEMORY_EXTRACT_MODEL = env.str("MEMORY_EXTRACT_MODEL", default="google/gemini-2.5-flash")

# === Web Push (VAPID) ===
# Ежедневный пуш «зачислен бонус» и прочие web-push уведомления (Push API).
# VAPID_PUBLIC_KEY также отдаётся во фронт как NEXT_PUBLIC_VAPID_PUBLIC_KEY
# (тот же самый ключ) — им браузер подписывается на пуши. Приватный ключ
# (raw base64url) задаётся ТОЛЬКО в .env и на фронт не попадает.
VAPID_PUBLIC_KEY = env.str("VAPID_PUBLIC_KEY", default="BPn53NaOSbOmmEEEtQ1zrQMwN2eO9a5947AOJXA5QM3_0clMN3vPNVZi7trvhi95NY1zwJP3xRmrLZXpvuIxJF8")
VAPID_PRIVATE_KEY = env.str("VAPID_PRIVATE_KEY", default="")  # raw base64url, задаю в .env
VAPID_SUBJECT = env.str("VAPID_SUBJECT", default="mailto:support@esai.kg")


# --- FreedomPay settings ---
FREEDOM_PAY_MERCHANT_ID = env.str("FREEDOM_PAY_MERCHANT_ID", default="")
FREEDOM_PAY_API_BASE = env.str("FREEDOM_PAY_API_BASE", default="https://api.freedompay.com/v1")
FREEDOM_PAY_TOKEN = env.str("FREEDOM_PAY_TOKEN", default="")
FREEDOM_PAY_INIT_PAYMENT_URL = env.str(
    "FREEDOM_PAY_INIT_PAYMENT_URL",
    default="https://api.freedompay.kg/init_payment",
)
FP_API_BASE = env.str("FP_API_BASE", default=FREEDOM_PAY_API_BASE)
FP_MERCHANT_ID = env.str("FP_MERCHANT_ID", default=FREEDOM_PAY_MERCHANT_ID)

# --- ЮKassa (оплата в рублях) -------------------------------------------------
# FreedomPay принимает сомы (KGS) — для рублёвых платежей клиент подключил
# ЮKassa. Валюта выбирается пользователем на /pricing: KGS -> FreedomPay,
# RUB -> ЮKassa. Ключ ТОЛЬКО из окружения, в репозиторий не попадает.
YOOKASSA_SHOP_ID = env.str("YOOKASSA_SHOP_ID", default="")
YOOKASSA_SECRET_KEY = env.str("YOOKASSA_SECRET_KEY", default="")
YOOKASSA_API_URL = env.str("YOOKASSA_API_URL", default="https://api.yookassa.ru/v3")
