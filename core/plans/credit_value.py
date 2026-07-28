"""Калькулятор "ценности" пакета кредитов: сколько единиц результата даёт пакет.

Фундамент для будущего интерактивного калькулятора "На что хватит" на сайте
esai.kg и для редизайна тарифов. НЕ меняет реальную формулу списания (см.
ai/handlers.py) — только ОЦЕНИВАЕТ её на эталонных моделях, чтобы показать
клиенту порядок величины ("N сообщений / N картинок / N видео / N страниц").

Категории и формулы (см. разведку, зафиксированную в комментариях ниже) —
КАЖДАЯ формула здесь намеренно зеркалит РЕАЛЬНУЮ логику списания из
ai/handlers.py (переиспользуя её функции, где это возможно), чтобы цифры,
показанные клиенту, не были "лучшим случаем", а были правдоподобной оценкой
типичного использования:

- text / document: токенная формула ceil(total_tokens * coeff / TOKEN_CREDIT_DIVISOR)
  — та же нормализация, что в ai/handlers.py _compute_charge/_precise_balance_gate.
  total_tokens берём НЕ из estimated_min_charge() (plans/wallet.py) — та функция
  оценивает МИНИМАЛЬНЫЙ ответ для гейта "хватит ли баланса вообще" (её
  докстринг: "лишь минимальный ответ, без учёта промпта"), а не типичное
  сообщение. Вместо этого используем settings.CREDIT_CALC_TEXT_TOKENS_PER_REPLY
  (ОЦЕНКА "типичного" сообщения с историей чата, см. комментарий в settings.py)
  для text, и settings.CREDIT_CALC_DOCUMENT_TOKENS_PER_PAGE для document.
- image: механизм биллинга зависит от КОНКРЕТНОЙ выбранной модели. Детекция
  FLUX и формула списания живут в ai/model_billing.py — ЕДИНЫЙ источник истины,
  импортируемый и отсюда (оценка), и из ai/handlers.py (реальное списание);
  дублирования кода между ними нет:
    * FLUX (black-forest-labs/*, *flux.2*) — плоское списание/картинку
      max(1, int(markup_coefficient)) — ai.model_billing.flux_charge_credits.
    * НЕ-FLUX (Nano Banana family: google/gemini-2.5-flash-image,
      google/gemini-3-pro-image) — билится КАК ТЕКСТ, токенной формулой, см.
      settings.CREDIT_CALC_IMAGE_*_TOKENS_ESTIMATE.
  Так что ЛЮБАЯ активная image-модель, назначенная эталоном через админку,
  даёт корректный результат — не только FLUX.
- video: markup_coefficient видео-модели = кредитов ЗА СЕКУНДУ, формула
  max(1, ceil(duration_seconds * markup_coefficient)) — переиспользуем
  ai.handlers._video_model_params(), чтобы получить РЕАЛЬНУЮ "примагниченную"
  длительность по умолчанию для КОНКРЕТНОЙ эталонной модели из живого каталога
  OpenRouter (кэш Redis "or_video_models", TTL 1ч) — та же функция, что
  вызывается при реальной генерации видео. Если каталог недоступен (сеть/ошибка)
  — фолбэк на settings.VIDEO_GEN_DURATION (приближение, как раньше).

Ни одна функция здесь не должна падать на "плохих" входных данных (нет
эталонной модели, нет цены, недоступен каталог видео-моделей и т.п.) —
вызывающий код (публичный API) обязан уметь пережить отсутствие категории
в выдаче.

Калькулятор "На что хватит?" (Этап 3, п.14): compute_all_packages_value()
дополнительно помечает, какой пакет РЕКОМЕНДОВАН под сценарий использования
каждой категории — "recommended": bool внутри value.<category> (см.
_mark_recommended). Логика: самый дешёвый пакет, чей count достиг
admin-настраиваемого порога credit_calc_<category>_min_count (дефолты:
text=200, image=100, video=5, document=200), либо, если порог никто не
достиг, самый дорогой активный пакет.
"""
from __future__ import annotations

import logging
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR

logger = logging.getLogger(__name__)

