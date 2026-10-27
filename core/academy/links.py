"""Внешние ссылки Академии: ссылка на курс и «Предложить курс» (ссылка, e-mail или текст).

Ссылки вводят сотрудники, а открывают посетители esai.kg — пропущенный
javascript:/data: или адрес внутренней сети стал бы XSS или фишингом с нашего
домена. Поэтому правила строгие, и публичный API проверяет ссылку ещё раз:
строку в базе могли поправить мимо панели.

«Предложить курс» по решению владельца (27.10.2026) принимает любую ссылку и
даже текст: адреса внутренней сети там можно, но ловушки, из-за которых
браузер откроет не тот адрес, что написан, и опасные схемы — нет. Правила —
CONTRACT_ACADEMY §5.

Доступность сайта сервер не проверяет: запрос по введённому адресу — это
SSRF, а многие сайты отвечают ботам 403/429 (ложные тревоги).
"""
from __future__ import annotations

import ipaddress
import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import quote, unquote, urlsplit

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from idna import IDNAError, check_bidi, check_initial_combiner, uts46_remap

URL_MAX = 1000
SUGGEST_MAX = 300
SUGGEST_LINES = 5
SUGGEST_KEY = "academy_suggest_url"

MSG_SCHEME = "Ссылка должна начинаться с https:// или http://"
MSG_USERINFO = "В ссылке не должно быть логина и пароля (user:pass@)"
MSG_LOCAL = "Ссылка ведёт на внутренний адрес — нужен адрес сайта в интернете"
MSG_INVALID = "Ссылка на курс — адрес сайта вида https://example.com/kurs"
MSG_SUGGEST_TYPE = "Предложить курс: нужна строка"
MSG_SUGGEST_LONG = "Не длиннее {max} символов — сейчас {n}"
# Про эмодзи: склейку U+200D внутри составного эмодзи сотрудник не видит и не поймёт, что убирать.
MSG_SUGGEST_HIDDEN = ("Уберите невидимые символы: управляющие, нулевой ширины (в том числе внутри "
                      "составных эмодзи) или смены направления текста")
MSG_SUGGEST_DANGER = ("Ссылки «{scheme}:» на сайт не ставим — нужна ссылка https://…, e-mail, @имя "
                      "или обычный текст")
MSG_SUGGEST_SCHEME = ("Ссылки «{scheme}:» не подходят — нужна https:// или http://, e-mail "
                      "или @имя в Telegram")
MSG_SUGGEST_HOST = ("Не разобрать адрес сайта в ссылке — проверьте её, например "
                    "https://example.com/forma")

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
# Только с @: без неё «Academy» или «Soon» — обычный текст, а не канал в Telegram.
_TG_NAME = re.compile(r"^@([A-Za-z][A-Za-z0-9_]{3,31})$")
_TG_HOST = re.compile(
    r"^(?:https?://)?(?:www\.)?(?:t\.me|telegram\.me|telegram\.dog)(?=[/?#]|$)(.*)$", re.I)
_TG_TAIL = re.compile(r"^/[A-Za-z0-9_+\-]+(?:/[A-Za-z0-9_\-]+)*/?(?:\?[A-Za-z0-9_=&\-]*)?$")
# Схемы, которые браузер исполняет или открывает как документ (file: — файл с компьютера
# посетителя). Их не храним даже текстом: если когда-нибудь текст станет ссылкой, он не выстрелит.
_DANGER = re.compile(r"^(javascript|vbscript|data|file):", re.I)
_HTTP = re.compile(r"^https?://", re.I)
_MAILTO = re.compile(r"^mailto:", re.I)
_SPACE = re.compile(r"\s")
_LINE_SPACES = re.compile(r"[^\S\n]+")
_EMAIL_LOCAL = re.compile(r"^[\w+\-]+(?:\.[\w+\-]+)*$")
# Метка хоста «любой ссылки»: браузер пускает и «_», и «-» по краям.
_OPEN_LABEL = re.compile(r"^[a-z0-9_-]{1,63}$")
_BRACKETED = re.compile(r"\[[0-9A-Fa-f:.]+\](?::\d{0,5})?")
# Точки, которыми и Python (IDNA2003), и браузер (UTS46) делят имя на метки.
_IDNA_DOTS = re.compile("[.\u3002\uff0e\uff61]")

