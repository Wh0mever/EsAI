from __future__ import annotations

import logging
from datetime import timedelta
from typing import Tuple

from django.db import transaction
from django.utils import timezone

from plans.models import (
    Plan,
    UserSubscription,
    SubscriptionStatus,
    PaymentStatus,
    GenerationUsage,
)
from plans.services import plan_cycle_days
from .models import User, UserCardBind, Notification, NotificationDelivery


logger = logging.getLogger("plans")

FREE_TRIGGER_FIRST_GEN = "Хочешь ещё? В платных тарифах больше лимитов"
FREE_TRIGGER_LOW_LIMIT = "Лимиты почти закончились"
FREE_TRIGGER_LAST_DAY = "Сегодня последний день бесплатного доступа"


def activate_free_plan_for_user(user: User) -> Tuple[bool, str]:
    """
    Легаси-подписки Vokalo сняты: больше НЕ создаём UserSubscription.

    Безопасный no-op. Возвращаем кортеж (False, "subscriptions_deprecated"),
    чтобы пережили все каллеры — включая тот, что распаковывает результат
    (`activated, _ = activate_free_plan_for_user(...)`): он просто не активирует
    подписку. Бизнес-доступ теперь даёт pay-as-you-go токен-система.
    """
    return False, "subscriptions_deprecated"


# --- EsAI Creators ----------------------------------------------------------
# Код креатора — отдельная программа (комиссия в USDT), а не referred_by.
# Все обращения к ней ленивые и в try/except: сбой программы не должен ломать
# ни регистрацию, ни обычные промокоды.

# Отказы при вводе кода креатора: клиентский код -> текст. Кортеж
# activate_promo код нести не может, поэтому PromoActivateView находит его по
# тексту (creator_promo_code) — интерфейсам en/kg нужен код, а не русская фраза.
CREATOR_PROMO_MESSAGES = {
    "self": "Нельзя использовать собственный промокод",
    "staff": "Промокод недоступен для этого аккаунта",
    "already_bound": "Вы уже закреплены за другим креатором",
    "has_referrer": "Вы уже зарегистрированы по приглашению — промокод креатора применить нельзя",
    "too_late": "Промокод креатора можно ввести только в первые 72 часа после регистрации",
    "already_paid": "Промокод креатора можно ввести только до первой оплаты",
    "not_found": "Промокод не найден или неактивен",
    "retry": "Не удалось активировать промокод, попробуйте позже",
}

# Причина отказа привязки -> клиентский код. Чего здесь нет — "retry".
_CREATOR_BIND_CODES = {
    "self": "self",
    "staff": "staff",
    "already_bound": "already_bound",
    "has_referrer": "has_referrer",
    "too_late": "too_late",
    "already_paid": "already_paid",
    "creator_unusable": "not_found",
    "disabled": "not_found",
    "no_user": "not_found",
}


def creator_promo_code(message: str) -> str:
    """Клиентский код отказа по тексту, который вернул activate_promo."""
    for client_code, text in CREATOR_PROMO_MESSAGES.items():
        if text == message:
            return client_code
    return "error"


def _signup_typed_code(request) -> str:
    """Промокод, введённый при регистрации (читается так же, как в
    maybe_activate_promo_on_signup): cookie `esai_promo`, иначе тело запроса."""
    code = ""
    try:
        code = (request.COOKIES.get("esai_promo") or "").strip()
    except Exception:
        code = ""
    if not code:
        try:
            data = getattr(request, "data", None) or {}
            code = str(data.get("promo") or data.get("promo_code") or "").strip()
        except Exception:
            code = ""
    return code


def _creator_code(raw):
    """Действующий код креатора (CreatorCode) или None."""
    try:
        from creators.attribution import creator_code

        return creator_code(raw)
    except Exception:
        logger.exception("creator code lookup failed")
        return None


# После этих ответов привязки человек закреплён за креатором (за этим или за
# другим): обычного реферера ему уже не ставим.
_CREATOR_BOUND_REASONS = ("already_bound_same", "already_bound", "race")