# credit_calc-категория -> settings-атрибут с дефолтным openrouter_id.
_CATEGORY_SETTINGS_ATTR = {
    "text": "CREDIT_CALC_TEXT_MODEL_ID",
    "image": "CREDIT_CALC_IMAGE_MODEL_ID",
    "video": "CREDIT_CALC_VIDEO_MODEL_ID",
    "document": "CREDIT_CALC_DOCUMENT_MODEL_ID",
}


def get_reference_model(category: str):
    """Вернуть эталонную GPTModels для категории калькулятора, либо None.

    Источник openrouter_id: runtime-настройка admin'ки (adminapi.AppSetting,
    ключ credit_calc_<category>_model) с фолбэком на settings.CREDIT_CALC_*_MODEL_ID.
    Возвращает None (не бросает исключение), если категория неизвестна, id
    пуст, модель не найдена или неактивна — вызывающий код обязан это пережить.
    """
    from django.conf import settings as dj_settings
    from ai.models import GPTModels

    settings_attr = _CATEGORY_SETTINGS_ATTR.get(category)
    if not settings_attr:
        return None

    default_id = str(getattr(dj_settings, settings_attr, "") or "")
    runtime_key = f"credit_calc_{category}_model"
    openrouter_id = default_id
    try:
        from adminapi.runtime import get_runtime
        openrouter_id = get_runtime(runtime_key, default_id)
    except Exception:
        openrouter_id = default_id

    openrouter_id = (openrouter_id or "").strip()
    if not openrouter_id:
        logger.warning(
            "credit_value: эталонная модель для категории %r не настроена "
            "(пустой openrouter_id)", category,
        )
        return None

    try:
        model = GPTModels.objects.filter(
            openrouter_id=openrouter_id, is_active=True,
        ).first()
    except Exception:
        logger.exception(
            "credit_value: ошибка чтения эталонной модели категории %r", category,
        )
        return None

    if model is None:
        logger.warning(
            "credit_value: эталонная модель %r для категории %r не найдена "
            "или неактивна", openrouter_id, category,
        )
    return model


def _token_credit_divisor() -> float:
    """Делитель конвертации токены→кредиты — ТОТ ЖЕ, что в ai/handlers.py
    _token_credit_divisor(), иначе оценка калькулятора разъедется с реальным
    списанием."""
    from django.conf import settings as dj_settings

    try:
        d = float(getattr(dj_settings, "TOKEN_CREDIT_DIVISOR", 1000) or 1000)
    except Exception:
        d = 1000.0
    return d if d > 0 else 1000.0


def _credits_for_tokens(total_tokens, coeff) -> Decimal:
    """Кредиты за total_tokens по ТОЙ ЖЕ нормализации, что реальное списание
    (ai/handlers.py _compute_charge / _precise_balance_gate):

        credits = max(1, ceil(total_tokens * coeff / TOKEN_CREDIT_DIVISOR))

    coeff — markup_coefficient модели (тариф в кредитах за 1000 токенов).
    """
    try:
        coeff_f = float(coeff) if coeff is not None else 1.0
    except Exception:
        coeff_f = 1.0
    if coeff_f <= 0:
        coeff_f = 1.0
    divisor = _token_credit_divisor()
    raw = (Decimal(str(total_tokens)) * Decimal(str(coeff_f)) / Decimal(str(divisor)))
    charged = raw.to_integral_value(rounding=ROUND_CEILING)
    return max(Decimal(1), charged)


def _text_tokens_per_reply() -> int:
    """"Типичный" размер ОДНОГО текстового сообщения (вход+выход) в токенах.

    ОЦЕНКА, не измеренное значение — см. развёрнутый комментарий у
    settings.CREDIT_CALC_TEXT_TOKENS_PER_REPLY о том, почему estimated_min_charge()
    здесь не подходит и откуда взят дефолт. Runtime-переопределяемо из админки
    (ключ credit_calc_text_tokens_per_reply) без рестарта.
    """
    from django.conf import settings as dj_settings

    default = int(getattr(dj_settings, "CREDIT_CALC_TEXT_TOKENS_PER_REPLY", 2500) or 2500)
    try:
        from adminapi.runtime import get_runtime
        value = int(get_runtime("credit_calc_text_tokens_per_reply", default))
    except Exception:
        value = default
    return value if value > 0 else default


