"""Привязка пользователя к креатору.

Привязка — отдельная строка CreatorReferral, а не User.referred_by: обычная
реферальная программа живёт рядом и не меняется. Строку пишет только bind().

Правила (решение клиента):
- по ссылке и из бота — только при регистрации (10 минут, последний переход);
- по введённому промокоду — при регистрации или в первые 72 часа и до первой оплаты;
- одна действующая привязка на человека; себя и сотрудников не привязываем;
- у кого уже есть обычный реферер, того привязывает только администратор.

Подозрительную привязку (то же устройство, повторная регистрация) не
отклоняем, а помечаем: отказ молча потерял бы атрибуцию и спрятал схему.
Помеченная не считается регистрацией, её комиссии копятся в held, креатор о
ней не узнаёт — пока администратор не снимет пометку.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from audit.services import log_admin_action

from . import flags, notify, stats
from .codes import CODE_RE, normalize
from .errors import CreatorsError
from .models import (
    Creator,
    CreatorApplication,
    CreatorCode,
    CreatorCommission,
    CreatorReferral,
)

logger = logging.getLogger("creators")

# Сколько неудачных вводов кода креатора прощаем за час: дальше любой код
# «не найден», иначе полем промокода можно перебирать чужие коды.
TYPED_FAIL_LIMIT = 10
TYPED_FAIL_TTL = 3600

_SELF_SOURCES = ("link", "bot", "promo")


@dataclass(frozen=True)
class BindResult:
    ok: bool
    reason: str = ""                       # "" при успехе; иначе стабильный код отказа
    referral: "CreatorReferral | None" = None


# ------------------------------------------------------------------ поиск ---

def creator_code(raw) -> "CreatorCode | None":
    """Действующий код креатора или None. В режиме off кодов нет вовсе."""
    if flags.is_off():
        return None
    norm = normalize(raw)
    if not CODE_RE.match(norm):
        return None
    return (CreatorCode.objects.filter(code=norm, is_active=True)
            .select_related("creator", "creator__user", "creator__level").first())


def resolve_code(raw) -> "tuple[str, object] | None":
    """Чей это код: ("creator", CreatorCode) | ("user", User) | None.

    Код креатора начинается с буквы и делит пространство имён с referral_uid,
    поэтому порядок проверок неоднозначности не создаёт, а старые числовые
    ссылки (id пользователя) продолжают работать.
    """
    code = str(raw or "").strip()
    if not code:
        return None
    row = creator_code(code)
    if row is not None:
        return "creator", row
    User = get_user_model()
    user = User.objects.filter(referral_uid__iexact=code).first()
    if user is None and code.isdigit():
        user = User.objects.filter(pk=int(code)).first()
    return ("user", user) if user is not None else None


# --------------------------------------------------------------- признаки ---

def _mask(user) -> str:
    """Имя приглашённого для уведомления — без почты и id."""
    try:
        from users.views import _mask_user_label

        return _mask_user_label(user)
    except Exception:  # noqa: BLE001
        return "—"


def _telegram_uid(user_pk) -> str:
    from allauth.socialaccount.models import SocialAccount

    return str(SocialAccount.objects.filter(user_id=user_pk, provider="telegram")
               .values_list("uid", flat=True).first() or "")


def _was_deleted_before(telegram_uid) -> bool:
    """Заводил ли этот Telegram аккаунт, погашенный по /delete.

    Функция живёт в чужом файле: если её нет или она упала — признака нет,
    а привязка всё равно состоится.
    """
    try:
        from botapi.services import was_deleted_before

        with transaction.atomic():
            return bool(was_deleted_before(telegram_uid))
    except Exception:  # noqa: BLE001
        return False


def _device_match(reasons) -> bool:
    """Есть ли среди признаков совпадение устройства (с креатором или его рефералом)."""
    return any(str(reason).startswith("same_device_") for reason in reasons)


def _telegram_seen_before(telegram_uid, user_pk) -> bool:
    """Был ли этот Telegram раньше привязан к другому аккаунту.

    Привязку и отвязку Telegram (в том числе /delete в боте) пишет в журнал
    botapi.linking, с telegram_id в meta. Погашенная заглушка сама Telegram id
    не хранит, так что журнал — единственный след прежнего аккаунта человека,
    который раньше не был ничьим рефералом. Журнал недоступен — признака нет.
    """
    try:
        from audit.models import EventLog

        with transaction.atomic():
            return (EventLog.objects.filter(type="other", meta__telegram_id=str(telegram_uid))
                    .exclude(user_id=user_pk).exists())
    except Exception:  # noqa: BLE001
        return False


def _evidence(user, creator, source: str) -> dict:
    """Слепок устройства и признаки накрутки на момент привязки."""
    from audit.models import SignupDevice

    device = SignupDevice.objects.filter(user_id=user.pk).order_by("-created_at").first()
    ip = getattr(device, "ip", None) or None
    subnet = str(getattr(device, "subnet", "") or "")
    fingerprint = str(getattr(device, "fingerprint", "") or "")
    telegram_uid = _telegram_uid(user.pk)

    reasons = []
    if fingerprint and SignupDevice.objects.filter(user_id=creator.user_id,
                                                   fingerprint=fingerprint).exists():
        reasons.append("same_device_as_creator")
    if fingerprint and (CreatorReferral.objects
                        .filter(creator=creator, fingerprint=fingerprint, ended_at__isnull=True)
                        .exclude(user_id=user.pk).exists()):
        reasons.append("same_device_as_referral")
    # Общий IP — только пометка: за одним адресом оператора сидят тысячи людей.
    if ip and SignupDevice.objects.filter(user_id=creator.user_id, ip=ip).exists():
        reasons.append("same_ip_as_creator")
    # Ручную привязку администратора повторной регистрацией не считаем.
    if source in _SELF_SOURCES:
        repeat = bool(telegram_uid) and (
            CreatorReferral.objects.filter(telegram_uid=telegram_uid)
            .exclude(user_id=user.pk).exists()
            or _was_deleted_before(telegram_uid)
            or _telegram_seen_before(telegram_uid, user.pk))
        # С этого устройства уже заводили другой аккаунт (ТЗ п.35: повторная
        # регистрация не создаёт нового реферала). Совпадение с устройством
        # креатора или его реферала названо выше точнее — второй раз не пишем.
        if not repeat and fingerprint and not _device_match(reasons):
            repeat = SignupDevice.objects.filter(fingerprint=fingerprint).exclude(
                user_id=user.pk).exists()
        if repeat:
            reasons.append("repeat_registration")

    suspect = _device_match(reasons) or "repeat_registration" in reasons
    return {"ip": ip, "subnet": subnet[:64], "fingerprint": fingerprint[:128],
            "telegram_uid": telegram_uid[:32], "reasons": reasons, "suspect": suspect}


def _announce(creator, user) -> None:
    """Креатор узнаёт о новом реферале; заодно проверяем условия уровня."""
    try:
        notify.emit(creator, "new_referral", user_label=_mask(user))
        stats.check_next_level(creator)
    except Exception:  # noqa: BLE001 — привязка уже записана
        logger.exception("creators.attribution: уведомление о реферале не поставлено")


# --------------------------------------------------------------- привязка ---

def _bind(user, creator, *, source: str, code_used: str = "", actor=None, force: bool = False,
          at=None) -> BindResult:
    if flags.is_off():
        return BindResult(False, "disabled")
    if user is None or not getattr(user, "pk", None) or not getattr(user, "is_active", False):
        return BindResult(False, "no_user")
    User = get_user_model()
    with transaction.atomic():
        # Строка пользователя — замок привязки: два одновременных ввода кода
        # одним человеком выстраиваются в очередь.
        u = User.objects.select_for_update().filter(pk=user.pk).first()
        if u is None or not u.is_active:
            return BindResult(False, "no_user")
        # Креатора перечитываем: статус мог измениться, пока объект лежал у вызывающего.
        creator = (Creator.objects.select_related("user", "level")
                   .filter(pk=getattr(creator, "pk", None)).first())
        if creator is None or not flags.creator_usable(creator):
            return BindResult(False, "creator_unusable")
        if creator.user_id == u.pk:
            return BindResult(False, "self")
        if u.is_staff or u.is_superuser:
            return BindResult(False, "staff")
        active = CreatorReferral.objects.active_for(u.pk)
        if active is not None:
            if active.creator_id == creator.pk:
                return BindResult(False, "already_bound_same", active)
            return BindResult(False, "already_bound")
        now = at or timezone.now()
        if not force:
            if u.referred_by_id:
                return BindResult(False, "has_referrer")
            age = timezone.now() - u.date_joined
            if source in ("link", "bot") and age > timedelta(minutes=flags.LINK_WINDOW_MINUTES):
                return BindResult(False, "link_window")
            if source == "promo":
                if age > timedelta(hours=flags.BIND_WINDOW_HOURS):
                    return BindResult(False, "too_late")
                if u.first_paid_at is not None or u.is_paid:
                    return BindResult(False, "already_paid")

        seen = _evidence(u, creator, source)
        try:
            with transaction.atomic():
                referral = CreatorReferral.objects.create(
                    user=u, creator=creator, source=source, code_used=normalize(code_used)[:16],
                    bound_at=now, bound_by=actor, suspect=seen["suspect"],
                    flags={"reasons": seen["reasons"]}, ip=seen["ip"], subnet=seen["subnet"],
                    fingerprint=seen["fingerprint"], telegram_uid=seen["telegram_uid"])
        except IntegrityError:
            # Вторую действующую привязку не дал уникальный индекс.
            return BindResult(False, "race")
        if not referral.suspect:
            _announce(creator, u)
    return BindResult(True, "", referral)


def bind(user, creator, *, source: str, code_used: str = "", actor=None,
         force: bool = False) -> BindResult:
    """Привязать пользователя к креатору. Единственное место, где создаётся CreatorReferral.

    Отказ — не исключение, а BindResult(ok=False, reason=код).
    force=True (ручная привязка администратором) снимает окна по времени,
    запрет после оплаты и запрет при обычном реферере; «сам себя»,
    сотрудника и недоступного креатора не снимает ничто.
    """
    return _bind(user, creator, source=source, code_used=code_used, actor=actor, force=force)


def _typed_fail(key: str) -> None:
    if cache.add(key, 1, TYPED_FAIL_TTL):
        return
    try:
        cache.incr(key)
    except ValueError:
        cache.set(key, 1, TYPED_FAIL_TTL)


def bind_by_typed_code(user, raw) -> "BindResult | None":
    """Код, введённый в поле промокода.

    None — «это не код креатора»: вызывающий отвечает «промокод не найден»
    как раньше.
    """
    if flags.is_off() or user is None or not getattr(user, "pk", None):
        return None
    key = f"creators:typed_fail:{user.pk}"
    if int(cache.get(key) or 0) >= TYPED_FAIL_LIMIT:
        return None
    row = creator_code(raw)
    if row is None:
        _typed_fail(key)
        return None
    result = bind(user, row.creator, source="promo", code_used=row.code)
    if not result.ok and result.reason != "already_bound_same":
        _typed_fail(key)
    return result


# ---------------------------------------------------------- администратор ---

def rebind(user, creator, *, actor, reason: str, request=None) -> "CreatorReferral | None":
    """Перепривязать пользователя вручную; creator=None — снять привязку.

    Меняет судьбу только заказов, оплаченных после перепривязки: прошлые
    комиссии остаются у прежнего креатора. User.referred_by не трогаем.
    """
    reason = str(reason or "").strip()
    if not reason:
        raise CreatorsError("reason_required")
    User = get_user_model()
    with transaction.atomic():
        u = User.objects.select_for_update().filter(pk=getattr(user, "pk", None)).first()
        if u is None:
            raise CreatorsError("not_found")
        old = CreatorReferral.objects.active_for(u.pk)
        if old is None and creator is None:
            # Снимать нечего — пустую строку в журнал не пишем.
            raise CreatorsError("not_found")
        now = timezone.now()
        if old is not None:
            old.ended_at = now
            old.end_reason = "admin_rebind" if creator is not None else "admin_unbind"
            old.save(update_fields=["ended_at", "end_reason"])
        referral = None
        if creator is not None:
            # Новая привязка начинается в тот же миг, когда кончилась старая:
            # между ними нет зазора, в который могла бы попасть оплата.
            result = _bind(u, creator, source="admin", actor=actor, force=True, at=now)
            if not result.ok:
                # Исключение откатывает и снятие старой привязки.
                raise CreatorsError(result.reason)
            referral = result.referral
        log_admin_action(
            actor, "referral.rebind", target=u,
            creator=creator if creator is not None else old.creator,
            before={"creator_id": old.creator_id if old is not None else None},
            # referral_id: сверка I8 находит запись по самой привязке, даже
            # когда слияние аккаунтов потом перенесёт её на другого пользователя.
            after=({"creator_id": creator.pk, "referral_id": referral.pk}
                   if referral is not None else {"creator_id": None}),
            reason=reason, request=request)
    return referral


def clear_suspect(referral_id, *, actor, reason: str, release_held: bool = False,
                  request=None) -> CreatorReferral:
    """Снять пометку «подозрительная»: реферал снова считается.

    release_held=True заодно отпускает комиссии, придержанные из-за пометки.
    """
    reason = str(reason or "").strip()
    if not reason:
        raise CreatorsError("reason_required")
    with transaction.atomic():
        referral = (CreatorReferral.objects.select_related("creator", "user")
                    .filter(pk=referral_id).first())
        if referral is None:
            raise CreatorsError("not_found")
        if not referral.suspect:
            raise CreatorsError("bad_state")
        before = {"suspect": True, "reasons": list((referral.flags or {}).get("reasons") or [])}
        new_flags = dict(referral.flags or {})
        new_flags["cleared_by"] = actor.pk
        # Условный UPDATE вместо блокировки строки: из двух одновременных
        # нажатий пройдёт одно, а порядок блокировок User -> Creator не задет.
        updated = (CreatorReferral.objects.filter(pk=referral.pk, suspect=True)
                   .update(suspect=False, flags=new_flags))
        if updated != 1:
            raise CreatorsError("bad_state")
        referral.suspect = False
        referral.flags = new_flags

        released = 0
        if release_held:
            from creators.commission import release as release_commission

            held = list(CreatorCommission.objects
                        .filter(referral_id=referral.pk, status=CreatorCommission.Status.HELD,
                                reason="referral_suspect")
                        .order_by("pk").values_list("pk", flat=True))
            for commission_pk in held:
                release_commission(commission_pk, actor=actor, reason=reason, request=request)
                released += 1

        log_admin_action(actor, "referral.clear_suspect", target=referral,
                         creator=referral.creator, before=before,
                         after={"suspect": False, "released": released},
                         reason=reason, request=request)
        if referral.ended_at is None:
            _announce(referral.creator, referral.user)
    return referral


def invited_by(user) -> "dict | None":
    """Кто пригласил пользователя (его действующая привязка). Никогда не бросает."""
    try:
        if flags.is_off() or user is None or not getattr(user, "pk", None):
            return None
        referral = CreatorReferral.objects.active_for(user.pk)
        if referral is None:
            return None
        return {"invited_by": referral.creator.display_name, "code": referral.code_used,
                "bound_at": referral.bound_at}
    except Exception:  # noqa: BLE001
        logger.exception("creators.attribution: invited_by")
        return None


# ------------------------------------------------------ слияние аккаунтов ---

def check_merge(stub, target) -> None:
    """Можно ли влить заглушку в аккаунт сайта.

    Два креатора в одном человеке — два баланса, два набора кодов и два адреса
    выплат: это решает поддержка вручную, а не слияние.
    """
    owners = set(Creator.objects.filter(user_id__in=[stub.pk, target.pk])
                 .values_list("user_id", flat=True))
    if stub.pk in owners and target.pk in owners:
        raise CreatorsError("creator_conflict")


def _may_inherit_referral(target, now) -> bool:
    """Мог бы аккаунт сайта сам ввести код креатора сегодня.

    Без этой проверки давно зарегистрированный или уже платящий пользователь
    становился бы пожизненным рефералом креатора, просто открыв бота по
    ссылке start=ref_CODE и привязав Telegram.
    """
    if CreatorReferral.objects.filter(user_id=target.pk, ended_at__isnull=True).exists():
        return False
    if target.referred_by_id or target.is_staff or target.is_superuser:
        return False
    if target.first_paid_at is not None or target.is_paid:
        return False
    return now - target.date_joined <= timedelta(hours=flags.BIND_WINDOW_HOURS)


def on_merge(stub, target) -> dict:
    """Перенести данные программы из заглушки в аккаунт сайта.

    Зовётся из botapi.linking.merge_into: обе строки User уже заблокированы,
    поэтому блокировка креаторов здесь идёт в порядке User -> Creator.
    """
    now = timezone.now()
    stub_creator = Creator.objects.filter(user_id=stub.pk).first()
    target_creator = Creator.objects.filter(user_id=target.pk).first()
    if stub_creator is not None and target_creator is not None:
        raise CreatorsError("creator_conflict")
    # Креатор, которым аккаунт сайта владеет после слияния.
    own = target_creator or stub_creator

    stub_referral = CreatorReferral.objects.active_for(stub.pk)
    target_referral = CreatorReferral.objects.active_for(target.pk)
    is_self = bool(own is not None and (
        (stub_referral is not None and stub_referral.creator_id == own.pk)
        or (target_referral is not None and target_referral.creator_id == own.pk)))

    # Все нужные блокировки креаторов — сразу и по возрастанию pk, ДО правки
    # строк комиссий: иначе слияние и действие администратора над той же
    # комиссией (Creator -> комиссия) могли бы запереть друг друга.
    buyer_rows = CreatorCommission.objects.filter(Q(buyer_id=stub.pk) | Q(buyer_pk=stub.pk))
    lock_ids = set(buyer_rows.values_list("creator_id", flat=True))
    if stub_creator is not None:
        lock_ids.add(stub_creator.pk)
    if is_self:
        lock_ids.add(own.pk)
    for creator_pk in sorted(lock_ids):
        Creator.objects.locked(creator_pk)

    result = {"creator_moved": False, "creator_referral": "none", "applications": 0}

    if stub_creator is not None:
        # Коды, рефералы, комиссии и выводы едут следом — они ссылаются на креатора.
        Creator.objects.filter(pk=stub_creator.pk).update(user=target, updated_at=now)
        result["creator_moved"] = True

    new = CreatorApplication.Status.NEW
    if CreatorApplication.objects.filter(user_id=target.pk, status=new).exists():
        # Двух заявок на рассмотрении у одного человека быть не может.
        CreatorApplication.objects.filter(user_id=stub.pk, status=new).update(
            status=CreatorApplication.Status.REJECTED, reject_reason="merge", decided_at=now)
    # Иначе открытая заявка осталась бы на погашенном аккаунте, и её одобрение
    # создало бы креатора, в которого никто не может войти.
    result["applications"] = (CreatorApplication.objects.filter(user_id=stub.pk)
                              .update(user=target))

    # Платежи заглушки переезжают в аккаунт сайта — покупатель в комиссиях тоже.
    buyer_rows.update(buyer=target, buyer_pk=target.pk, updated_at=now)

    def end(referral) -> None:
        CreatorReferral.objects.filter(pk=referral.pk).update(ended_at=now,
                                                              end_reason="merge_self")

    if stub_referral is not None:
        if own is not None and stub_referral.creator_id == own.pk:
            end(stub_referral)
            result["creator_referral"] = "self"
        elif _may_inherit_referral(target, now):
            CreatorReferral.objects.filter(pk=stub_referral.pk).update(user=target)
            result["creator_referral"] = "moved"
        else:
            CreatorReferral.objects.filter(pk=stub_referral.pk).update(
                ended_at=now, end_reason="merge_dropped")
            result["creator_referral"] = "dropped"

    # Аккаунт сайта был рефералом креатора, которым теперь владеет сам.
    if (own is not None and target_referral is not None
            and target_referral.creator_id == own.pk):
        end(target_referral)
        if result["creator_referral"] == "none":
            result["creator_referral"] = "self"

    if is_self:
        # Комиссия с собственных покупок: придерживаем, решит администратор.
        # Уже придержанные строки тоже получают причину merge_self: иначе снятие
        # пометки «подозрительная» с погашенной привязки отпустило бы креатору
        # комиссию с его же покупки.
        CreatorCommission.objects.filter(
            creator_id=own.pk, buyer_pk=target.pk,
            status__in=(CreatorCommission.Status.ACCRUED, CreatorCommission.Status.HELD),
        ).update(status=CreatorCommission.Status.HELD, reason="merge_self", updated_at=now)
    return result
