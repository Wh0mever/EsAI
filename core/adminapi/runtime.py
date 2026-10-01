"""Чтение/запись runtime-настроек (adminapi.AppSetting) поверх env/settings.

Паттерн подключения в чужом коде — ЛЕНИВО и безопасно:

    value = <прежний источник>
    try:
        from adminapi.runtime import get_runtime
        value = get_runtime("KEY", value)
    except Exception:
        pass

get_runtime НИКОГДА не бросает исключений: пока миграция adminapi.0001 не
накатана (или БД недоступна), тихо возвращается default — прод не падает.
"""
from django.core.cache import cache

CACHE_TTL = 30  # секунд
CACHE_PREFIX = "appset:"

# Ключи, управляемые из админки (/api/manage/settings/).
KEYS = (
    "OPENROUTER_API_KEY",
    # Ниже какого остатка ($) система сама переключается на запасной аккаунт.
    "openrouter_auto_switch_below",
    "WELCOME_BONUS_TOKENS",
    "REFERRAL_BONUS_TOKENS",
    "DAILY_RETENTION_TARGET",
    # Порог ежедневного бонуса: кому доводим баланс до TARGET. Обязан быть
    # управляемым из админки вместе с TARGET — иначе рассинхрон убивает всю
    # механику (реальный инцидент: в .env стоял THRESHOLD=1, админ поднял
    # TARGET до 10, и бонус получал только тот, кто выжег баланс ровно в ноль).
    "DAILY_RETENTION_THRESHOLD",
    "WEB_SEARCH_SURCHARGE_CREDITS",
    "FREE_DAILY_REQUESTS",
    "PAID_DAILY_REQUESTS",
    "IMAGE_GEN_AUTO_ROUTE",
    # Калькулятор ценности кредитов (plans/credit_value.py): эталонные модели
    # по категориям (строка — openrouter_id) + размер "страницы" в токенах +
    # "типичный" размер текстового сообщения в токенах.
    "credit_calc_text_model",
    "credit_calc_image_model",
    "credit_calc_video_model",
    "credit_calc_document_model",
    "credit_calc_document_tokens_per_page",
    "credit_calc_text_tokens_per_reply",
    # Калькулятор "На что хватит?" (Этап 3, п.14): пороги "разумно полезного
    # объёма" за категорию — ниже порога пакет не считается "рекомендованным"
    # под сценарий использования (plans/credit_value.py _mark_recommended).
    "credit_calc_text_min_count",
    "credit_calc_image_min_count",
    "credit_calc_video_min_count",
    "credit_calc_document_min_count",
    # Витринный курс пересчёта цен KGS -> RUB (задача клиента: ЮKassa/показ цен
    # в рублях). НЕ платёжный курс — см. комментарий у settings.CURRENCY_KGS_TO_RUB_RATE.
    "currency_kgs_to_rub_rate",
    # Криптооплата. Режим off/staff/on, ключи процессора (наружу только маска),
    # курс сом->доллар (в отличие от рублёвого — ПЛАТЁЖНЫЙ: по нему выставляется
    # счёт) и список монет на витрине.
    "crypto_payments_mode",
    "NOWPAYMENTS_API_KEY",
    "NOWPAYMENTS_IPN_SECRET",
    "currency_kgs_to_usd_rate",
    "crypto_allowed_currencies",
    "crypto_fee_paid_by_user",
    "crypto_settlement_currency",
    # Оплата в сомах: выбор способа до ухода на FreedomPay (payments/kgs_methods.py).
    # Режим off/staff/on, список включённых способов через запятую и код единого
    # QR — его FreedomPay выдаёт магазину отдельно, пока не выдал — пусто.
    "kgs_methods_mode",
    "kgs_methods_enabled",
    "kgs_elqr_ps_code",
    # Видеостудия: режим off/staff/on поверх VSTUDIO_MODE из окружения
    # (выключить или открыть студию без выкладки; читает vstudio.views.studio_mode).
    "vstudio_mode",
    # Студия: сколько бесплатных примерок героя гости получают за сутки.
    "studio_guest_tryon_daily_cap",
    # Студия: цена сцены мультфильма (5 с) в кредитах; 0 — по тарифу модели.
    "studio_scene_credits",
    # Звук студии: ключ ElevenLabs и цены.
    "ELEVENLABS_API_KEY",
    "studio_voice_credits_per_1k",
    "studio_voice_min_credits",
    "studio_music_credits_per_min",
    "studio_sfx_credits",
)

# Сентинел «в кэше пусто» — None невалиден: мы кэшируем и None («ключа нет в БД»).
_MISSING = object()


def get_runtime(key: str, default):
    """Значение настройки из БД с кэшем 30с; тип приводится по типу default.

    bool-default: строка из ("1", "true", "True") -> True, иначе False.
    int-default: int(value). float-default: float(value). Остальное — str(value).
    При ЛЮБОЙ ошибке (нет таблицы, нет БД, кривое значение) -> default.
    """
    try:
        cache_key = CACHE_PREFIX + key
        raw = cache.get(cache_key, _MISSING)
        if raw is _MISSING:
            from .models import AppSetting
            row = AppSetting.objects.filter(key=key).only("value").first()
            raw = row.value if row is not None else None
            cache.set(cache_key, raw, CACHE_TTL)
        if raw is None:
            return default
        # ВАЖНО: bool раньше int (bool — подкласс int).
        if isinstance(default, bool):
            return raw in ("1", "true", "True")
        if isinstance(default, int):
            return int(raw)
        if isinstance(default, float):
            return float(raw)
        return str(raw)
    except Exception:
        return default


def set_runtime(key: str, value) -> None:
    """Upsert настройки + сброс кэша. bool сериализуем как "1"/"0"."""
    from .models import AppSetting

    if isinstance(value, bool):
        value = "1" if value else "0"
    AppSetting.objects.update_or_create(key=key, defaults={"value": str(value)})
    cache.delete(CACHE_PREFIX + key)


def delete_runtime(key: str) -> None:
    """Удалить override настройки (строку AppSetting) + сбросить кэш.

    После вызова get_runtime(key, default) снова начнёт возвращать default —
    это единственный способ вернуть runtime-настройку в состояние "не задано"
    (set_runtime может только ПЕРЕЗАПИСАТЬ значение, не стереть его). Безопасно
    вызывать для ключа, которого и так нет в БД (просто ничего не удалит).
    """
    from .models import AppSetting

    AppSetting.objects.filter(key=key).delete()
    cache.delete(CACHE_PREFIX + key)