# Адрес без схемы становится кнопкой, только если похож на сайт, а не на прозу без пробела
# («Скоро.Ждите», «v1.2»): домен верхнего уровня — латиницей или из настоящих кириллических.
_SCHEMELESS_HOST = re.compile(r"^[^/?#:]+")
_ASCII_TOP = re.compile(r"[A-Za-z]{2,24}")
_CYRILLIC_TOPS = frozenset({"рф", "бел", "укр", "срб", "қаз", "рус", "мкд", "мон", "онлайн", "сайт"})
# Кириллица с латиницей в одной метке — подмена похожих букв (русская «а» в латинском имени).
_CYRILLIC = re.compile(r"[\u0400-\u052f\u1c80-\u1c8f\ua640-\ua69f]")
_LATIN = re.compile(r"[A-Za-z\u00c0-\u00d6\u00d8-\u00f6\u00f8-\u024f]")

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


def _nfkc_dots(name: str) -> bool:
    """NFKC делает в имени точку из «не точки»: U+2024 → «.», U+2488 → «1.», U+FE12 → U+3002 и т. п."""
    # Python (IDNA2003) делит имя на метки до NFKC и видит другой хост, а браузер (UTS46)
    # такие знаки не пускает и ссылку не открывает: на сайте она молча пропала бы.
    return len(_IDNA_DOTS.findall(unicodedata.normalize("NFKC", name))) != len(_IDNA_DOTS.findall(name))


def _browser_ascii(name: str) -> str | None:
    """Хост в ASCII так, как его прочтёт браузер (UTS46); None — браузер такой адрес не откроет."""
    try:
        mapped = uts46_remap(name, std3_rules=False, transitional=False)
    except (IDNAError, UnicodeError):
        return None
    out = []
    for label in mapped.split("."):
        if not label:
            out.append(label)
            continue
        if label.isascii():
            if label.lower().startswith("xn--"):
                try:
                    decoded = label[4:].encode("ascii").decode("punycode")
                except UnicodeError:
                    return None
                if uts46_remap(decoded, std3_rules=False, transitional=False) != decoded:
                    return None
            out.append(label.lower())
            continue
        if unicodedata.normalize("NFC", label) != label:
            return None
        try:
            check_initial_combiner(label)
            check_bidi(label)
        except (IDNAError, UnicodeError):
            return None
        out.append("xn--" + label.encode("punycode").decode("ascii"))
    return ".".join(out)


def _browser_differs(name: str, ascii_name: str) -> bool:
    # Python кодирует имя по IDNA2003 (таблицы Unicode 3.2), браузер — по UTS46: символы новее 3.2,
    # «невидимые» заполнители, U+1FBF1 → «1» и т. п. Где ответы расходятся, браузер откроет другой хост
    # (127.0.0.<U+1FBF1> → 127.0.0.1) или не откроет никакой, и ссылка на сайте молча пропадёт.
    browser = _browser_ascii(name)
    return browser is None or browser.rstrip(".") != ascii_name.rstrip(".")


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
    if not host or port == 0 or _IDNA_DEVIATION.search(parts.netloc) or _nfkc_dots(host):
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
    if _browser_differs(host, ascii_host):
        raise _invalid()
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


@dataclass(frozen=True)
class Suggest:
    """«Предложить курс» после разбора: что хранить в настройке и что показать на сайте."""

    kind: str  # url | email | text
    value: str
    text: str
    href: str | None

    def as_json(self) -> dict:
        return {"kind": self.kind, "text": self.text, "href": self.href}


def _link(value: str) -> Suggest:
    return Suggest("url", value, value, value)


def _bad_host() -> LinkError:
    return LinkError("suggest_host", MSG_SUGGEST_HOST)


