"""Настройки единого QR (GoPay): режим, среда, ключи, срок жизни счёта.

Значения читаются в порядке «админка -> окружение» (adminapi.runtime), как
ключи NOWPayments: подменить ключ на проде можно из панели, не трогая .env.
Наружу секреты не отдаются никогда: у публичного API-ключа видны последние
четыре символа, у двух секретов — только «задан / не задан».

Режим не булев:
  off   — способа нет ни у кого;
  staff — виден только сотрудникам;
  on    — открыт всем.
Среда — какая пара ключей работает: test или live. С тестовой парой способ
доступен ТОЛЬКО сотрудникам при любом режиме: тестовый ключ имитирует оплату
без денег, и обычный покупатель не должен получить за неё кредиты.

Где лежат ключи, честно: открытым текстом в таблице AppSetting (значит, и в
дампах базы) и до 30 секунд в общем Redis под appset:<KEY>. Так же, как ключи
NOWPayments; шифрования на хранении в проекте нет.

Чтение не бросает исключений и при сбое кэша или базы возвращает значение из
settings. Поэтому два чтения в одном запросе могут разойтись — и правило
«тест только сотрудникам» повторено там, где счёт создаётся и где зачисляется.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from django.conf import settings

MODE_OFF, MODE_STAFF, MODE_ON = "off", "staff", "on"
MODES = (MODE_OFF, MODE_STAFF, MODE_ON)
ENV_TEST, ENV_LIVE = "test", "live"
ENVS = (ENV_TEST, ENV_LIVE)
# Границы срока жизни — границы самого GoPay (lifetime 300…86400 секунд).
LIFETIME_MIN_MINUTES, LIFETIME_MAX_MINUTES, LIFETIME_DEFAULT_MINUTES = 5, 1440, 15
WEBHOOK_PATH = "/api/payments/gopay/webhook/"
# GoPay шлёт только те события, что отмечены в кабинете: без этих четырёх счёт
# не закроется по вебхуку. Список показывает админка рядом с адресом.
WEBHOOK_EVENTS = ("payment.committed", "payment.failed", "payment.expired", "payment.cancelled")
# Нужен, только если в кабинете GoPay включена онлайн-касса.
WEBHOOK_EVENTS_OPTIONAL = ("receipt.sent",)
SECRET_FIELDS = ("api_key", "api_secret", "webhook_secret")
RT_MODE, RT_ENV, RT_LIFETIME, RT_SEND_BUYER_EMAIL = \
    "gopay_mode", "gopay_env", "gopay_lifetime_minutes", "gopay_send_buyer_email"
# Печатные символы ASCII без пробелов: ключ уходит в HTTP-заголовок, а пробел
# внутри почти всегда означает неудачную вставку из буфера.
SECRET_RE = re.compile(r"[\x21-\x7E]{8,256}")

_TRUE_WORDS = ("1", "true", "yes", "on")


def _runtime(key: str, default):
    try:
        from adminapi.runtime import get_runtime

        return get_runtime(key, default)
    except Exception:  # noqa: BLE001 — настройки не должны ронять оплату
        return default


def runtime_key(env: str, field: str) -> str:
    """Имя настройки с секретом: ("test", "api_key") -> "GOPAY_TEST_API_KEY"."""
    if env not in ENVS or field not in SECRET_FIELDS:
        raise ValueError("gopay: неизвестная среда или поле ключа")
    return f"GOPAY_{env.upper()}_{field.upper()}"


@dataclass(frozen=True, repr=False)
class Credentials:
    env: str
    api_key: str
    api_secret: str
    webhook_secret: str

    @property
    def complete(self) -> bool:
        """Хватает ли ключей, чтобы подписать запрос (секрет вебхуков тут не нужен)."""
        return bool(self.api_key and self.api_secret)

    def __repr__(self) -> str:
        # Объект может попасть в трейсбек или отладочный вывод — значений в нём
        # быть не должно.
        secrets = "set" if (self.api_secret or self.webhook_secret) else "unset"
        return (f"Credentials(env={self.env!r}, api_key={mask_tail(self.api_key)!r}, "
                f"secrets={secrets})")

    __str__ = __repr__


def mode() -> str:
    value = str(_runtime(RT_MODE, str(getattr(settings, "GOPAY_MODE", MODE_STAFF)))).strip().lower()
    # Непонятное значение — выключено: опечатка в .env не должна открыть способ всем.
    return value if value in MODES else MODE_OFF


def env() -> str:
    value = str(_runtime(RT_ENV, str(getattr(settings, "GOPAY_ENV", ENV_TEST)))).strip().lower()
    # Непонятное значение — тест: в тесте счёт получит только сотрудник.
    return value if value in ENVS else ENV_TEST


# У credentials() параметр зовётся env (так его передают по имени) и внутри
# заслоняет функцию — активную среду там читаем через это имя.
_active_env = env


def _as_int(value):
    if isinstance(value, bool):
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def lifetime_minutes() -> int:
    raw = _runtime(RT_LIFETIME, "")
    minutes = _as_int(raw) if str(raw).strip() else None
    if minutes is None:
        minutes = _as_int(getattr(settings, "GOPAY_LIFETIME_MINUTES", LIFETIME_DEFAULT_MINUTES))
    if minutes is None:
        minutes = LIFETIME_DEFAULT_MINUTES
    return max(LIFETIME_MIN_MINUTES, min(LIFETIME_MAX_MINUTES, minutes))


def lifetime_seconds() -> int:
    return lifetime_minutes() * 60


def send_buyer_email() -> bool:
    """Передавать ли GoPay почту покупателя (для чека и чтобы его страница не спрашивала контакт)."""
    value = _runtime(RT_SEND_BUYER_EMAIL, bool(getattr(settings, "GOPAY_SEND_BUYER_EMAIL", True)))
    if isinstance(value, str):
        return value.strip().lower() in _TRUE_WORDS
    return bool(value)


def api_base_url() -> str:
    """Адрес API GoPay — только из settings, из админки он не меняется.

    Запрос несёт ключ и подпись, поэтому по http он не уходит никогда: при
    неверном адресе возвращается пустая строка, и клиент считает GoPay
    не настроенным. Исключение — локальная отладка (DEBUG).
    """
    url = str(getattr(settings, "GOPAY_API_URL", "") or "").strip().rstrip("/")
    if url.startswith("https://"):
        return url
    if url.startswith("http://") and getattr(settings, "DEBUG", False):
        return url
    return ""


def credentials(env: str | None = None) -> Credentials:
    current = env if env is not None else _active_env()
    if current not in ENVS:
        raise ValueError("gopay: неизвестная среда")

    def read(field: str) -> str:
        key = runtime_key(current, field)
        return str(_runtime(key, str(getattr(settings, key, "") or "")) or "").strip()

    return Credentials(env=current, api_key=read("api_key"), api_secret=read("api_secret"),
                       webhook_secret=read("webhook_secret"))


def is_configured(env: str | None = None) -> bool:
    try:
        return credentials(env).complete
    except ValueError:
        return False


def webhook_secrets() -> list[tuple[str, str]]:
    """Секреты вебхуков, которыми можно проверить подпись: активная среда первой.

    Один ли секрет у точки или свой на каждую среду, документация GoPay не
    говорит — поэтому храним до двух и пробуем оба.
    """
    active = env()
    result = []
    for name in (active, *[e for e in ENVS if e != active]):
        secret = credentials(name).webhook_secret
        if secret:
            result.append((name, secret))
    return result


def is_staff_user(user) -> bool:
    try:
        return bool(user is not None and getattr(user, "is_authenticated", False)
                    and (getattr(user, "is_staff", False) or getattr(user, "is_superuser", False)))
    except Exception:  # noqa: BLE001 — проверка прав не должна ронять оплату
        return False


def enabled_for(is_staff: bool) -> bool:
    """Единственное правило доступности способа."""
    m, e = mode(), env()
    if m == MODE_OFF or not is_configured(e):
        return False
    if e == ENV_TEST:
        # Тестовая среда: только сотрудники, каким бы ни был режим.
        return bool(is_staff)
    if m == MODE_ON:
        return True
    return bool(is_staff)


def is_enabled_for(user=None) -> bool:
    return enabled_for(is_staff_user(user))


def webhook_url() -> str:
    """Адрес для кабинета GoPay.

    Только из настроек: заголовок Host подделывается, и адрес, собранный из
    запроса, увёл бы уведомления о наших оплатах на чужой сервер.
    """
    base = str(getattr(settings, "SITE_BASE_URL", "") or "").strip().rstrip("/")
    return f"{base}{WEBHOOK_PATH}" if base else ""


def mask_tail(value: str) -> str:
    value = str(value or "")
    if not value:
        return ""
    # У короткого значения четыре символа — уже половина ключа.
    if len(value) < 8:
        return "…"
    return "…" + value[-4:]


def clean_secret(value) -> str:
    """Проверить ключ, введённый в админке. Пустая строка — «удалить».

    Текст ошибки не повторяет значение: он уходит в ответ и в журнал.
    """
    if not isinstance(value, str):
        raise ValueError("ожидается строка")
    value = value.strip()
    if not value:
        return ""
    if not SECRET_RE.fullmatch(value):
        raise ValueError("от 8 до 256 печатных латинских символов без пробелов")
    return value


def _api_host() -> str:
    try:
        return urlsplit(api_base_url()).hostname or ""
    except ValueError:
        return ""


def public_state() -> dict:
    """Настройки GoPay для админки — без единого значения секрета."""
    current = env()
    state = {
        "mode": mode(),
        "env": current,
        "lifetime_minutes": lifetime_minutes(),
        "send_buyer_email": send_buyer_email(),
        "configured": is_configured(current),
        "effective": {"public": enabled_for(False), "staff": enabled_for(True)},
        "webhook_url": webhook_url(),
        "webhook_events": list(WEBHOOK_EVENTS),
        "webhook_events_optional": list(WEBHOOK_EVENTS_OPTIONAL),
        "api_host": _api_host(),
    }
    for name in ENVS:
        creds = credentials(name)
        state[name] = {
            "api_key_set": bool(creds.api_key),
            "api_key_tail": mask_tail(creds.api_key),
            "api_secret_set": bool(creds.api_secret),
            "webhook_secret_set": bool(creds.webhook_secret),
        }
    return state
