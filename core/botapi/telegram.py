"""Разговор с Telegram Bot API и проверка его подписей.

Здесь нет aiogram: ядру нужно всего два действия — проверить, что данные
действительно от Telegram, и отправить сообщение. Тащить ради этого
асинхронную библиотеку в синхронный Django незачем.
"""
import hashlib
import hmac
import json
import logging
from urllib.parse import parse_qsl

import requests
from django.conf import settings

logger = logging.getLogger("botapi")

API_BASE = "https://api.telegram.org"
TIMEOUT = (10, 30)


def bot_token() -> str:
    """Токен товарного бота (не того, через который вход на сайте)."""
    return (getattr(settings, "TELEGRAM_PRODUCT_BOT_TOKEN", "") or "").strip()


def verify_webapp_init_data(init_data: str, token: str = "", max_age: int = 3600) -> dict | None:
    """Проверить initData из Mini App и вернуть данные пользователя.

    Ключ подписи — HMAC от строки «WebAppData» на токене бота (именно в таком
    порядке: сообщение — WebAppData, ключ — токен). Перепутать местами легко,
    и тогда подпись не сойдётся никогда.
    """
    token = (token or bot_token()).strip()
    if not token or not init_data:
        return None
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    except Exception:
        return None

    received = (pairs.pop("hash", "") or "").strip().lower()
    if len(received) != 64 or not all(c in "0123456789abcdef" for c in received):
        return None
    pairs.pop("signature", None)

    check_string = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
    secret = hmac.new(b"WebAppData", token.encode("utf-8"), hashlib.sha256).digest()
    expected = hmac.new(secret, check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received):
        return None

    try:
        auth_date = int(pairs.get("auth_date") or 0)
    except (TypeError, ValueError):
        return None
    if max_age and auth_date:
        import time

        if time.time() - auth_date > max_age:
            return None

    try:
        user = json.loads(pairs.get("user") or "{}")
    except ValueError:
        return None
    if not isinstance(user, dict) or not user.get("id"):
        return None
    user["_auth_date"] = auth_date
    user["_hash"] = received
    return user


class TelegramError(RuntimeError):
    def __init__(self, description: str = "", code: int = 0, retry_after: int = 0,
                 blocked: bool = False):
        super().__init__(description or f"telegram_error_{code}")
        self.description = description
        self.code = code
        self.retry_after = retry_after
        self.blocked = blocked


def tg_api(method: str, token: str = "", **params):
    """Вызвать метод Bot API. Кидает TelegramError с разобранной причиной."""
    token = (token or bot_token()).strip()
    if not token:
        raise TelegramError("bot_token_missing")
    payload = {k: v for k, v in params.items() if v is not None}
    for key in ("reply_markup", "prices"):
        if key in payload and not isinstance(payload[key], str):
            payload[key] = json.dumps(payload[key], ensure_ascii=False)
    try:
        r = requests.post(f"{API_BASE}/bot{token}/{method}", json=payload, timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise TelegramError(f"network: {exc}") from exc

    try:
        data = r.json()
    except ValueError:
        raise TelegramError(f"bad_response_{r.status_code}", code=r.status_code)

    if data.get("ok"):
        return data.get("result")

    description = str(data.get("description") or "")
    parameters = data.get("parameters") or {}
    raise TelegramError(
        description,
        code=int(data.get("error_code") or r.status_code),
        retry_after=int(parameters.get("retry_after") or 0),
        # Человек заблокировал бота или удалил чат — писать ему больше нельзя.
        blocked=("bot was blocked" in description.lower()
                 or "user is deactivated" in description.lower()
                 or "chat not found" in description.lower()),
    )


def escape(text: str) -> str:
    """Экранировать текст для parse_mode=HTML."""
    return (str(text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