def _ascii_domain(name: str) -> str | None:
    """Имя хоста в punycode, нижним регистром; None — браузер прочтёт его иначе или не откроет."""
    if _IDNA_DEVIATION.search(name) or _nfkc_dots(name):
        return None
    try:
        ascii_name = name.encode("idna").decode("ascii").lower()
        # Обратный ход ловит битый punycode (xn--zz): Python его пропускает, браузер — нет.
        ascii_name.encode("ascii").decode("idna")
    except UnicodeError:
        return None
    if _browser_differs(name, ascii_name):
        return None
    return ascii_name if len(ascii_name) <= 253 else None


def _open_link(value: str) -> str:
    """http(s)://-ссылка кнопки одним словом: любой хост, и localhost, и IP, но тот, что откроет браузер."""
    scheme, _, rest = value.partition(":")
    value = f"{scheme.lower()}:{rest}"
    # Обратная косая: браузер читает её как «/», и хост у него вышел бы другой.
    if "\\" in value:
        raise _bad_host()
    try:
        parts = urlsplit(value)
        port = parts.port
        host = parts.hostname or ""
    except ValueError:
        raise _bad_host() from None
    if "@" in parts.netloc:
        raise LinkError("suggest_userinfo", MSG_USERINFO)
    host = host[:-1] if host.endswith(".") else host
    if not host or port == 0 or "%" in host:
        raise _bad_host()
    bracketed = "[" in parts.netloc or "]" in parts.netloc
    # Мусор после «]» ([::1]-x) Python молча отбрасывает, а браузер такую ссылку не откроет.
    if bracketed and not _BRACKETED.fullmatch(parts.netloc):
        raise _bad_host()
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None:
        if (ip.version == 6) != bracketed:
            raise _bad_host()
        return value
    name = None if bracketed else _ascii_domain(host)
    labels = name.split(".") if name else []
    # 127.1, 0x7f.1, 2130706433, 010.0.0.1: браузер откроет не тот адрес, что
    # написан (или не откроет вовсе), — такое за адрес не считаем.
    if (not labels or not all(_OPEN_LABEL.fullmatch(label) for label in labels)
            or _NUMERIC_TLD.fullmatch(labels[-1])):
        raise _bad_host()
    return value


def _email(address: str) -> Suggest | None:
    """Адрес почты → вид email; None — не адрес (вызывающий разбирает строку дальше, в конце — как текст)."""
    # После %-раскодирования mailto: могли появиться невидимые знаки (mailto:a@b%C2%ADc.kg): nameprep
    # выбросит их из домена, а в сохранённое значение они попадут — и повторный разбор его отвергнет.
    if _hidden_in_text(address):
        return None
    local, at, domain = address.rpartition("@")
    # fullmatch, а не match: «$» пропускает перевод строки в конце (mailto:a%0A@b.kg).
    if (not at or "@" in local or len(local) > 64 or len(address) > 254
            or not _EMAIL_LOCAL.fullmatch(local) or domain.endswith(".")):
        return None
    name = _ascii_domain(domain)
    labels = name.split(".") if name else []
    if (len(labels) < 2 or not all(_LABEL.fullmatch(label) for label in labels)
            or not _TLD.fullmatch(labels[-1])):
        return None
    # Домен в punycode понимает любая почтовая программа; не-ASCII в имени — только %-кодом.
    return Suggest("email", address, address, f"mailto:{quote(local, safe='+')}@{name}")


def _schemeless(value: str) -> bool:
    """Одно слово — адрес сайта без схемы: example.com, www.example.com/path, курсы.рф."""
    if "@" in value or not _DOMAIN_LIKE.match(value):
        return False
    labels = _SCHEMELESS_HOST.match(value).group(0).split(".")
    top = labels[-1]
    if not (_ASCII_TOP.fullmatch(top) or top.lower() in _CYRILLIC_TOPS):
        return False
    return not any(_CYRILLIC.search(label) and _LATIN.search(label) for label in labels)


def _plain_text(value: str) -> Suggest:
    lines = [_LINE_SPACES.sub(" ", raw).strip() for raw in value.split("\n")]
    lines = [line for line in lines if line]
    if len(lines) > SUGGEST_LINES:
        lines = lines[:SUGGEST_LINES - 1] + [" ".join(lines[SUGGEST_LINES - 1:])]
    text = "\n".join(lines)
    return Suggest("text", text, text, None)