def _document_tokens_per_page() -> int:
    """Сколько токенов в одной "странице" документа (runtime-переопределяемо)."""
    from django.conf import settings as dj_settings

    default = int(getattr(dj_settings, "CREDIT_CALC_DOCUMENT_TOKENS_PER_PAGE", 650) or 650)
    try:
        from adminapi.runtime import get_runtime
        value = int(get_runtime("credit_calc_document_tokens_per_page", default))
    except Exception:
        value = default
    return value if value > 0 else default


def _image_credits(model) -> Decimal | None:
    """Кредиты за ОДНУ картинку эталонной image-модели, с учётом РЕАЛЬНОГО
    механизма биллинга этой конкретной модели (FLUX плоско / Nano Banana как
    токены) — см. docstring модуля. Возвращает None, если coeff отсутствует.
    """
    from django.conf import settings as dj_settings
    from ai.model_billing import is_flux_image_model, flux_charge_credits

    coeff = model.markup_coefficient
    if coeff is None:
        return None
    openrouter_id = str(getattr(model, "openrouter_id", "") or "")

    if is_flux_image_model(openrouter_id):
        return Decimal(flux_charge_credits(model))

    # НЕ-FLUX (Nano Banana family) — билится КАК ТЕКСТ токенной формулой.
    prompt_tokens = int(
        getattr(dj_settings, "CREDIT_CALC_IMAGE_PROMPT_TOKENS_ESTIMATE", 150) or 150)
    output_tokens = int(
        getattr(dj_settings, "CREDIT_CALC_IMAGE_OUTPUT_TOKENS_ESTIMATE", 1300) or 1300)
    return _credits_for_tokens(prompt_tokens + output_tokens, coeff)


def _video_credits(model) -> Decimal | None:
    """Кредиты за ОДИН ролик эталонной video-модели, по РЕАЛЬНОЙ "примагниченной"
    длительности этой конкретной модели (см. docstring модуля). Возвращает
    None, если coeff отсутствует.
    """
    from django.conf import settings as dj_settings

    coeff = model.markup_coefficient
    if coeff is None:
        return None
    openrouter_id = str(getattr(model, "openrouter_id", "") or "")
    want_duration = int(getattr(dj_settings, "VIDEO_GEN_DURATION", 5) or 5)
    want_resolution = str(getattr(dj_settings, "VIDEO_GEN_RESOLUTION", "720p") or "720p")

    duration = want_duration
    try:
        from ai.handlers import _video_model_params, _openrouter_config
        cfg = _openrouter_config()
        vp = _video_model_params(openrouter_id, cfg, want_duration, want_resolution)
        duration = int(vp.get("duration") or want_duration)
    except Exception:
        # Каталог OpenRouter недоступен/ошибка сети — фолбэк на приближение
        # VIDEO_GEN_DURATION (как было раньше), НЕ роняем весь расчёт.
        logger.exception(
            "credit_value: не удалось получить реальную длительность видео для %r, "
            "используется VIDEO_GEN_DURATION как приближение", openrouter_id)
        duration = want_duration

    raw = (Decimal(duration) * Decimal(str(coeff))).to_integral_value(rounding=ROUND_CEILING)
    return max(Decimal(1), raw)


def credits_per_unit(category: str, model=None) -> Decimal | None:
    """Сколько кредитов стоит ОДНА единица результата данной категории.

    text/document — кредитов за "типичное сообщение"/"страницу" (токенная формула).
    image — кредитов за картинку (формула зависит от механизма биллинга модели).
    video — кредитов за ролик (по РЕАЛЬНОЙ длительности эталонной модели).
    Возвращает None, если эталонная модель не настроена/не активна.

    model — опционально, уже полученная эталонная модель категории (избегает
    повторного get_reference_model(category), если вызывающий код её уже
    зафетчил, например compute_package_value() в цикле по пакетам). Если не
    передан — модель получается внутри, как раньше.
    """
    if model is None:
        model = get_reference_model(category)
    if model is None:
        return None

    if category in ("text", "document"):
        coeff = model.markup_coefficient
        if coeff is None:
            return None
        if category == "text":
            return _credits_for_tokens(_text_tokens_per_reply(), coeff)
        # document: кредиты за "страницу" (CREDIT_CALC_DOCUMENT_TOKENS_PER_PAGE токенов).
        return _credits_for_tokens(_document_tokens_per_page(), coeff)

    if category == "image":
        return _image_credits(model)

    if category == "video":
        return _video_credits(model)

    logger.warning("credit_value: неизвестная категория %r", category)
    return None


