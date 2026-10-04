"""REST API программы EsAI Creators: публичная страница и кабинет креатора.

Здесь нет ни одного правила программы и ни одной записи в базу мимо сервисов:
вьюха проверяет рубильник и права, зовёт сервис (attribution, codes, program,
publications, withdrawals, credits, stats, balance) и собирает ответ.

Каждый адрес сначала смотрит на рубильник (creators.flags): программа
выключена для этого человека — 404 disabled, как будто раздела нет. Ошибки
сервисов (CreatorsError) уходят единым телом {code, message, detail}.
"""
from __future__ import annotations

from django.db.models import Q
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle, ScopedRateThrottle
from rest_framework.views import APIView, exception_handler as drf_exception_handler, set_rollback
from rest_framework_simplejwt.authentication import JWTAuthentication

from users.views import OptionalJWTAuthentication

from . import attribution, balance, clicks, codes, credits, flags, program, publications
from . import serializers as S
from . import stats, withdrawals
from .errors import CreatorsError, error_body
from .models import (
    Creator,
    CreatorApplication,
    CreatorCommission,
    CreatorLevel,
    CreatorPublication,
    CreatorReferral,
    CreatorWithdrawal,
)
from .permissions import IsActiveCreator, IsCreator

PAGE_SIZE = 50
CREDITS_HISTORY_LIMIT = 100

SCOPE_CLICK = "creators_click"
SCOPE_APPLY = "creators_apply"
SCOPE_WRITE = "creators_write"

OPEN_WITHDRAWALS = ("review", "approved")


def exception_handler(exc, context):
    """Обработчик ошибок API программы (кабинет и админка).

    CreatorsError — отказ сервиса: тело {code, message, detail} и откат
    транзакции запроса (при ATOMIC_REQUESTS ответ с ошибкой сам по себе ничего
    не откатывает). Ошибкам самого DRF (401, 403, 429) добавляем code и
    message, чтобы фронтенд разбирал все отказы одинаково.
    """
    if isinstance(exc, CreatorsError):
        set_rollback()
        return Response(error_body(exc), status=exc.http)
    response = drf_exception_handler(exc, context)
    if response is None:
        return None
    data = response.data
    if isinstance(data, dict) and "detail" in data:
        detail = data["detail"]
        body = {"code": str(getattr(detail, "code", "") or "error"), "message": str(detail)}
        # Свой code у ответа уже может быть (просроченный токен: token_not_valid).
        body.update(data)
        body["detail"] = str(detail)
        response.data = body
    return response


def _paginate(qs, request, page_size=PAGE_SIZE):
    """Ручная пагинация: ?page=N, срез по page_size (как в админке)."""
    try:
        page = max(1, int(request.query_params.get("page", 1)))
    except (TypeError, ValueError):
        page = 1
    count = qs.count()
    start = (page - 1) * page_size
    if start >= count:
        # За последней страницей пусто. Без этой проверки огромный номер
        # страницы уходил в OFFSET, и база отвечала ошибкой (HTTP 500).
        return count, []
    return count, qs[start:start + page_size]


def _data(request) -> dict:
    """Тело запроса словарём: вместо объекта могли прислать список или строку."""
    data = getattr(request, "data", None)
    return data if hasattr(data, "get") else {}


def _user(request):
    user = getattr(request, "user", None)
    return user if user is not None and getattr(user, "is_authenticated", False) else None


class AcceptedOnlyThrottle(ScopedRateThrottle):
    """Лимит, в который идут только принятые запросы.

    Обычный ScopedRateThrottle записывает запрос до вьюхи: пять ошибок в форме
    заявки закрыли бы подачу на сутки. Здесь запрос только сверяется с
    лимитом, а в историю попадает после успеха — вьюха зовёт commit().
    """

    def throttle_success(self):
        return True

    def commit(self) -> None:
        if getattr(self, "key", None) is not None:
            super().throttle_success()