def _hidden_in_text(value: str) -> bool:
    # Перевод строки — часть текста. Остальное невидимо или переворачивает
    # строку: в панели видно одно, на сайте прочтут другое. Одинокий суррогат
    # не запишется в Postgres.
    return any(ch != "\n" and unicodedata.category(ch) in ("Cc", "Cf", "Zl", "Zp", "Cs")
               for ch in value)


def _too_long(n: int) -> LinkError:
    return LinkError("suggest_too_long", MSG_SUGGEST_LONG.format(max=SUGGEST_MAX, n=n))


def _refuse_danger(value: str) -> None:
    # Переводы строк браузер из ссылки выбрасывает: «java⏎script:» — тоже она.
    danger = _DANGER.match(value.replace("\n", ""))
    if danger:
        raise LinkError("suggest_danger", MSG_SUGGEST_DANGER.format(scheme=danger.group(1).lower()))


def _classify(value: str) -> Suggest:
    _refuse_danger(value)
    one_word = not _SPACE.search(value)
    name = _TG_NAME.match(value)
    if name:
        return _link("https://t.me/" + name.group(1))
    telegram = _TG_HOST.match(value)
    if telegram and _TG_TAIL.match(telegram.group(1)):
        return _link("https://t.me" + telegram.group(1))
    if _MAILTO.match(value):
        # Тему и прочие параметры отбрасываем: на сайте кнопка просто открывает письмо.
        address = unquote(re.split(r"[?#]", value[len("mailto:"):], maxsplit=1)[0])
        item = _email(address)
        # Не адрес после mailto: — обычный текст: годный адрес в нём сайт всё равно сделает ссылкой.
        return item if item is not None else _plain_text(value)
    if one_word and "@" in value:
        item = _email(value)
        if item is not None:
            return item
    if _HTTP.match(value):
        # Ссылка, а за ней слова или строки («https://forms.gle/… ⏎ Заполните анкету»), — это текст:
        # ссылку в нём сайт сделает ссылкой, если она проходит те же правила.
        return _link(_open_link(value)) if one_word else _plain_text(value)
    if one_word and _schemeless(value):
        try:
            return _link(_open_link("https://" + value))
        except LinkError:
            # Похоже на адрес, но ссылкой не откроется (порт 99999, битый punycode) — пусть остаётся текстом.
            return _plain_text(value)
    scheme = _SCHEME.match(value)
    if one_word and scheme:
        # tg://, ftp://, whatsapp://: кнопка с такой ссылкой у посетителя не откроется.
        raise LinkError("suggest_scheme", MSG_SUGGEST_SCHEME.format(scheme=scheme.group(1).lower()))
    # Остальное — текст, и с двоеточием тоже: «Contact:a@b.kg», «tel:+996…», «https:example.com».
    return _plain_text(value)


def parse_suggest(raw) -> Suggest | None:
    """«Предложить курс»: ссылка, e-mail или текст (CONTRACT_ACADEMY §5). None — пусто."""
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise LinkError("suggest_type", MSG_SUGGEST_TYPE)
    value = raw.replace("\r\n", "\n").replace("\r", "\n").replace("\t", " ").strip()
    if not value:
        return None
    if len(value) > SUGGEST_MAX:
        raise _too_long(len(value))
    if _hidden_in_text(value):
        raise LinkError("suggest_hidden", MSG_SUGGEST_HIDDEN)
    item = _classify(value)
    # Ещё раз — по тому, что ляжет в базу: у текста срезаны пробелы у переносов,
    # и «java ⏎script:» склеился бы в опасное начало.
    _refuse_danger(item.value)
    # Длиннее входа становятся только формы Telegram (t.me/… → https://t.me/…).
    if len(item.value) > SUGGEST_MAX:
        raise _too_long(len(item.value))
    return item


def safe_suggest(raw) -> Suggest | None:
    """То, что лежит в настройке, если оно всё ещё проходит проверку; иначе — на сайте ничего."""
    try:
        return parse_suggest(raw)
    except LinkError:
        return None