_ACTIVE_PACKAGES_CACHE_KEY = "credit_value:active_packages_by_price"
_ACTIVE_PACKAGES_CACHE_TTL = 30  # секунд — коротко, чтобы правки пакетов из админки подхватывались быстро.


def _active_packages_by_price() -> list:
    """Активные TokenPackage от самого дешёвого к самому дорогому (по price,
    затем sort_order/id для детерминизма) — порядок эскалации для
    estimate_model_usage_cost(): база "от" — это "Старт", но если coeff модели
    дороже целого "Старта" (например, Veo 3.1/coeff=83, Sora 2 Pro/coeff=62,
    Seedance 2.0/coeff=32 — per_unit кредитов больше, чем total_credits
    "Старта"), пробуем следующий по цене пакет, пока не наберётся count >= 1
    хотя бы у одного активного пакета.

    Кэшируется на _ACTIVE_PACKAGES_CACHE_TTL секунд (django cache): без этого
    get_estimated_usage() в AiModelSerializer вызывает это на КАЖДУЮ модель в
    списке (N+1 на публичном GET /api/ai/models/, ~N одинаковых запросов ради
    одной и той же таблицы из нескольких строк). Список пакетов меняется редко
    и не денежно-чувствителен здесь (только для оценки "на что хватит", не для
    реального списания), поэтому короткий TTL — безопасный компромисс.
    """
    from django.core.cache import cache
    from .models import TokenPackage

    cached = cache.get(_ACTIVE_PACKAGES_CACHE_KEY)
    if cached is not None:
        return cached

    packages = list(
        TokenPackage.objects.filter(is_active=True)
        .order_by("price", "sort_order", "id")
    )
    try:
        cache.set(_ACTIVE_PACKAGES_CACHE_KEY, packages, _ACTIVE_PACKAGES_CACHE_TTL)
    except Exception:
        logger.exception("credit_value: не удалось закэшировать active_packages_by_price")
    return packages


# category (GPTModels.CATEGORY_CHOICES) -> русская подпись единицы измерения
# для estimate_model_usage_cost(). Категории вне этой карты (chat/writing/
# reasoning/fast/budget/search/coding) билятся как текст (см. _credits_for_tokens)
# и получают дефолтную подпись "ответов".
_MODEL_UNIT_LABELS = {
    "image": "картинок",
    "video": "видео",
}
_MODEL_UNIT_LABEL_DEFAULT = "ответов"

# Категории, которые считаются "текстовыми" для оценки использования (билятся
# токенной формулой, как chat) — coding тоже текстовый вывод по механизму
# биллинга, просто другая специализация модели.
_TEXT_LIKE_CATEGORIES = {
    "chat", "writing", "reasoning", "fast", "budget", "search", "coding",
}