class CreatorsAPIView(APIView):
    """База вьюх программы: JWT, рубильник, троттлинг по методу, форма ошибок.

    scopes — {метод: scope}. Метод со своим scope считается только в нём
    (ScopedRateThrottle), остальные — общими лимитами проекта.
    """

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]
    scopes: dict = {}
    # True — адрес нужен приглашённым людям: в режиме staff они не сотрудники,
    # поэтому проверяется только «программа не выключена».
    open_to_invited = False
    # True — гостей дополнительно держит общий анонимный лимит по IP.
    keep_anon_throttle = False

    def get_exception_handler(self):
        return exception_handler

    def check_permissions(self, request):
        # Рубильник раньше прав: при выключенной программе раздела нет ни для кого.
        if self.open_to_invited:
            allowed = not flags.is_off()
        else:
            allowed = flags.enabled_for(request.user)
        if not allowed:
            raise CreatorsError("disabled")
        super().check_permissions(request)

    def get_throttles(self):
        scope = self.scopes.get(str(self.request.method or "").upper())
        if not scope:
            return super().get_throttles()
        self.throttle_scope = scope
        throttles = [ScopedRateThrottle()]
        if self.keep_anon_throttle:
            throttles.append(AnonRateThrottle())
        return throttles


# ---------------------------------------------------------------- публичное

class ProgramView(CreatorsAPIView):
    """GET /program/ — условия программы для публичной страницы /creators."""

    authentication_classes = [OptionalJWTAuthentication]
    permission_classes = [AllowAny]

    def get(self, request):
        user = _user(request)
        creator_status = application_status = None
        if user is not None:
            creator_status = (Creator.objects.filter(user_id=user.pk)
                              .values_list("status", flat=True).first())
            application_status = (CreatorApplication.objects.filter(user_id=user.pk)
                                  .order_by("-created_at", "-id")
                                  .values_list("status", flat=True).first())
        return Response({
            "mode": flags.mode(),
            "min_payout_usdt": S.usdt2(flags.MIN_PAYOUT_USDT),
            "hold_days": flags.hold_days(),
            "network": "TRC20",
            "levels": [S.level_row(level) for level in CreatorLevel.objects.order_by("sort")],
            "me": {
                "is_authenticated": user is not None,
                "is_creator": creator_status is not None,
                "creator_status": creator_status,
                "application_status": application_status,
            },
        })


class ClickView(CreatorsAPIView):
    """POST /click/ {code} — переход по ссылке ?ref=CODE.

    Ответ всегда {"ok": true}: по нему нельзя узнать, существует ли код.
    """

    authentication_classes = [OptionalJWTAuthentication]
    permission_classes = [AllowAny]
    open_to_invited = True
    scopes = {"POST": SCOPE_CLICK}
    keep_anon_throttle = True

    def post(self, request):
        clicks.record(_data(request).get("code"), request)
        return Response({"ok": True})


class InviteView(CreatorsAPIView):
    """GET /invite/ — по чьему приглашению пришёл сам пользователь.

    Только чтение: сайт и бот показывают «вы пришли по приглашению …», не
    активируя код повторно.
    """

    open_to_invited = True

    def get(self, request):
        info = attribution.invited_by(request.user) or {}
        return Response({
            "invited_by": info.get("invited_by") or None,
            "code": info.get("code") or None,
            "bound_at": info.get("bound_at"),
        })


# ------------------------------------------------------------------- заявка

class ApplicationView(CreatorsAPIView):
    """GET — последняя заявка пользователя; POST — подать заявку.

    Лимит creators_apply считает только принятые заявки; отклонённые отправки
    (ошибки в полях) держит общий лимит проекта.
    """

    _apply_throttle = None

    def get_throttles(self):
        throttles = super().get_throttles()
        if str(self.request.method or "").upper() == "POST":
            self.throttle_scope = SCOPE_APPLY
            self._apply_throttle = AcceptedOnlyThrottle()
            throttles.append(self._apply_throttle)
        return throttles

    def get(self, request):
        application = (CreatorApplication.objects.filter(user_id=request.user.pk)
                       .order_by("-created_at", "-id").first())
        return Response({
            "application": S.application_row(application) if application else None})

    def post(self, request):
        application = program.submit_application(request.user, _data(request), request=request)
        if self._apply_throttle is not None:
            self._apply_throttle.commit()
        return Response({"application": S.application_row(application)},
                        status=status.HTTP_201_CREATED)


# ------------------------------------------------------------------ кабинет

def _code_block(creator) -> dict:
    code = codes.primary_code(creator)
    if not code:
        return {"code": None, "link": None, "telegram_link": None}
    return {"code": code, "link": codes.link_for(code),
            "telegram_link": codes.telegram_link_for(code) or None}