def _bind_creator(user, hit, source: str, *, bot_arrival: bool = False) -> bool:
    """Привязать нового пользователя к креатору найденного кода. Отказ — не ошибка.

    True — человек теперь закреплён за креатором. Сбой программы — тоже True:
    не зная, состоялась ли привязка, обычного реферера рядом не ставим.
    """
    try:
        if bot_arrival:
            # Приход из бота сайт не видит: без этой строки «Переходов» у
            # креатора было бы меньше, чем «Регистраций».
            from creators.clicks import record_bot

            record_bot(hit, user)
        from creators.attribution import bind

        res = bind(user, hit.creator, source=source, code_used=hit.code)
        logger.info("creator bind: user %s code=%s source=%s -> %s",
                    user.pk, hit.code, source, "ok" if res.ok else res.reason)
        return bool(res.ok or res.reason in _CREATOR_BOUND_REASONS)
    except Exception:
        logger.exception("creator bind failed")
        return True


def _activate_creator_code(user, norm) -> "Tuple[bool, str, int] | None":
    """Код креатора в поле промокода: привязка без начисления кредитов.

    None — это не код креатора (или программа выключена): activate_promo
    отвечает «не найден», как раньше.
    """
    try:
        from creators.attribution import bind_by_typed_code

        res = bind_by_typed_code(user, norm)
    except Exception:
        logger.exception("creator promo failed for code=%s user=%s", norm, getattr(user, "pk", None))
        return None
    if res is None:
        return None
    if res.ok or res.reason == "already_bound_same":
        # Повторный ввод того же кода — тот же дружелюбный ответ, а не ошибка.
        name = res.referral.creator.display_name
        return True, f"Промокод принят — вы пришли по приглашению {name}", 0
    return False, CREATOR_PROMO_MESSAGES[_CREATOR_BIND_CODES.get(res.reason, "retry")], 0


def maybe_link_referrer(request, new_user, code: str = "") -> None:
    """Привязать реферера к новому пользователю при регистрации по реф-ссылке.

    Реф-код берём из аргумента (так его передаёт бот из ссылки
    t.me/<bot>?start=ref_XXX), иначе из cookie `esai_ref` (её ставит фронт при
    переходе по реф-ссылке — атрибуция переживает и email-OTP, и соц-вход),
    иначе из поля `ref` в теле запроса.

    Привязываем ТОЛЬКО что созданному аккаунту (моложе 10 минут). Иначе
    достаточно разослать свою ссылку старым пользователям — и получать процент
    с чужих покупок, к которым приглашение отношения не имело.

    РЕШЕНИЕ КЛИЕНТА: разовый бонус за регистрацию УБРАН. Вместо этого просто
    фиксируем реферера в new_user.referred_by. Начисление 10% происходит позже —
    при КАЖДОМ пополнении приглашённого (пожизненно), см. payments/tasks.py.

    Идемпотентно: привязываем ТОЛЬКО если referred_by ещё пуст. Защита от
    самонакрутки (referrer != new_user). Кредиты здесь НЕ начисляются.
    """
    try:
        if not new_user or not getattr(new_user, "pk", None):
            return
        # Идемпотентность: реферер ставится один раз и не переписывается.
        if getattr(new_user, "referred_by_id", None):
            return
        code = (code or "").strip()
        # Код пришёл аргументом — значит, из бота (t.me/<bot>?start=ref_XXX).
        from_arg = bool(code)
        if not code:
            try:
                code = (request.COOKIES.get("esai_ref") or "").strip()
            except Exception:
                code = ""
        if not code:
            try:
                code = str(((getattr(request, "data", None) or {}).get("ref") or "")).strip()
            except Exception:
                code = ""
        if not code:
            return
        # Только для свежего аккаунта: реферер — тот, по чьей ссылке пришли
        # регистрироваться, а не тот, кто прислал ссылку год спустя.
        joined = getattr(new_user, "date_joined", None)
        if joined is not None:
            from datetime import timedelta

            from django.utils import timezone as _tz

            if _tz.now() - joined > timedelta(minutes=10):
                return
        # EsAI Creators. Введённый при регистрации промокод креатора сильнее
        # реф-ссылки: человек сам назвал, кто его пригласил.
        typed = _signup_typed_code(request)
        if typed and typed.strip().upper() != code.upper():
            hit = _creator_code(typed)
            # Отказ привязки (креатор заблокирован, код не для этого аккаунта)
            # не отменяет ссылку, по которой человек пришёл: иначе пригласивший
            # по обычной программе терял бы его навсегда.
            if hit and _bind_creator(new_user, hit, "promo"):
                return
        # Ссылка креатора (?ref=CODE или start=ref_CODE). Что бы ни ответила
        # привязка, в referred_by код креатора не попадает никогда: иначе с
        # одного покупателя платили бы и комиссию, и 10% кредитами.
        hit = _creator_code(code)
        if hit:
            _bind_creator(new_user, hit, "bot" if from_arg else "link", bot_arrival=from_arg)
            return
        referrer = User.objects.filter(referral_uid__iexact=code).first()
        if not referrer and code.isdigit():
            referrer = User.objects.filter(pk=int(code)).first()
        if not referrer or referrer.pk == new_user.pk:
            return
        new_user.referred_by = referrer
        new_user.save(update_fields=["referred_by"])
        logger.info("referrer linked: user %s referred_by %s (code=%s)",
                    new_user.pk, referrer.pk, code)
    except Exception:
        logger.exception("maybe_link_referrer failed")