def estimate_model_usage_cost(model) -> dict | None:
    """"Что получит пользователь за один пакет на ЭТОЙ модели" — оценка для
    карточки каталога AI-моделей (Этап 4, п.2), работает для ЛЮБОЙ активной
    GPTModels, а не только для 4 категорийных эталонов калькулятора "На что
    хватит?" (compute_package_value/credits_per_unit выше).

    База "от" — самый дешёвый активный пакет ("Старт"). НО если per_unit этой
    конкретной модели дороже, чем весь "Старт" целиком (per-unit коэффициент
    ставит модель в дорогую категорию — на проде это флагманские видео: Veo
    3.1/coeff=83, Sora 2 Pro/coeff=62, Seedance 2.0/coeff=32 — "Старт" не даёт
    ни одного целого ролика), функция ЭСКАЛИРУЕТ: перебирает активные пакеты
    от самого дешёвого к самому дорогому (_active_packages_by_price) и
    возвращает результат для ПЕРВОГО пакета, где count >= 1. Иначе на
    /models такие модели показывали бы "нет данных" вместо честной оценки —
    хуже, чем сказать "от N штук на пакете 'Максимум'".

    package_name в результате — реальное имя пакета, на котором расчёт
    получился (не всегда "Старт").

    Переиспользует ТЕ ЖЕ low-level формулы, что calculator "На что хватит" —
    _credits_for_tokens/_text_tokens_per_reply для текстовых категорий,
    _image_credits(model)/_video_credits(model) для image/video (обе уже
    принимают ПРОИЗВОЛЬНУЮ модель, не только эталонную) — никакого
    дублирования формул списания.

    Возвращает {"count": int, "unit_label": str, "package_name": str} либо
    None, если оценить нечего (нет активных пакетов, нет тарифа у модели, или
    ДАЖЕ самый дорогой активный пакет не даёт ни одной целой единицы — на
    практике не встречается: "Максимум" перекрывает любую разумную стоимость
    одной генерации) — вызывающий сериализатор обязан пережить None молча
    (поле каталога просто не показывает блок оценки).
    """
    if model is None:
        return None

    packages = _active_packages_by_price()
    if not packages:
        return None

    category = str(getattr(model, "category", "") or "")

    if category == "image":
        per_unit = _image_credits(model)
    elif category == "video":
        per_unit = _video_credits(model)
    else:
        # chat/writing/reasoning/fast/budget/search/coding — та же токенная
        # формула, что и text-категория калькулятора "На что хватит".
        coeff = model.markup_coefficient
        if coeff is None:
            return None
        per_unit = _credits_for_tokens(_text_tokens_per_reply(), coeff)

    if not per_unit or per_unit <= 0:
        return None

    unit_label = _MODEL_UNIT_LABELS.get(category, _MODEL_UNIT_LABEL_DEFAULT)

    for package in packages:
        total_credits = int(getattr(package, "tokens", 0) or 0) + \
            int(getattr(package, "bonus_tokens", 0) or 0)
        if total_credits <= 0:
            continue
        count = int(
            (Decimal(total_credits) / per_unit).to_integral_value(rounding=ROUND_FLOOR)
        )
        if count >= 1:
            return {
                "count": count,
                "unit_label": unit_label,
                "package_name": package.name,
            }

    # Даже самый дорогой активный пакет не даёт ни одной целой единицы.
    return None


def compute_package_value(package) -> dict:
    """{category: {count, unit_model_name}} для всех 4 категорий одного пакета.

    Категория ОТСУТСТВУЕТ в результате, если для неё нет эталонной модели
    (не настроена/не активна) — так фронт может просто не показать блок,
    не роняя весь расчёт.

    НЕ включает "recommended" — это кросс-пакетное сравнение (см.
    _mark_recommended), которое требует знать value ВСЕХ активных пакетов
    сразу, а не одного; выставляется только из compute_all_packages_value().
    """
    total_credits = int(getattr(package, "tokens", 0) or 0) + \
        int(getattr(package, "bonus_tokens", 0) or 0)

    result: dict = {}
    for category in ("text", "image", "video", "document"):
        model = get_reference_model(category)
        if model is None:
            continue
        per_unit = credits_per_unit(category, model=model)
        if not per_unit or per_unit <= 0:
            continue
        count = int(
            (Decimal(total_credits) / per_unit).to_integral_value(rounding=ROUND_FLOOR)
        )
        if count < 1:
            # Пакет не даёт НИ ОДНОЙ целой единицы этой категории на эталонной
            # модели (см. docstring estimate_model_usage_cost про Veo 3.1/Sora 2
            # Pro и т.п.) — как "нет данных" для этой категории у этого пакета,
            # а не карточка "До 0 видео/картинок". Симметрично с пропуском
            # категорий без эталонной модели/тарифа выше.
            continue
        result[category] = {
            "count": count,
            "unit_model_name": model.name,
        }
    return result


# credit_calc-категория -> settings-атрибут с дефолтным порогом "min_count"
# (калькулятор "На что хватит?", Этап 3 п.14 — см. _mark_recommended).
_CATEGORY_MIN_COUNT_SETTINGS_ATTR = {
    "text": "CREDIT_CALC_TEXT_MIN_COUNT",
    "image": "CREDIT_CALC_IMAGE_MIN_COUNT",
    "video": "CREDIT_CALC_VIDEO_MIN_COUNT",
    "document": "CREDIT_CALC_DOCUMENT_MIN_COUNT",
}

# Зашитые дефолты на случай, если даже settings-атрибута нет (не должно
# происходить в норме — settings.py всегда их определяет) — согласованы с
# клиентом 2026-07-16.
_CATEGORY_MIN_COUNT_HARDCODED_DEFAULT = {
    "text": 200,
    "image": 100,
    "video": 5,
    "document": 200,
}


