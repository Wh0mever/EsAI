"""Внешние ссылки Академии: ссылка на курс и ссылка кнопки «Предложить курс».

Ссылки вводят сотрудники, а открывают посетители esai.kg — пропущенный
javascript:/data: или адрес внутренней сети стал бы XSS или фишингом с нашего
домена. Поэтому правила строгие, и публичный API проверяет ссылку ещё раз:
строку в базе могли поправить мимо панели.

Доступность сайта сервер не проверяет: запрос по введённому адресу — это
SSRF, а многие сайты отвечают ботам 403/429 (ложные тревоги).
"""
from __future__ import annotations

import ipaddress
import re
import unicodedata
from urllib.parse import urlsplit

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator

URL_MAX = 1000
SUGGEST_MAX = 300
SUGGEST_KEY = "academy_suggest_url"

MSG_SCHEME = "Ссылка должна начинаться с https:// или http://"
MSG_USERINFO = "В ссылке не должно быть логина и пароля (user:pass@)"
MSG_LOCAL = "Ссылка ведёт на внутренний адрес — нужен адрес сайта в интернете"
MSG_INVALID = "Ссылка на курс — адрес сайта вида https://example.com/kurs"
MSG_SUGGEST = "Ссылка для кнопки — @имя, t.me/имя или адрес сайта с https://"

# Пробелы, управляющие символы и обратная косая: браузер читает «\» как «/»,
# и хост в его понимании разошёлся бы с нашим.
_BAD_CHARS = re.compile(r"[\s\x00-\x1f\x7f\\]")
_SCHEME = re.compile(r"^([A-Za-z][A-Za-z0-9+.\-]*)://")
# «example.com/kurs», «курсы.рф» — адрес без схемы, к нему подставляем https://.
_DOMAIN_LIKE = re.compile(r"^[^/?#:@\s]+\.[^/?#:@\s.]+(?::\d{1,5})?(?:[/?#]|$)")
_LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")
_TLD = re.compile(r"^(?:[a-z]{2,63}|xn--[a-z0-9-]{1,59})$")
# Числовая последняя метка — браузер читает такой хост как IPv4 (127.1, 0x7f.1).
_NUMERIC_TLD = re.compile(r"^(?:\d+|0x[0-9a-f]*)$")
# «Отклоняющиеся» буквы IDNA: Python (IDNA2003) пишет straße.de как strasse.de, а
# браузер (UTS46) открывает xn--strae-oqa.de — панель показала бы не тот хост.
_IDNA_DEVIATION = re.compile("[ßẞς]")  # ß ẞ ς
_LOCAL_ZONES = frozenset({
    "localhost", "local", "internal", "intranet", "lan", "home", "corp", "test", "invalid",
    "example", "arpa", "onion",
})
_TG_NAME = re.compile(r"^@?([A-Za-z][A-Za-z0-9_]{3,31})$")
_TG_HOST = re.compile(
    r"^(?:https?://)?(?:www\.)?(?:t\.me|telegram\.me|telegram\.dog)(?=[/?#]|$)(.*)$", re.I)
_TG_TAIL = re.compile(r"^/[A-Za-z0-9_+\-]+(?:/[A-Za-z0-9_\-]+)*/?(?:\?[A-Za-z0-9_=&\-]*)?$")

_django_check = URLValidator(schemes=["http", "https"])