class MeView(CreatorsAPIView):
    """GET — главный экран кабинета (ТЗ п.13–15, 37–38); PATCH — язык уведомлений."""

    permission_classes = [IsCreator]
    scopes = {"PATCH": SCOPE_WRITE}

    def get(self, request):
        creator = request.creator
        have = stats.counters(creator)
        state = stats.progress(creator, counters=have)
        # Счётчик подозрительных привязок — только для администратора.
        have.pop("suspect_referrals", None)
        have["sales_usdt"] = S.usdt2(have["sales_usdt"])
        state["awaiting_confirmation"] = state["conditions_met"]

        money_now = balance.summary(creator)
        open_withdrawal = (CreatorWithdrawal.objects
                           .filter(creator_id=creator.pk, status__in=OPEN_WITHDRAWALS).first())
        payouts = flags.payouts_enabled()
        money = balance.as_json(money_now)
        # Комиссии, придержанные из-за привязки на проверке, креатору не
        # показываются ни в списке, ни в рефералах — и в сумме «придержано» их
        # быть не должно. Администратор видит полную цифру в профиле креатора.
        hidden = balance._sum(
            CreatorCommission.objects.filter(creator_id=creator.pk,
                                             status=CreatorCommission.Status.HELD,
                                             reason="referral_suspect"), "amount_usdt")
        money["held"] = S.usdt2(max(money_now.held - hidden, 0))
        money.update({
            "min_payout": S.usdt2(flags.MIN_PAYOUT_USDT),
            "can_withdraw": bool(creator.status == Creator.Status.ACTIVE and payouts
                                 and money_now.available >= flags.MIN_PAYOUT_USDT
                                 and open_withdrawal is None),
            "payouts_enabled": payouts,
        })

        body = {
            "creator": {"id": creator.pk, "status": creator.status,
                        "display_name": creator.display_name,
                        "joined_at": creator.created_at, "lang": creator.lang},
            "level": S.level_brief(creator.level),
        }
        body.update(_code_block(creator))
        body.update({
            "counters": have,
            "money": money,
            "progress": state,
            "credits": {"granted": credits.granted_total(request.user),
                        "remaining": credits.remaining(request.user)},
            "payout_address": creator.payout_address,
            "payout_address_changed_at": creator.payout_address_changed_at,
            "open_withdrawal": (S.withdrawal_row(open_withdrawal)
                                if open_withdrawal else None),
        })
        return Response(body)

    def patch(self, request):
        # У пользователя нет поля языка: без этого уведомления навсегда остались
        # бы на языке, выбранном в заявке.
        creator = program.set_lang(request.creator, _data(request).get("lang"))
        return Response({"lang": creator.lang})


class CodeCheckView(CreatorsAPIView):
    """GET /code/check/?code= — свободен ли код, пока креатор его набирает."""

    permission_classes = [IsActiveCreator]

    def get(self, request):
        code = codes.normalize(request.query_params.get("code"))
        try:
            codes.validate_format(code)
            codes.check_available(code)
        except CreatorsError as exc:
            return Response({"code": code, "available": False, "reason": exc.code})
        return Response({"code": code, "available": True})


class MyCodeView(CreatorsAPIView):
    """POST /me/code/ {code} — создать свой промокод. Один раз; дальше — только админ."""

    permission_classes = [IsActiveCreator]
    scopes = {"POST": SCOPE_WRITE}

    def post(self, request):
        row = codes.create_code(request.creator, _data(request).get("code"))
        return Response({"code": row.code, "link": codes.link_for(row.code),
                         "telegram_link": codes.telegram_link_for(row.code) or None},
                        status=status.HTTP_201_CREATED)


class MyPublicationsView(CreatorsAPIView):
    permission_classes = [IsCreator]
    scopes = {"POST": SCOPE_WRITE}

    def get(self, request):
        qs = (CreatorPublication.objects.filter(creator_id=request.creator.pk)
              .order_by("-created_at", "-id"))
        wanted = request.query_params.get("status")
        if wanted:
            qs = qs.filter(status=wanted)
        count, page = _paginate(qs, request)
        return Response({"count": count, "results": [S.publication_row(p) for p in page]})

    def post(self, request):
        data = _data(request)
        publication = publications.submit(request.creator, data.get("network"),
                                          data.get("url"), data.get("description") or "")
        return Response(S.publication_row(publication), status=status.HTTP_201_CREATED)