def _min_count_for_category(category: str) -> int:
    """Порог "разумно полезного объёма" для категории — см. docstring
    settings.CREDIT_CALC_<CATEGORY>_MIN_COUNT. Runtime-переопределяемо из
    админки (ключ credit_calc_<category>_min_count) без рестарта.

    0 — валидный порог (означает "рекомендуй самый дешёвый пакет всегда",
    т.к. любой count >= 0). Отрицательные/битые значения не должны попасть
    в БД (PATCH /api/manage/settings/ валидирует >= 0), но на всякий случай
    подстрахованы фолбэком на default, как и остальные get_runtime-обёртки
    в этом файле.
    """
    from django.conf import settings as dj_settings

    hardcoded = _CATEGORY_MIN_COUNT_HARDCODED_DEFAULT.get(category, 0)
    settings_attr = _CATEGORY_MIN_COUNT_SETTINGS_ATTR.get(category)
    default = int(getattr(dj_settings, settings_attr, hardcoded)) if settings_attr else hardcoded

    try:
        from adminapi.runtime import get_runtime
        value = int(get_runtime(f"credit_calc_{category}_min_count", default))
    except Exception:
        value = default
    return value if value >= 0 else default


def _mark_recommended(category: str, pkg_list: list, values: dict) -> None:
    """Проставить recommended=True ровно одному пакету для category (мутирует
    values in-place) — "лучший выбор" под сценарий использования калькулятора
    "На что хватит?" (Этап 3, п.14):

    - среди пакетов, у которых value[category] присутствует И
      value[category]['count'] >= порога категории (_min_count_for_category),
      выбирается САМЫЙ ДЕШЁВЫЙ (Decimal price; при равной цене — меньший
      sort_order, затем меньший id, для детерминизма);
    - если ни один пакет не достиг порога — выбирается САМЫЙ ДОРОГОЙ среди
      пакетов, у которых категория вообще присутствует (обычно "Максимум").

    Это ОТДЕЛЬНАЯ ось от TokenPackage.featured (см. models.py) — featured
    выделяет пакет визуально по умолчанию вне зависимости от сценария,
    recommended зависит от выбранной клиентом категории использования.

    Пакеты без этой категории в value (нет эталонной модели) полностью
    исключены из сравнения. Если категория отсутствует у ВСЕХ активных
    пакетов — ничего не помечается.
    """
    eligible = [pkg for pkg in pkg_list if category in values.get(pkg.id, {})]
    for pkg in eligible:
        values[pkg.id][category]["recommended"] = False
    if not eligible:
        return

    threshold = _min_count_for_category(category)
    meets = [pkg for pkg in eligible if values[pkg.id][category]["count"] >= threshold]

    if meets:
        winner = min(meets, key=lambda p: (p.price, p.sort_order, p.id))
    else:
        winner = max(eligible, key=lambda p: (p.price, p.sort_order, p.id))

    values[winner.id][category]["recommended"] = True


def compute_all_packages_value() -> list[dict]:
    """Расчёт value для всех активных TokenPackage, отсортированных по sort_order.

    Каждый элемент — словарь с базовыми полями пакета + вложенный "value"
    (см. compute_package_value), где КАЖДАЯ присутствующая категория
    дополнительно несёт "recommended": bool (см. _mark_recommended) — ровно
    один пакет на категорию помечен рекомендованным под сценарий "На что
    хватит?" (Этап 3, п.14). Используется публичным API
    GET /api/plans/packages/value/.
    """
    from .models import TokenPackage

    pkg_list = list(TokenPackage.objects.filter(is_active=True).order_by("sort_order", "id"))
    values = {pkg.id: compute_package_value(pkg) for pkg in pkg_list}

    for category in ("text", "image", "video", "document"):
        _mark_recommended(category, pkg_list, values)

    out = []
    for pkg in pkg_list:
        out.append({
            "id": pkg.id,
            "name": pkg.name,
            "tokens": pkg.tokens,
            "bonus_tokens": pkg.bonus_tokens,
            "price": str(pkg.price),
            "currency": pkg.currency,
            "badge": pkg.badge,
            "featured": pkg.featured,
            "sort_order": pkg.sort_order,
            "value": values[pkg.id],
        })
    return out
