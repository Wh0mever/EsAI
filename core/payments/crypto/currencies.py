"""Монеты и сети: как они называются у процессора и как выглядят на витрине.

Человек выбирает не «usdttrc20», а «USDT · TRON (TRC-20)» — эта таблица и
переводит одно в другое. Список доступных монет правится в админке
(AppSetting "crypto_allowed_currencies"), код при этом не трогается.

Комиссии сети в долларах здесь намеренно НЕ записаны: они плавают, а цифра,
которая разошлась с реальностью, хуже её отсутствия. Показываем не число, а
насколько сеть дорогая (network_cost), — этого достаточно, чтобы человек
выбрал TRC-20 вместо ERC-20.
"""
from __future__ import annotations

from decimal import Decimal

from django.conf import settings

from .base import CurrencyInfo

# code процессора -> (монета, сеть, подпись, memo, дороговизна сети, популярная)
KNOWN = {
    "usdttrc20": ("USDT", "TRC-20", "USDT · TRON (TRC-20)", False, "low", True),
    "usdtton": ("USDT", "TON", "USDT · TON", True, "low", True),
    "usdtbsc": ("USDT", "BEP-20", "USDT · BNB Smart Chain (BEP-20)", False, "low", False),
    "usdterc20": ("USDT", "ERC-20", "USDT · Ethereum (ERC-20)", False, "high", False),
    "usdtsol": ("USDT", "Solana", "USDT · Solana", False, "low", False),
    "usdcerc20": ("USDC", "ERC-20", "USDC · Ethereum (ERC-20)", False, "high", False),
    "usdcbsc": ("USDC", "BEP-20", "USDC · BNB Smart Chain (BEP-20)", False, "low", False),
    "usdcsol": ("USDC", "Solana", "USDC · Solana", False, "low", False),
    "btc": ("BTC", "Bitcoin", "Bitcoin", False, "medium", True),
    "eth": ("ETH", "ERC-20", "Ethereum", False, "high", True),
    # Клиент просит звать монету «GRAM» (так называлась монета Telegram до
    # 2020 года), Toncoin — в скобках. Тикер остаётся TON: на экране счёта
    # человек видит «отправьте TON», и перепутать с жетоном GRAM сложнее.
    "ton": ("TON", "TON", "GRAM (Toncoin)", True, "low", True),
    "ltc": ("LTC", "Litecoin", "Litecoin", False, "low", False),
    "trx": ("TRX", "TRC-20", "TRON", False, "low", False),
    "bnbbsc": ("BNB", "BEP-20", "BNB · BNB Smart Chain", False, "low", False),
    "sol": ("SOL", "Solana", "Solana", False, "low", False),
    "doge": ("DOGE", "Dogecoin", "Dogecoin", False, "low", False),
    "xrp": ("XRP", "XRP Ledger", "XRP", True, "low", False),
    "xmr": ("XMR", "Monero", "Monero", False, "low", False),
}

# Порядок на витрине: сперва то, чем действительно платят в наших краях.
ORDER = ("usdttrc20", "usdtton", "usdtbsc", "usdterc20", "usdtsol",
         "ton", "btc", "eth", "ltc", "trx", "bnbbsc", "sol", "doge",
         "usdcerc20", "usdcbsc", "usdcsol", "xrp", "xmr")


def allowed_codes() -> list:
    """Коды монет, включённых админом (в порядке витрины)."""
    from adminapi.runtime import get_runtime

    raw = get_runtime("crypto_allowed_currencies",
                      str(getattr(settings, "CRYPTO_ALLOWED_CURRENCIES", "")))
    codes = {c.strip().lower() for c in str(raw or "").split(",") if c.strip()}
    ordered = [c for c in ORDER if c in codes]
    # Монета, которой нет в нашей таблице порядка, всё равно должна работать:
    # админ мог включить её раньше, чем мы успели описать.
    ordered += sorted(c for c in codes if c not in set(ORDER))
    return ordered


def is_allowed(code: str) -> bool:
    return str(code or "").strip().lower() in set(allowed_codes())


def describe(code: str, *, min_amount_usd: Decimal | None = None) -> CurrencyInfo:
    """Как показать эту монету человеку."""
    code = str(code or "").strip().lower()
    coin, network, label, extra, cost, popular = KNOWN.get(
        code, (code.upper(), "", code.upper(), False, "medium", False))
    return CurrencyInfo(
        code=code, coin=coin, network=network, label=label,
        extra_id_required=extra, min_amount_usd=min_amount_usd,
        network_cost=cost, popular=popular,
    )