class MyCreditsView(CreatorsAPIView):
    """GET /me/credits/ — Creator Credits: выдано, осталось, история (ТЗ п.22).

    ?full=1 — вместе с расходами (сколько из каждого списания пришлось на
    Creator Credits).
    """

    permission_classes = [IsCreator]

    def get(self, request):
        user = request.user
        granted = credits.granted_total(user)
        remaining = credits.remaining(user)
        if str(request.query_params.get("full") or "").lower() in ("1", "true", "yes"):
            rows = credits.ledger(user, limit=CREDITS_HISTORY_LIMIT)
        else:
            rows = credits.history(user, limit=CREDITS_HISTORY_LIMIT)
        results = [S.credit_row(row) for row in rows]
        return Response({"granted": granted, "remaining": remaining,
                         "spent": max(0, granted - remaining),
                         "count": len(results), "results": results})


class MyCommissionsView(CreatorsAPIView):
    """GET /me/commissions/ — комиссии креатора.

    Не показываем то, что выдало бы внутренние сигналы: строки, не ставшие
    комиссией (покупатель — сотрудник, тестовый платёж: void от хука оплаты), и
    комиссии, придержанные из-за привязки на проверке, — такой привязки нет и
    в списке рефералов. Комиссию, аннулированную администратором, креатор видит.
    """

    permission_classes = [IsCreator]

    def get(self, request):
        qs = (CreatorCommission.objects.filter(creator_id=request.creator.pk)
              .exclude(Q(status=CreatorCommission.Status.VOID) & ~Q(reason="admin_void"))
              .exclude(status=CreatorCommission.Status.HELD, reason="referral_suspect")
              .select_related("buyer").order_by("-created_at", "-id"))
        wanted = request.query_params.get("status")
        if wanted:
            qs = qs.filter(status=wanted)
        count, page = _paginate(qs, request)
        return Response({"count": count, "results": [S.commission_row(c) for c in page]})


class MyReferralsView(CreatorsAPIView):
    """GET /me/referrals/ — приглашённые люди. Ни id, ни почты — только маска.

    Те же правила, что у счётчика «Регистрации»: привязка на проверке
    (подозрительная) и отключённый аккаунт в список не попадают — иначе список
    расходился бы с цифрой на главном экране.
    """

    permission_classes = [IsCreator]

    def get(self, request):
        qs = (CreatorReferral.objects
              .filter(creator_id=request.creator.pk, ended_at__isnull=True,
                      suspect=False, user__is_active=True)
              .select_related("user").order_by("-bound_at", "-id"))
        count, page = _paginate(qs, request)
        rows = list(page)
        totals = S.referral_totals([row.pk for row in rows])
        return Response({"count": count,
                         "results": [S.referral_row(row, totals[row.pk]) for row in rows]})


class MyWithdrawalsView(CreatorsAPIView):
    """GET — история выводов (с TXID); POST {amount, address} — заявка на вывод."""

    permission_classes = [IsCreator]
    scopes = {"POST": SCOPE_WRITE}

    def get(self, request):
        qs = (CreatorWithdrawal.objects.filter(creator_id=request.creator.pk)
              .order_by("-created_at", "-id"))
        count, page = _paginate(qs, request)
        return Response({"count": count, "results": [S.withdrawal_row(w) for w in page]})

    def post(self, request):
        data = _data(request)
        withdrawal = withdrawals.request_withdrawal(
            request.creator, data.get("amount"), address=data.get("address"), request=request)
        return Response(S.withdrawal_row(withdrawal), status=status.HTTP_201_CREATED)


class PayoutAddressView(CreatorsAPIView):
    """PUT /me/payout-address/ {address} — адрес USDT TRC20 для выплат."""

    permission_classes = [IsActiveCreator]
    scopes = {"PUT": SCOPE_WRITE}

    def put(self, request):
        creator = withdrawals.set_payout_address(request.creator, _data(request).get("address"),
                                                 request=request)
        return Response({"payout_address": creator.payout_address,
                         "payout_address_changed_at": creator.payout_address_changed_at})