# Обратная совместимость: старое имя вызывается из views.py и adapters.py.
# Оставляем алиас, чтобы не трогать чужие вызовы (сигнатура идентична).
maybe_grant_referral_bonus = maybe_link_referrer


def activate_promo(user, code: str) -> Tuple[bool, str, int]:
    """Активировать промокод для пользователя. Возвращает (ok, msg, credited).

    Промокод даёт ФИКСИРОВАННОЕ число кредитов (без процентов). Все проверки и
    начисление выполняются атомарно под select_for_update по строке PromoCode,
    чтобы параллельные активации (двойной клик/гонка) не пробили лимиты.

    Проверки: код существует и активен; не истёк (expires_at); не исчерпан
    (used_count < max_activations, если задан); per_user_once → нет прошлой
    активации этим юзером; new_users_only → пользователь ещё не платил (is_paid).
    """
    from django.db import transaction as _tx
    from plans.models import PromoCode, PromoActivation
    from plans.wallet import credit_tokens

    if not user or not getattr(user, "pk", None):
        return False, "Требуется авторизация", 0

    norm = (code or "").strip().upper()
    if not norm:
        return False, "Введите промокод", 0

    try:
        with _tx.atomic():
            promo = (
                PromoCode.objects
                .select_for_update()
                .filter(code=norm, is_active=True)
                .first()
            )
            if not promo:
                creator_result = _activate_creator_code(user, norm)
                if creator_result is not None:
                    return creator_result
                return False, "Промокод не найден или неактивен", 0

            if promo.expires_at and promo.expires_at <= timezone.now():
                return False, "Срок действия промокода истёк", 0

            if promo.max_activations is not None and promo.used_count >= promo.max_activations:
                return False, "Лимит активаций промокода исчерпан", 0

            if promo.new_users_only and getattr(user, "is_paid", False):
                return False, "Промокод доступен только новым пользователям", 0

            if promo.per_user_once and PromoActivation.objects.filter(promo=promo, user=user).exists():
                return False, "Вы уже активировали этот промокод", 0

            # Двойная страховка от гонки: unique(promo,user) в PromoActivation.
            # ВАЖНО: create заворачиваем в ВЛОЖЕННЫЙ atomic (savepoint). На
            # PostgreSQL любой IntegrityError переводит транзакцию в состояние
            # "needs rollback" — без savepoint внешний atomic на выходе упал бы
            # TransactionManagementError вместо чистого возврата. Savepoint
            # откатывает только неудачный INSERT, внешняя транзакция остаётся живой.
            try:
                with _tx.atomic():
                    PromoActivation.objects.create(
                        promo=promo, user=user, credited=promo.bonus_credits,
                    )
            except Exception:
                # Уникальный конфликт (параллельная активация) — считаем уже активированным.
                return False, "Вы уже активировали этот промокод", 0

            promo.used_count = (promo.used_count or 0) + 1
            promo.save(update_fields=["used_count"])

            credited = int(promo.bonus_credits or 0)
            new_balance = credit_tokens(user, credited, "promo", meta={"code": norm})

        logger.info("promo %s activated by user %s (+%s credits)", norm, user.pk, credited)
        return True, "Промокод активирован", credited
    except Exception:
        logger.exception("activate_promo failed for code=%s user=%s", norm, getattr(user, "pk", None))
        return False, "Не удалось активировать промокод, попробуйте позже", 0


