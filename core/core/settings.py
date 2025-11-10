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

ALLOWED_HOSTS = env.list(
    "DJANGO_ALLOWED_HOSTS",
    default=["localhost", "127.0.0.1"],
)

# Behind nginx reverse proxy: trust X-Forwarded-Proto
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# CSRF trusted origins
_DEFAULT_CSRF_TRUSTED = [
    "https://vokalo.kg",
    "https://www.vokalo.kg",
    "https://vokalo.online",
    "https://www.vokalo.online",
    "https://vokalo.ru",
    "https://www.vokalo.ru",
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

    # Auth (Google)
    "corsheaders",
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.google",

    # Project apps
    "mails.apps.MailsConfig",
    "users.apps.UsersConfig",
    "content.apps.ContentConfig",
    "ai.apps.AiConfig",
    "plans.apps.PlansConfig",
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
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
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
    "ACCESS_TOKEN_LIFETIME": timedelta(days=7),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=15),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
}

# --- Security, CSRF & CORS ---
# Base (prod) CORS allowlist for our three domains
_DEFAULT_CORS_ALLOWED = [
    "https://vokalo.kg",
    "https://www.vokalo.kg",
    "https://vokalo.online",
    "https://www.vokalo.online",
    "https://vokalo.ru",
    "https://www.vokalo.ru",
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

# --- Allauth (Google) ---
# After successful Google auth, allauth redirects here (Django path)
# We expose users.urls under "/api/users/", so include that prefix
LOGIN_REDIRECT_URL = "/api/users/auth/complete/"
ACCOUNT_EMAIL_VERIFICATION = "none"
ACCOUNT_AUTHENTICATION_METHOD = "email"
ACCOUNT_EMAIL_REQUIRED = True
SOCIALACCOUNT_PROVIDERS = {
    "google": {
        "APP": {
            "client_id": env("GOOGLE_CLIENT_ID", default=""),
            "secret": env("GOOGLE_CLIENT_SECRET", default=""),
            "key": "",
        },
        "SCOPE": ["openid", "email", "profile"],
    }
}

# --- Email ---
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = "smtp.gmail.com"
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = env('EMAIL_HOST_USER', default="vokalo.online")
EMAIL_HOST_PASSWORD = env('EMAIL_HOST_PASSWORD')
DEFAULT_FROM_EMAIL = env('DEFAULT_FROM_EMAIL')

# --- Logging ---
LOG_DIR = BASE_DIR / "logs"
LOG_FILE = LOG_DIR / "django.log"
LOG_PAYMENTS_FILE = LOG_DIR / "payments.log"
LOG_DIR.mkdir(exist_ok=True)
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {"format": "[{levelname}] {asctime} {name} | {message}", "style": "{"},
        "simple": {"format": "[{levelname}] {message}", "style": "{"},
    },
    "handlers": {
        "file": {"level": "DEBUG", "class": "logging.FileHandler", "filename": str(LOG_FILE), "formatter": "verbose"},
        "payments_file": {"level": "INFO", "class": "logging.FileHandler", "filename": str(LOG_PAYMENTS_FILE), "formatter": "verbose"},
    },
    "loggers": {
        "django": {"handlers": ["file"], "level": "DEBUG", "propagate": True},
        # Project app loggers -> write to files
        "plans": {"handlers": ["file"], "level": "INFO", "propagate": False},
        # Dedicated payments logger always writes to payments.log even when DEBUG=False
        "payments": {"handlers": ["payments_file"], "level": "INFO", "propagate": False},
    },
}
if DEBUG:
    LOGGING["handlers"]["console"] = {
        "level": "DEBUG", "class": "logging.StreamHandler", "formatter": "simple"}
    LOGGING["loggers"]["django"]["handlers"].append("console")
    # Also mirror our project loggers to console in DEBUG
    for _name in ("plans", "payments"):
        LOGGING["loggers"].setdefault(_name, {"handlers": ["file"], "level": "INFO", "propagate": False})
        LOGGING["loggers"][_name]["handlers"].append("console")

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
CELERY_IMPORTS = ("mails.tasks", "plans.tasks",)
CELERY_BEAT_SCHEDULE = {
    # Check and renew subscriptions frequently
    "plans:process_due_subscriptions": {
        "task": "plans.tasks.process_due_subscriptions",
        "schedule": timedelta(minutes=10),
    },
    # Refresh currency rates hourly (kept small; adjust as you prefer)
    "plans:refresh_currency_rates": {
        "task": "plans.tasks.refresh_currency_rates",
        "schedule": timedelta(hours=1),
        "args": (),
    },
}

# Public base URL for absolute links in emails
SITE_BASE_URL = env.str("SITE_BASE_URL", default="")

# --- External APIs ---
EXCHANGE_API_BASE = env.str("EXCHANGE_API_BASE",
                            default="https://v6.exchangerate-api.com/v6")
EXCHANGE_API_KEY = env.str("EXCHANGE_API_KEY")

# --- OpenAI timeouts ---
OPENAI_TIMEOUT_SECONDS = env.int("OPENAI_TIMEOUT_SECONDS", default=480)
