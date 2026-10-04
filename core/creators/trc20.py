"""Проверка адреса USDT TRC20 и хеша перевода (TXID).

Сети здесь нет: выплату отправляет человек, код только не даёт сохранить
адрес с опечаткой — перевод на такой адрес не вернуть. Адрес Tron — это
Base58Check: 21 байт (0x41 + 20 байт адреса) и 4 байта контрольной суммы.
"""
from __future__ import annotations

import hashlib
import re

from .errors import CreatorsError

_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_INDEX = {char: index for index, char in enumerate(_ALPHABET)}

ADDRESS_LENGTH = 34
_DECODED_LENGTH = 25
_TRON_PREFIX = 0x41

TXID_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def is_valid_address(addr) -> bool:
    """Настоящий ли это адрес сети Tron. Никогда не бросает исключений."""
    if not isinstance(addr, str) or len(addr) != ADDRESS_LENGTH or not addr.startswith("T"):
        return False
    number = 0
    for char in addr:
        digit = _INDEX.get(char)
        if digit is None:
            return False
        number = number * 58 + digit
    try:
        raw = number.to_bytes(_DECODED_LENGTH, "big")
    except OverflowError:
        return False
    if raw[0] != _TRON_PREFIX:
        return False
    body, checksum = raw[:21], raw[21:]
    return hashlib.sha256(hashlib.sha256(body).digest()).digest()[:4] == checksum


def normalize_txid(raw) -> str:
    """TXID к одному виду: без 0x, в нижнем регистре. Не 64 hex-символа — txid_invalid."""
    value = str(raw or "").strip()
    if value[:2] in ("0x", "0X"):
        value = value[2:]
    if not TXID_RE.match(value):
        raise CreatorsError("txid_invalid")
    return value.lower()
