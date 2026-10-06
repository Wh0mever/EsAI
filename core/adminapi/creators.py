"""Раздел «Creators» панели /admin-new: заявки, креаторы, публикации, рефералы,
комиссии, выплаты, Creator Credits, уровни, журнал, настройки.

Отдельный модуль, как blocks.py: тема большая и к остальной панели не относится.

Правил программы здесь нет. Каждая кнопка зовёт сервис из приложения creators
(program, publications, attribution, commission, withdrawals, credits, codes),
и запись в журнал действий (audit.AdminActionLog) делает сам сервис — в той же
транзакции, что и действие. Исключение одно: настройки программы
(режим, холд, приём заявок на вывод) пишутся и журналируются здесь.

Кто что может (решение 10): проверять заявки и публикации — любой сотрудник;
деньги и структура (выплаты, TXID, уровень, код, перепривязка, Creator
Credits, блокировка, отметка возврата, пороги уровней) — только главный
администратор (SuperuserAPIView).
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db.models import Count, Q, Sum
from rest_framework.response import Response

from audit.models import AdminActionLog
from audit.services import log_admin_action
from creators import attribution, balance, codes, credits, flags, program, publications
from creators import commission as commissions
from creators import serializers as S
from creators import stats, withdrawals
from creators.errors import CreatorsError
from creators.models import (
    Creator,
    CreatorApplication,
    CreatorCode,
    CreatorCommission,
    CreatorLevel,
    CreatorPublication,
    CreatorReferral,
    CreatorWithdrawal,
)
from creators.views import exception_handler
from payments.models import Payment
from plans.models import TokenTransaction

from .permissions import IsSuperuser
from .runtime import set_runtime
from .serializers import PaymentAdminSerializer
from .views import PAGE_SIZE, StaffAPIView, _paginate

User = get_user_model()

# Сколько последних строк каждого блока отдаёт профиль креатора.
PROFILE_ROWS = 50
PROFILE_LOG_ROWS = 20
PROFILE_CREDITS_ROWS = 100


# ------------------------------------------------------------------- основа

class CreatorsStaffView(StaffAPIView):
    """Любой сотрудник. Ошибки сервисов — телом {code, message, detail}."""

    def get_exception_handler(self):
        return exception_handler


class SuperuserAPIView(CreatorsStaffView):
    """Деньги и структура программы — только главный администратор."""

    permission_classes = [IsSuperuser]

    def permission_denied(self, request, message=None, code=None):
        user = getattr(request, "user", None)
        if code == "superuser_required" and user is not None and user.is_authenticated:
            # Сотруднику отвечаем кодом: панель прячет кнопку или объясняет, почему нельзя.
            raise CreatorsError("superuser_required")
        super().permission_denied(request, message=message, code=code)


def _data(request) -> dict:
    data = getattr(request, "data", None)
    return data if hasattr(data, "get") else {}


def _flag(value) -> bool:
    """Булев параметр. Строка "false" из формы не должна стать True."""
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def _int(value):
    """Целое из тела или строки запроса; None — не число."""
    if value is None or isinstance(value, (bool, float)):
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _by_id(qs, request, param: str, field: str):
    """Фильтр ?param=<id>. Нечисловое значение — пустой список, а не «все строки»."""
    raw = request.query_params.get(param)
    if raw in (None, ""):
        return qs
    value = _int(raw)
    return qs.none() if value is None else qs.filter(**{field: value})


def _page_of(items: list, request):
    """Страница готового списка (когда отбор сделан в Python, а не в базе)."""
    try:
        page = max(1, int(request.query_params.get("page", 1)))
    except (TypeError, ValueError):
        page = 1
    start = (page - 1) * PAGE_SIZE
    return len(items), items[start:start + PAGE_SIZE]


def _creator(pk) -> Creator:
    creator = (Creator.objects.select_related("level", "user", "application")
               .filter(pk=pk).first())
    if creator is None:
        raise CreatorsError("not_found")
    return creator


# ----------------------------------------------------------- строки ответов

def _creator_row(creator, have: dict, progress: dict, earned, code, granted) -> dict:
    """Строка списка креаторов — столбцы ТЗ п.30."""
    user = creator.user
    return {
        "id": creator.pk,
        "user_id": creator.user_id,
        "email": user.email,
        "username": user.username,
        "display_name": creator.display_name,
        "telegram": creator.application.telegram if creator.application_id else "",
        "level": {"key": creator.level.key, "title": creator.level.title},
        "percent": S.pct(creator.level.percent),
        "status": creator.status,
        "code": code or None,
        "clicks": have["clicks"],
        "registrations": have["registrations"],
        "paying": have["paying"],
        "sales_usdt": S.usdt2(have["sales_usdt"]),
        "earned_usdt": S.usdt2(earned),
        "credits_granted": int(granted or 0),
        "conditions_met": bool(progress["conditions_met"]),
        "joined_at": creator.created_at,
    }


def _creator_rows(creators, *, progress: dict | None = None) -> list[dict]:
    """Строки списка. Число запросов от числа креаторов не зависит."""
    creators = list(creators)
    if not creators:
        return []
    ids = [creator.pk for creator in creators]
    have = stats.counters_bulk(ids)
    if progress is None:
        progress = stats.progress_bulk(creators)
    earned = balance.earned_bulk(ids)
    primary = dict(CreatorCode.objects.filter(creator_id__in=ids, is_primary=True)
                   .values_list("creator_id", "code"))
    granted = {row["user_id"]: row["total"] for row in (
        TokenTransaction.objects
        .filter(user_id__in=[creator.user_id for creator in creators],
                reason=credits.REASON, delta__gt=0)
        .values("user_id").annotate(total=Sum("delta")))}
    return [_creator_row(creator, have[creator.pk], progress[creator.pk], earned[creator.pk],
                         primary.get(creator.pk), granted.get(creator.user_id))
            for creator in creators]


def _application(pk) -> CreatorApplication:
    return CreatorApplication.objects.select_related("user", "decided_by").get(pk=pk)


def _publications():
    return CreatorPublication.objects.select_related("creator", "decided_by")


def _referrals():
    return CreatorReferral.objects.select_related("user", "creator", "bound_by")


def _referral_rows(referrals) -> list[dict]:
    referrals = list(referrals)
    totals = S.referral_totals([referral.pk for referral in referrals])
    return [S.referral_admin_row(referral, totals[referral.pk]) for referral in referrals]


def _commissions():
    return CreatorCommission.objects.select_related("creator", "buyer")


def _withdrawals():
    return CreatorWithdrawal.objects.select_related("creator", "creator__user",
                                                    "approved_by", "paid_by")


def _withdrawal_rows(rows) -> list[dict]:
    """Строки выплат с балансом креатора; баланс считается один раз на креатора."""
    seen: dict = {}
    out = []
    for row in rows:
        if row.creator_id not in seen:
            seen[row.creator_id] = balance.summary(row.creator_id)
        money = seen[row.creator_id]
        out.append(S.withdrawal_admin_row(row, balance_json=balance.as_json(money),
                                          covered=money.available_raw >= 0))
    return out


def _withdrawal_row(pk) -> dict:
    return _withdrawal_rows([_withdrawals().get(pk=pk)])[0]


def _level_row(level, creators_count: int) -> dict:
    row = S.level_row(level)
    row["creators"] = int(creators_count or 0)
    return row


# ------------------------------------------------------------------- заявки

class ApplicationsListView(CreatorsStaffView):
    """GET /creators/applications/?status=&q= — заявки на участие (ТЗ п.7)."""

    def get(self, request):
        qs = (CreatorApplication.objects.select_related("user", "decided_by")
              .order_by("-created_at", "-id"))
        wanted = request.query_params.get("status")
        if wanted:
            qs = qs.filter(status=wanted)
        q = (request.query_params.get("q") or "").strip()
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(telegram__icontains=q)
                           | Q(user__email__icontains=q))
        count, page = _paginate(qs, request)
        return Response({"count": count,
                         "results": [S.application_row(a, admin=True) for a in page]})


class ApplicationApproveView(CreatorsStaffView):
    """POST {level} — одобрить. Уровень обязателен: по умолчанию его нет (ТЗ п.8).

    Уровень выше базового назначает только главный администратор — это
    проверяет сервис.
    """

    def post(self, request, pk):
        creator = program.approve_application(pk, actor=request.user,
                                              level_key=_data(request).get("level"),
                                              request=request)
        return Response({"application": S.application_row(_application(pk), admin=True),
                         "creator": _creator_rows([_creator(creator.pk)])[0]})


class ApplicationRejectView(CreatorsStaffView):
    """POST {reason, block} — отклонить; block=true (запрет подавать снова) — только главный."""

    def post(self, request, pk):
        data = _data(request)
        program.reject_application(pk, actor=request.user, reason=data.get("reason") or "",
                                   block=_flag(data.get("block")), request=request)
        return Response(S.application_row(_application(pk), admin=True))


class ApplicationUnblockView(SuperuserAPIView):
    """POST {reason} — снять запрет на подачу заявки (blocked -> rejected)."""

    def post(self, request, pk):
        program.unblock_application(pk, actor=request.user,
                                    reason=_data(request).get("reason"), request=request)
        return Response(S.application_row(_application(pk), admin=True))


# ----------------------------------------------------------------- креаторы

class CreatorsListView(CreatorsStaffView):
    """GET /creators/?status=&level=&q=&ready=1 — все креаторы (ТЗ п.30).

    ready=1 — у кого выполнены условия следующего уровня: подсказка, кого
    пора повысить. Само повышение — только вручную.
    """

    def get(self, request):
        params = request.query_params
        qs = (Creator.objects.select_related("level", "user", "application")
              .order_by("-created_at", "-id"))
        if params.get("status"):
            qs = qs.filter(status=params["status"])
        if params.get("level"):
            qs = qs.filter(level__key=params["level"])
        q = (params.get("q") or "").strip()
        if q:
            by_code = CreatorCode.objects.filter(code__icontains=q).values("creator_id")
            qs = qs.filter(Q(display_name__icontains=q) | Q(user__email__icontains=q)
                           | Q(user__username__icontains=q) | Q(pk__in=by_code))

        if _flag(params.get("ready")):
            # Условия считаются из счётчиков, а не из колонки: отбор по всему
            # найденному списку, страница — потом.
            everyone = list(qs)
            progress = stats.progress_bulk(everyone)
            ready = [creator for creator in everyone if progress[creator.pk]["conditions_met"]]
            count, page = _page_of(ready, request)
            return Response({"count": count, "results": _creator_rows(page, progress=progress)})

        count, page = _paginate(qs, request)
        return Response({"count": count, "results": _creator_rows(page)})


class CreatorDetailView(CreatorsStaffView):
    """GET /creators/<id>/ — профиль креатора (ТЗ п.31)."""

    def get(self, request, pk):
        creator = _creator(pk)
        user = creator.user
        have = stats.counters(creator)
        progress = stats.progress(creator, counters=have)
        money = balance.summary(creator)
        granted = credits.granted_total(user)
        remaining = credits.remaining(user)

        row = _creator_row(creator, have, progress, money.earned,
                           codes.primary_code(creator), granted)
        row.update({
            "lang": creator.lang,
            "blocked_at": creator.blocked_at,
            "blocked_reason": creator.blocked_reason,
            "payout_address": creator.payout_address,
            "payout_address_changed_at": creator.payout_address_changed_at,
        })

        application = None
        if creator.application_id:
            application = S.application_row(_application(creator.application_id), admin=True)

        counters = dict(have)
        counters["sales_usdt"] = S.usdt2(counters["sales_usdt"])
        money_json = balance.as_json(money)
        covered = money.available_raw >= 0
        by_status = dict(CreatorCommission.objects
                         .filter(creator_id=creator.pk, status__in=("held", "reversed"))
                         .values_list("status").annotate(n=Count("id")))

        return Response({
            "creator": row,
            "application": application,
            "codes": [{"code": code.code, "is_primary": code.is_primary,
                       "is_active": code.is_active, "created_at": code.created_at}
                      for code in CreatorCode.objects.filter(creator_id=creator.pk)
                      .order_by("-is_primary", "created_at", "id")],
            "counters": counters,
            "money": money_json,
            "progress": progress,
            "publications": [S.publication_row(p, admin=True) for p in
                             _publications().filter(creator_id=creator.pk)
                             .order_by("-created_at", "-id")[:PROFILE_ROWS]],
            "referrals": _referral_rows(_referrals().filter(creator_id=creator.pk)
                                        .order_by("-bound_at", "-id")[:PROFILE_ROWS]),
            "credits": {
                "granted": granted,
                "remaining": remaining,
                "spent": max(0, granted - remaining),
                "wallet_balance": int(user.token_balance or 0),
                # Выдачи и расходы вместе (ТЗ п.31: «баланс + история начислений/расходов»).
                "history": credits.ledger(user, limit=PROFILE_CREDITS_ROWS, for_admin=True),
            },
            "withdrawals": [S.withdrawal_admin_row(w, balance_json=money_json, covered=covered)
                            for w in _withdrawals().filter(creator_id=creator.pk)
                            .order_by("-created_at", "-id")[:PROFILE_ROWS]],
            "risk": {
                "suspect_referrals": have["suspect_referrals"],
                "held_commissions": int(by_status.get("held") or 0),
                "reversed_commissions": int(by_status.get("reversed") or 0),
                "debt": S.usdt2(money.debt),
            },
            "log": [S.log_row(entry) for entry in
                    AdminActionLog.objects.filter(creator_id=creator.pk)
                    .select_related("actor")[:PROFILE_LOG_ROWS]],
        })


class CreatorLevelView(SuperuserAPIView):
    """POST {level, reason} — сменить уровень (вверх или вниз). Только вручную."""

    def post(self, request, pk):
        data = _data(request)
        program.set_level(pk, data.get("level"), actor=request.user,
                          reason=data.get("reason") or "", request=request)
        return Response(_creator_rows([_creator(pk)])[0])


class CreatorBlockView(SuperuserAPIView):
    """POST {reason} — заблокировать. Заявка на вывод в работе закрывается тут же."""

    def post(self, request, pk):
        program.block(pk, actor=request.user, reason=_data(request).get("reason"),
                      request=request)
        return Response(_creator_rows([_creator(pk)])[0])


class CreatorUnblockView(SuperuserAPIView):
    def post(self, request, pk):
        program.unblock(pk, actor=request.user, reason=_data(request).get("reason") or "",
                        request=request)
        return Response(_creator_rows([_creator(pk)])[0])


class CreatorCodeView(SuperuserAPIView):
    """POST {code, reason} — заменить промокод. Старый остаётся рабочим псевдонимом."""

    def post(self, request, pk):
        data = _data(request)
        creator = _creator(pk)
        row = codes.change_code(creator, data.get("code"), actor=request.user,
                                reason=data.get("reason"), request=request)
        aliases = list(CreatorCode.objects.filter(creator_id=creator.pk, is_primary=False)
                       .order_by("created_at", "id").values_list("code", flat=True))
        return Response({"code": row.code, "link": codes.link_for(row.code), "aliases": aliases})


class CreatorCreditsGrantView(SuperuserAPIView):
    """POST {amount, category, note} — выдать Creator Credits (ТЗ п.20–21). Только вручную."""

    def post(self, request, pk):
        data = _data(request)
        creator = _creator(pk)
        tx = credits.grant(creator, data.get("amount"), data.get("category"),
                           actor=request.user, note=data.get("note") or "", request=request)
        user = creator.user
        # Строка истории в том же виде, что и во вкладке Creator Credits.
        recent = credits.history(user, limit=5, for_admin=True)
        wallet = User.objects.filter(pk=user.pk).values_list("token_balance", flat=True).first()
        return Response({
            "granted": credits.granted_total(user),
            "remaining": credits.remaining(user),
            "balance": int(wallet or 0),
            "transaction": next((row for row in recent if row["id"] == tx.pk), None),
        })


# --------------------------------------------------------------- публикации

class PublicationsListView(CreatorsStaffView):
    """GET /creators/publications/?status=&creator= — публикации на проверку (ТЗ п.17)."""

    def get(self, request):
        qs = _publications().order_by("-created_at", "-id")
        wanted = request.query_params.get("status")
        if wanted:
            qs = qs.filter(status=wanted)
        qs = _by_id(qs, request, "creator", "creator_id")
        count, page = _paginate(qs, request)
        return Response({"count": count,
                         "results": [S.publication_row(p, admin=True) for p in page]})


class PublicationApproveView(CreatorsStaffView):
    def post(self, request, pk):
        publications.approve(pk, actor=request.user, request=request)
        return Response(S.publication_row(_publications().get(pk=pk), admin=True))


class PublicationRejectView(CreatorsStaffView):
    def post(self, request, pk):
        publications.reject(pk, actor=request.user, reason=_data(request).get("reason") or "",
                            request=request)
        return Response(S.publication_row(_publications().get(pk=pk), admin=True))


# ----------------------------------------------------------------- рефералы

class ReferralsListView(CreatorsStaffView):
    """GET /creators/referrals/?creator=&q=&suspect=1&active=1 — привязки пользователей."""

    def get(self, request):
        params = request.query_params
        qs = _referrals().order_by("-bound_at", "-id")
        qs = _by_id(qs, request, "creator", "creator_id")
        if _flag(params.get("suspect")):
            qs = qs.filter(suspect=True)
        if _flag(params.get("active")):
            qs = qs.filter(ended_at__isnull=True)
        q = (params.get("q") or "").strip()
        if q:
            cond = (Q(user__email__icontains=q) | Q(user__username__icontains=q)
                    | Q(code_used__icontains=q))
            if q.isdigit():
                cond |= Q(user_id=int(q))
            qs = qs.filter(cond)
        count, page = _paginate(qs, request)
        return Response({"count": count, "results": _referral_rows(page)})


class ReferralRebindView(SuperuserAPIView):
    """POST {user_id, creator_id|null, reason} — перепривязать пользователя вручную.

    creator_id=null снимает привязку. Меняется судьба только будущих оплат.
    """

    def post(self, request):
        data = _data(request)
        user_id = _int(data.get("user_id"))
        if user_id is None:
            raise CreatorsError("validation", fields={"user_id": "Укажите пользователя"})
        user = User.objects.filter(pk=user_id).first()
        if user is None:
            raise CreatorsError("not_found")
        creator = None
        raw = data.get("creator_id")
        if raw not in (None, ""):
            creator_id = _int(raw)
            if creator_id is None:
                raise CreatorsError("validation", fields={"creator_id": "Укажите креатора"})
            creator = Creator.objects.select_related("level", "user").filter(pk=creator_id).first()
            if creator is None:
                raise CreatorsError("not_found")
        referral = attribution.rebind(user, creator, actor=request.user,
                                      reason=data.get("reason"), request=request)
        row = _referral_rows([_referrals().get(pk=referral.pk)])[0] if referral else None
        return Response({"referral": row})


class ReferralClearSuspectView(SuperuserAPIView):
    """POST {reason, release_held} — снять пометку «подозрительная»."""

    def post(self, request, pk):
        data = _data(request)
        attribution.clear_suspect(pk, actor=request.user, reason=data.get("reason"),
                                  release_held=_flag(data.get("release_held")), request=request)
        return Response(_referral_rows([_referrals().get(pk=pk)])[0])


# ----------------------------------------------------------------- комиссии

class CommissionsListView(CreatorsStaffView):
    """GET /creators/commissions/?creator=&status=&provider= — все комиссии."""

    def get(self, request):
        params = request.query_params
        qs = _commissions().order_by("-created_at", "-id")
        qs = _by_id(qs, request, "creator", "creator_id")
        if params.get("status"):
            qs = qs.filter(status=params["status"])
        if params.get("provider"):
            qs = qs.filter(provider=params["provider"])
        count, page = _paginate(qs, request)
        return Response({"count": count, "results": [S.commission_admin_row(c) for c in page]})


class CommissionVoidView(SuperuserAPIView):
    def post(self, request, pk):
        commissions.void(pk, actor=request.user, reason=_data(request).get("reason"),
                         request=request)
        return Response(S.commission_admin_row(_commissions().get(pk=pk)))


class CommissionReleaseView(SuperuserAPIView):
    """POST {reason} — снять удержание: held -> accrued."""

    def post(self, request, pk):
        commissions.release(pk, actor=request.user, reason=_data(request).get("reason") or "",
                            request=request)
        return Response(S.commission_admin_row(_commissions().get(pk=pk)))


class CommissionRestoreView(SuperuserAPIView):
    """POST {reason, clear_admin_refund} — вернуть ошибочно отменённую комиссию."""

    def post(self, request, pk):
        data = _data(request)
        commissions.restore(pk, actor=request.user, reason=data.get("reason"),
                            clear_admin_refund=_flag(data.get("clear_admin_refund")),
                            request=request)
        return Response(S.commission_admin_row(_commissions().get(pk=pk)))


# ------------------------------------------------------------------ выплаты

class WithdrawalsListView(CreatorsStaffView):
    """GET /creators/withdrawals/?status=&creator= — заявки на вывод (ТЗ п.26).

    В каждой строке баланс креатора и covered: false — после заявки пришёл
    возврат, платить по ней уже нечем.
    """

    def get(self, request):
        qs = _withdrawals().order_by("-created_at", "-id")
        wanted = request.query_params.get("status")
        if wanted:
            qs = qs.filter(status=wanted)
        qs = _by_id(qs, request, "creator", "creator_id")
        count, page = _paginate(qs, request)
        return Response({"count": count, "results": _withdrawal_rows(page)})


class WithdrawalApproveView(SuperuserAPIView):
    def post(self, request, pk):
        withdrawals.approve(pk, actor=request.user, request=request)
        return Response(_withdrawal_row(pk))


class WithdrawalRejectView(SuperuserAPIView):
    def post(self, request, pk):
        withdrawals.reject(pk, actor=request.user, reason=_data(request).get("reason"),
                           request=request)
        return Response(_withdrawal_row(pk))


class WithdrawalMarkPaidView(SuperuserAPIView):
    """POST {txid, force, reason} — USDT отправлены вручную, вводим TXID (ТЗ п.26)."""

    def post(self, request, pk):
        data = _data(request)
        withdrawals.mark_paid(pk, actor=request.user, txid=data.get("txid"),
                              force=_flag(data.get("force")), reason=data.get("reason") or "",
                              request=request)
        return Response(_withdrawal_row(pk))


class WithdrawalTxidView(SuperuserAPIView):
    """POST {txid, reason} — исправить опечатку в TXID выплаченной заявки."""

    def post(self, request, pk):
        data = _data(request)
        withdrawals.fix_txid(pk, actor=request.user, txid=data.get("txid"),
                             reason=data.get("reason"), request=request)
        return Response(_withdrawal_row(pk))


class WithdrawalReopenView(SuperuserAPIView):
    """POST {reason} — перевод не прошёл в сети: paid -> approved."""

    def post(self, request, pk):
        withdrawals.reopen(pk, actor=request.user, reason=_data(request).get("reason"),
                           request=request)
        return Response(_withdrawal_row(pk))


# ----------------------------------------------------------- Creator Credits

class CreditsListView(CreatorsStaffView):
    """GET /creators/credits/?creator= — все выдачи Creator Credits, новые сверху."""

    def get(self, request):
        creator_id = None
        raw = request.query_params.get("creator")
        if raw not in (None, ""):
            creator_id = _int(raw)
            if creator_id is None:
                return Response({"count": 0, "results": []})
        try:
            page = max(1, int(request.query_params.get("page", 1)))
        except (TypeError, ValueError):
            page = 1
        count, rows = credits.history_all(creator_id=creator_id,
                                          offset=(page - 1) * PAGE_SIZE, limit=PAGE_SIZE)
        return Response({"count": count, "results": rows})


# ------------------------------------------------------------------- уровни

class LevelsListView(CreatorsStaffView):
    def get(self, request):
        levels = CreatorLevel.objects.annotate(creators_count=Count("creators")).order_by("sort")
        return Response({"results": [_level_row(level, level.creators_count)
                                     for level in levels]})


class LevelDetailView(SuperuserAPIView):
    """PATCH /creators/levels/<key>/ — название, процент, пороги уровня.

    Меняет только будущие начисления: в комиссиях процент записан слепком.
    """

    def patch(self, request, key):
        data = _data(request)
        # Не dict(data): у тела формы (QueryDict) значения — списки.
        changes = {name: data.get(name) for name in data}
        reason = changes.pop("reason", "") or ""
        level = program.edit_level(key, changes, actor=request.user, reason=reason,
                                   request=request)
        return Response(_level_row(level, Creator.objects.filter(level_id=level.pk).count()))


# ------------------------------------------------------------------- журнал

class LogListView(CreatorsStaffView):
    """GET /creators/log/?creator=&action=&actor= — журнал ручных действий (ТЗ п.35)."""

    def get(self, request):
        qs = AdminActionLog.objects.select_related("actor")
        qs = _by_id(qs, request, "creator", "creator_id")
        qs = _by_id(qs, request, "actor", "actor_id")
        action = request.query_params.get("action")
        if action:
            qs = qs.filter(action=action)
        count, page = _paginate(qs, request)
        return Response({"count": count, "results": [S.log_row(entry) for entry in page]})


# ---------------------------------------------------------------- настройки

def _settings_body() -> dict:
    return {"mode": flags.mode(), "payouts_enabled": flags.payouts_enabled(),
            "hold_days": flags.hold_days()}


class CreatorsSettingsView(SuperuserAPIView):
    """GET/PATCH /creators/settings/ — режим программы, приём выводов, срок холда.

    Значения живут в runtime-настройках (без выкладки). Каждое изменение — в
    журнале: режим открывает программу всем, холд двигает срок выплат.
    """

    def get(self, request):
        return Response(_settings_body())

    def patch(self, request):
        data = _data(request)
        errors: dict[str, str] = {}
        new: dict = {}

        if "mode" in data:
            mode = str(data["mode"] or "").strip().lower()
            if mode in flags.MODES:
                new["mode"] = mode
            else:
                errors["mode"] = "Режим: off, staff или on"

        if "payouts_enabled" in data:
            raw = data["payouts_enabled"]
            text = str(raw).strip().lower()
            if isinstance(raw, bool):
                new["payouts_enabled"] = raw
            elif text in ("1", "true", "yes", "on"):
                new["payouts_enabled"] = True
            elif text in ("0", "false", "no", "off"):
                new["payouts_enabled"] = False
            else:
                errors["payouts_enabled"] = "Укажите true или false"

        if "hold_days" in data:
            days = _int(data["hold_days"])
            if days is None or not 0 <= days <= flags.HOLD_DAYS_MAX:
                errors["hold_days"] = f"Целое число от 0 до {flags.HOLD_DAYS_MAX}"
            else:
                new["hold_days"] = days

        if not errors and not new:
            errors["settings"] = "Нечего менять"
        if errors:
            # Проверяем всё до первой записи: половина настроек не сохраняется.
            raise CreatorsError("validation", fields=errors)

        before = _settings_body()
        changed = {name: value for name, value in new.items() if before[name] != value}
        keys = {"mode": "creators_mode", "payouts_enabled": "creators_payouts_enabled",
                "hold_days": "creators_hold_days"}
        for name, value in changed.items():
            set_runtime(keys[name], value)
        if changed:
            log_admin_action(request.user, "settings.edit",
                             before={name: before[name] for name in changed},
                             after=changed, request=request)
        return Response(_settings_body())


# ------------------------------------------------------------------ платежи

class PaymentMarkRefundedView(SuperuserAPIView):
    """POST /payments/<id>/mark-refunded/ {kind, reason, clawback_credits}.

    Ручная отметка «платёж возвращён» или «мошенничество»: комиссия креатора
    отменяется, кредиты покупателя изымаются только по явной просьбе. Нужна,
    когда провайдер о возврате не сообщил.
    """

    def post(self, request, pk):
        data = _data(request)
        # Единый QR (GoPay): пока счёт открыт, его ещё можно оплатить — а платёж
        # сейчас отметят возвращённым. Сначала гасим счёт у GoPay, и только потом
        # берём блокировки: сетевой вызов под блокировкой строки недопустим.
        # Запрос, который отметка всё равно отклонит (нет причины, неизвестный
        # вид), чужой QR гасить не должен — отмену у GoPay назад не вернуть.
        if (str(data.get("kind") or "") in ("refund", "fraud")
                and str(data.get("reason") or "").strip()):
            self._close_gopay_invoice(pk)
        result = commissions.mark_payment_refunded(
            pk, kind=data.get("kind"), actor=request.user, reason=data.get("reason"),
            clawback_credits=_flag(data.get("clawback_credits")), request=request)
        payment = Payment.objects.get(pk=pk)
        return Response({"reversed": int(result.get("reversed") or 0),
                         "clawback_debited": int(result.get("clawback_debited") or 0),
                         "payment": PaymentAdminSerializer(payment).data})

    @staticmethod
    def _close_gopay_invoice(pk) -> None:
        """Отменить у GoPay ещё открытый QR этого платежа. Не бросает.

        Не вышло отменить (GoPay молчит или банк занят) — счёт помечается
        оставленным: покупателю он больше не показывается, а поздняя оплата по
        нему уже не зачислится, потому что платёж отмечен возвращённым.
        """
        import logging

        from django.db import transaction

        try:
            from payments.gopay import service as gopay_service
            from payments.models import GoPayInvoice

            # Точка сохранения: сбой здесь не должен отравить транзакцию запроса —
            # сама отметка от GoPay не зависит.
            with transaction.atomic():
                gp = gopay_service.invoice_of(Payment.objects.filter(pk=pk).first())
                if gp is not None and (gp.status in GoPayInvoice.OPEN_STATES
                                       or (gp.flags or {}).get("local_expiry")):
                    if gopay_service.cancel_invoice(gp, reason="admin_refund") in ("retry", "busy"):
                        gopay_service.mark_abandoned(gp, "admin_refund")
        except Exception:  # noqa: BLE001 — отметка возврата важнее отмены счёта
            logging.getLogger("payments.gopay").warning(
                "gopay: cancel before refund mark failed payment=%s", pk)