def maybe_activate_promo_on_signup(request, new_user) -> None:
    """Опционально активировать промокод при регистрации (тихо, ошибки глотаем).

    Код берётся из cookie `esai_promo` или поля `promo`/`promo_code` в теле
    запроса. Любые ошибки/провалы валидации не влияют на регистрацию.
    """
    try:
        if not new_user or not getattr(new_user, "pk", None):
            return
        code = ""
        try:
            code = (request.COOKIES.get("esai_promo") or "").strip()
        except Exception:
            code = ""
        if not code:
            try:
                data = getattr(request, "data", None) or {}
                code = (data.get("promo") or data.get("promo_code") or "").strip()
            except Exception:
                code = ""
        if not code:
            return
        activate_promo(new_user, code)
    except Exception:
        logger.exception("maybe_activate_promo_on_signup failed")


def _notify_user_once(user: User, title: str) -> bool:
    if not user or not title:
        return False
    exists = NotificationDelivery.objects.filter(
        recipient=user,
        notification__title=title,
    ).exists()
    if exists:
        return False
    n = Notification.objects.create(title=title, body="")
    NotificationDelivery.objects.get_or_create(notification=n, recipient=user)
    return True


def _calc_plan_initial_and_left(sub: UserSubscription, usage: GenerationUsage) -> tuple[int, int, int]:
    plan = sub.plan
    resources = (
        ("text_limit", "texts_left"),
        ("image_limit", "images_left"),
        ("song_limit", "songs_left"),
        ("music_limit", "music_left"),
    )
    initial_total = 0
    left_total = 0
    consumed_total = 0
    for limit_attr, left_attr in resources:
        limit = int(getattr(plan, limit_attr, 0) or 0)
        if limit <= 0:
            continue
        left = int(getattr(usage, left_attr, 0) or 0)
        initial_total += limit
        left_total += max(left, 0)
        consumed_total += max(limit - left, 0)
    return initial_total, left_total, consumed_total


def process_free_plan_triggers(sub: UserSubscription) -> dict[str, bool]:
    """
    Emit one-time notifications for free-plan milestones:
    1) first successful generation
    2) 20% limits remaining
    3) last day of free access
    """
    result = {"first_gen": False, "low_limits": False, "last_day": False}
    if not sub or not getattr(sub, "plan", None) or not sub.plan.is_free:
        return result
    if str(sub.status or "").lower() != SubscriptionStatus.ACTIVE:
        return result

    usage, _ = GenerationUsage.objects.get_or_create(subscription=sub)
    initial_total, left_total, consumed_total = _calc_plan_initial_and_left(sub, usage)

    if consumed_total >= 1:
        result["first_gen"] = _notify_user_once(sub.user, FREE_TRIGGER_FIRST_GEN)

    if initial_total > 0 and (left_total / initial_total) <= 0.2:
        result["low_limits"] = _notify_user_once(sub.user, FREE_TRIGGER_LOW_LIMIT)

    if sub.end_date and sub.end_date.date() == timezone.localdate():
        result["last_day"] = _notify_user_once(sub.user, FREE_TRIGGER_LAST_DAY)

    return result