class LinkError(ValueError):
    """Ссылка не подходит: код для фронта и текст человеку."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _hidden_chars(value: str) -> bool:
    # Невидимые символы и переключатели направления текста (U+202E и т. п.):
    # с ними ссылка в панели выглядит не тем, куда ведёт.
    return any(unicodedata.category(ch) in ("Cc", "Cf", "Zl", "Zp") for ch in value)


def _local() -> LinkError:
    return LinkError("url_local", MSG_LOCAL)


def _invalid() -> LinkError:
    return LinkError("url_invalid", MSG_INVALID)


def _host(value: str) -> str:
    """Хост ссылки в ASCII (punycode) после всех проверок, иначе LinkError."""
    try:
        parts = urlsplit(value)
        port = parts.port
        host = parts.hostname or ""
    except ValueError:
        raise _invalid() from None
    if "@" in parts.netloc:
        raise LinkError("url_userinfo", MSG_USERINFO)
    if not host or port == 0 or _IDNA_DEVIATION.search(parts.netloc):
        raise _invalid()
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None:
        # Нужен адрес сайта, а не IP: внутренний — отдельным текстом.
        raise _invalid() if ip.is_global else _local()
    host = host[:-1] if host.endswith(".") else host
    if "." not in host:
        raise _local()
    try:
        ascii_host = host.encode("idna").decode("ascii").lower()
    except UnicodeError:
        raise _invalid() from None
    labels = ascii_host.split(".")
    if len(ascii_host) > 253 or not all(_LABEL.match(label) for label in labels):
        raise _invalid()
    tld = labels[-1]
    if _NUMERIC_TLD.match(tld):
        raise _local()
    if not _TLD.match(tld):
        raise _invalid()
    if tld in _LOCAL_ZONES:
        raise _local()
    return ascii_host


def clean_url(raw: str, *, https_only: bool = False, limit: int = URL_MAX) -> str:
    """Ссылка на сайт в интернете: схема в нижнем регистре, без схемы — https://.

    Пустая строка возвращается пустой: обязательность решает вызывающий.
    """
    value = (raw or "").strip()
    if not value:
        return ""
    if _BAD_CHARS.search(value) or _hidden_chars(value):
        raise _invalid()
    match = _SCHEME.match(value)
    if match:
        scheme = match.group(1).lower()
        if scheme not in ("http", "https") or (https_only and scheme != "https"):
            raise LinkError("url_scheme", MSG_SCHEME)
        value = scheme + value[len(match.group(1)):]
    elif _DOMAIN_LIKE.match(value):
        value = "https://" + value
    else:
        # javascript:, data:, mailto:, tg: и всё, что не похоже на адрес сайта.
        raise LinkError("url_scheme", MSG_SCHEME)
    if len(value) > limit:
        raise LinkError("url_too_long", f"Ссылка длиннее {limit} символов")
    _host(value)
    try:
        _django_check(value)
    except ValidationError:
        raise _invalid() from None
    return value


def valid_course_url(value: str) -> bool:
    """Годится ли ссылка из базы для сайта как есть (без подстановок)."""
    if not value:
        return False
    try:
        return clean_url(value) == value
    except LinkError:
        return False


def ascii_host(value: str) -> str:
    """Хост ссылки в punycode — панели, чтобы подмена кириллицей была видна."""
    if not value:
        return ""
    try:
        return _host(clean_url(value))
    except LinkError:
        return ""


def clean_suggest_url(raw) -> str:
    """Ссылка кнопки «Предложить курс». @имя и t.me/… → https://t.me/…; пусто — кнопки нет."""
    if raw is None:
        return ""
    if not isinstance(raw, str):
        raise LinkError("suggest_invalid", MSG_SUGGEST)
    value = raw.strip()
    if not value:
        return ""
    name = _TG_NAME.match(value)
    telegram = _TG_HOST.match(value)
    if name:
        value = "https://t.me/" + name.group(1)
    elif telegram:
        tail = telegram.group(1)
        if not _TG_TAIL.match(tail):
            raise LinkError("suggest_invalid", MSG_SUGGEST)
        value = "https://t.me" + tail
    if len(value) > SUGGEST_MAX:
        raise LinkError("suggest_invalid", f"Ссылка для кнопки длиннее {SUGGEST_MAX} символов")
    try:
        # Кнопку открывают и в Telegram, и в браузере: только https.
        return clean_url(value, https_only=True, limit=SUGGEST_MAX)
    except LinkError:
        raise LinkError("suggest_invalid", MSG_SUGGEST) from None


def safe_suggest_url(raw) -> str:
    """То, что лежит в настройке, если оно всё ещё проходит проверку; иначе — кнопки нет."""
    try:
        return clean_suggest_url(raw)
    except LinkError:
        return ""
