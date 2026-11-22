"""REST API Creative Studio: /api/creative/ (SPEC_B §7).

Правила, ради которых вьюхи устроены именно так (как у видеостудии):
- клиент передаёт только uid своих загрузок и персонажей; все выборки — по
  user=request.user, чужой uid неотличим от несуществующего (404);
- цену считает только сервер и одной функцией: quote и run зовут
  pricing.price() — «цена на кнопке» = резерв = списание (иначе 409 price_changed);
- запуск идемпотентен по client_request_id, резерв — под замком строки
  пользователя (reserve.spend_gate), задача ставится после коммита;
- режим CREATIVE_MODE: off — 403 creative_disabled (кроме tools/), staff —
  только сотрудники; у инструмента свой рубильник (CreativeTool.enabled);
- у каждого вида запросов свой throttle scope;
- в ответах нет имени поставщика, его ссылок и себестоимости.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import re
import time
from functools import partial

from django.conf import settings
from django.db import IntegrityError, transaction
from rest_framework import status as http
from rest_framework.negotiation import DefaultContentNegotiation
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication

from ai.pricing import PriceUnavailable

from . import access, catalog, notify, pipeline, pricing, registry, reserve, uploads
from . import serializers as S
from .errors import CreativeError, exception_handler
from .models import KIND_CHARACTER, CreativeCharacter, CreativeJob, CreativeUpload, CreativeWebhookEvent

logger = logging.getLogger(__name__)

SCOPE_READ = "creative_read"
SCOPE_QUOTE = "creative_quote"
SCOPE_RUN = "creative_run"
SCOPE_UPLOAD = "creative_upload"
SCOPE_POLL = "creative_poll"
SCOPE_HOOK = "creative_hook"

PAGE_SIZE = 20
MAX_PAGE = 500
HOOK_MAX_BODY = 64 * 1024
HOOK_TOLERANCE_S = 300
LANGS = {"ru": "ru", "en": "en", "ky": "ky", "kg": "ky"}


class CreativeAPIView(APIView):
    """База вьюх раздела: JWT, режим, свой throttle scope на метод, форма ошибок."""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated, access.CreativeOpen]
    throttle_classes = [ScopedRateThrottle]
    scopes: dict = {}
    default_scope = SCOPE_READ

    @property
    def throttle_scope(self):
        method = str(getattr(getattr(self, "request", None), "method", "") or "GET").upper()
        return self.scopes.get(method, self.default_scope)

    def get_exception_handler(self):
        return exception_handler


def _body(request) -> dict:
    data = request.data
    if not isinstance(data, dict):
        raise CreativeError("bad_request", field="body")
    return data


def _lang(request, data: dict | None = None) -> str:
    raw = ""
    if data and isinstance(data.get("lang"), str):
        raw = data["lang"]
    raw = raw or str(request.query_params.get("lang") or "")
    raw = raw or str(request.headers.get("Accept-Language") or "")
    return LANGS.get(raw.strip().lower()[:2], "ru")


def _tool_for(data: dict) -> registry.Tool:
    tool = registry.get(data.get("tool"))
    if tool is None:
        raise CreativeError("tool_not_found")
    if not access.tool_enabled(tool.id):
        raise CreativeError("tool_disabled")
    return tool


def _params(request, tool: registry.Tool, data: dict) -> dict:
    raw = data.get("params")
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise CreativeError("bad_request", field="params")
    raw = dict(raw)
    if tool.field("language") is not None and not raw.get("language"):
        raw["language"] = _lang(request, data)
    return raw


def _validated(request, tool: registry.Tool, data: dict) -> registry.Validated:
    v = registry.validate(tool, _params(request, tool, data), user=request.user,
                          catalog_lookup=catalog.lookup)
    if v.errors:
        raise CreativeError("bad_params", errors=v.errors)
    return v


def _price(tool: registry.Tool, v: registry.Validated) -> pricing.Price:
    try:
        return pricing.price(tool, v.params, v.uploads)
    except PriceUnavailable:
        raise CreativeError("price_unavailable") from None


def _job_payload(job: CreativeJob, user) -> dict:
    job = CreativeJob.objects.get(pk=job.pk)
    return {"job": S.job_json(job), "balance": reserve.balance_snapshot(user)}


def _get_job(user, uid) -> CreativeJob:
    job = CreativeJob.objects.filter(user=user, uid=uid).first() if S.is_uid(uid) else None
    if job is None:
        raise CreativeError("job_not_found")
    return job


# ---------------------------------------------------------------- инструменты и каталоги

class ToolsView(CreativeAPIView):
    """GET tools/ — режим, доступность и цены «от …». Отвечает в любом режиме:
    фронт сам решает, показывать форму или «Скоро»."""

    permission_classes = [AllowAny]
    scopes = {"GET": SCOPE_READ}

    def get(self, request):
        user = request.user if getattr(request.user, "is_authenticated", False) else None
        mode = access.creative_mode()
        available = access.can_use(user, mode)
        rows = access.tool_rows()
        tools = []
        for tool in registry.TOOLS:
            enabled = access.tool_enabled(tool.id, rows)
            hint = pricing.hint_price(tool, rows=rows) if available else None
            tools.append({"id": tool.id, "enabled": enabled, "kind": tool.kind,
                          "face_consent": tool.face_consent,
                          "price_hint_credits": hint.credits if hint else None})
        payload = {"mode": mode, "available": available, "tools": tools}
        if user is not None:
            payload["balance"] = reserve.balance_snapshot(user)
        return Response(payload)


class CatalogView(CreativeAPIView):
    """GET catalog/<kind>/ — стили, пресеты, опции блогера: {id, name, preview} с нашими адресами."""

    scopes = {"GET": SCOPE_READ}

    def get(self, request, kind):
        if kind not in catalog.KINDS:
            raise CreativeError("catalog_not_found")
        data = catalog.public(kind)
        if data is None:
            raise CreativeError("catalog_unavailable")
        return Response(data)


# ---------------------------------------------------------------- загрузки

class UploadsView(CreativeAPIView):
    """POST uploads/ (multipart: file, kind=image|video) → {uid, kind, w, h, duration, preview}."""

    parser_classes = [MultiPartParser, FormParser]
    scopes = {"POST": SCOPE_UPLOAD}

    def post(self, request):
        uploads.precheck(request.META.get("CONTENT_LENGTH"))
        kind = str(request.data.get("kind") or "").strip().lower()
        if kind not in (CreativeUpload.KIND_IMAGE, CreativeUpload.KIND_VIDEO):
            raise CreativeError("bad_request", field="kind")
        from vstudio.assets import AssetError, single_upload

        try:
            fileobj = single_upload(request.FILES)
        except AssetError:
            raise CreativeError("bad_request", field="file") from None
        row = uploads.accept(request.user, fileobj, kind)
        return Response(uploads.upload_json(row), status=http.HTTP_201_CREATED)


# ---------------------------------------------------------------- цена и запуск

class QuoteView(CreativeAPIView):
    """POST quote/ {tool, params} → {credits, balance}. Себестоимость наружу не отдаём."""

    parser_classes = [JSONParser]
    scopes = {"POST": SCOPE_QUOTE}

    def post(self, request):
        data = _body(request)
        tool = _tool_for(data)
        v = _validated(request, tool, data)
        price = _price(tool, v)
        return Response({"credits": price.credits, "tool": tool.id,
                         "outputs": tool.expected_outputs(v.params), "eta_s": tool.eta_s,
                         "balance": reserve.balance_snapshot(request.user, price.credits)})


class RunView(CreativeAPIView):
    """POST run/ {tool, params, quoted_credits, client_request_id} → 201 {job, balance};
    200 при повторе того же client_request_id."""

    parser_classes = [JSONParser]
    scopes = {"POST": SCOPE_RUN}

    def post(self, request):
        user = request.user
        data = _body(request)
        cid = data.get("client_request_id")
        if not isinstance(cid, str) or not S.CLIENT_REQUEST_ID_RE.match(cid.strip()):
            raise CreativeError("bad_request", field="client_request_id")
        cid = cid.strip()
        existing = CreativeJob.objects.filter(user=user, client_request_id=cid).first()
        if existing is not None:
            return Response(_job_payload(existing, user), status=http.HTTP_200_OK)
        quoted = data.get("quoted_credits")
        if isinstance(quoted, bool) or not isinstance(quoted, (int, str)):
            raise CreativeError("bad_request", field="quoted_credits")
        try:
            quoted = int(quoted)
        except (TypeError, ValueError):
            raise CreativeError("bad_request", field="quoted_credits") from None

        tool = _tool_for(data)
        v = _validated(request, tool, data)
        price = _price(tool, v)
        if quoted != price.credits:
            raise CreativeError("price_changed", credits=price.credits)

        try:
            with reserve.spend_gate(user, price.credits, kind=tool.kind, client_request_id=cid):
                job = CreativeJob.objects.create(
                    user=user, tool_slug=tool.id, kind=tool.kind, params=v.params,
                    credits_quoted=quoted, credits_reserved=price.credits,
                    cost_usd=price.cost_usd, markup_pct_at_launch=price.markup_pct,
                    expected_outputs=tool.expected_outputs(v.params), client_request_id=cid,
                    stage="queued")
                if tool.kind == KIND_CHARACTER:
                    CreativeCharacter.objects.create(user=user, name=v.params.get("name", "")[:60],
                                                     job=job)
        except reserve.AlreadyStarted as started:
            return Response(_job_payload(started.job, user), status=http.HTTP_200_OK)
        except reserve.SpendRefused as refused:
            return Response(refused.payload, status=refused.status)
        except IntegrityError:
            existing = CreativeJob.objects.filter(user=user, client_request_id=cid).first()
            if existing is None:
                raise
            return Response(_job_payload(existing, user), status=http.HTTP_200_OK)

        transaction.on_commit(partial(pipeline.enqueue_start, job))
        logger.info("creative run job=%s tool=%s credits=%s", job.uid, tool.id, price.credits)
        return Response(_job_payload(job, user), status=http.HTTP_201_CREATED)


# ---------------------------------------------------------------- работы

class JobsView(CreativeAPIView):
    """GET jobs/?tool=&page= — «Мои работы» (новые сверху). Ставит creative:seen."""

    scopes = {"GET": SCOPE_POLL}

    def get(self, request):
        notify.mark_seen(request.user.pk)
        qs = CreativeJob.objects.filter(user=request.user)
        tool = request.query_params.get("tool")
        if tool:
            if registry.get(tool) is None:
                raise CreativeError("tool_not_found")
            qs = qs.filter(tool_slug=tool)
        try:
            page = max(1, min(MAX_PAGE, int(request.query_params.get("page") or 1)))
        except (TypeError, ValueError):
            raise CreativeError("bad_request", field="page") from None
        start = (page - 1) * PAGE_SIZE
        rows = list(qs.order_by("-created_at", "-pk")[start:start + PAGE_SIZE + 1])
        return Response({"items": [S.job_json(j) for j in rows[:PAGE_SIZE]], "page": page,
                         "has_more": len(rows) > PAGE_SIZE})


class JobDetailView(CreativeAPIView):
    scopes = {"GET": SCOPE_POLL}

    def get(self, request, uid):
        job = _get_job(request.user, uid)
        notify.mark_seen(request.user.pk)
        return Response(S.job_json(job))


class JobCancelView(CreativeAPIView):
    """POST jobs/<uid>/cancel/ — из нашей очереди или из очереди генерации; начатую — 409."""

    scopes = {"POST": SCOPE_RUN}

    def post(self, request, uid):
        job = _get_job(request.user, uid)
        if not pipeline.cancel(job.pk):
            raise CreativeError("already_submitted")
        return Response(_job_payload(job, request.user))


# ---------------------------------------------------------------- персонажи

class CharactersView(CreativeAPIView):
    scopes = {"GET": SCOPE_READ}

    def get(self, request):
        rows = (CreativeCharacter.objects.filter(user=request.user, deleted_at__isnull=True)
                .order_by("-created_at", "-pk")[:200])
        return Response({"items": [S.character_json(c) for c in rows]})


class CharacterHideView(CreativeAPIView):
    scopes = {"POST": SCOPE_RUN}

    def post(self, request, uid):
        from django.utils import timezone

        ch = (CreativeCharacter.objects.filter(user=request.user, uid=uid, deleted_at__isnull=True).first()
              if S.is_uid(uid) else None)
        if ch is None:
            raise CreativeError("character_not_found")
        CreativeCharacter.objects.filter(pk=ch.pk).update(deleted_at=timezone.now())
        return Response({"ok": True, "uid": ch.uid})


# ---------------------------------------------------------------- вебхук

class _IgnoreAccept(DefaultContentNegotiation):
    def select_renderer(self, request, renderers, format_suffix=None):
        return renderers[0], renderers[0].media_type


_SIG_RE = re.compile(r"^v1,[A-Za-z0-9+/=]{20,200}$")


def verify_signature(secret: str, headers, raw: bytes, *, now: float | None = None) -> bool:
    """Подпись Standard Webhooks: HMAC-SHA256(«id.timestamp.тело») ключом из whsec_…."""
    msg_id = str(headers.get("webhook-id") or "").strip()
    ts = str(headers.get("webhook-timestamp") or "").strip()
    sigs = str(headers.get("webhook-signature") or "").strip()
    if not (msg_id and ts and sigs) or len(msg_id) > 200:
        return False
    try:
        stamp = int(ts)
    except ValueError:
        return False
    if abs((now if now is not None else time.time()) - stamp) > HOOK_TOLERANCE_S:
        return False
    try:
        key = base64.b64decode(secret.removeprefix("whsec_"))
    except (ValueError, TypeError):
        return False
    expected = base64.b64encode(hmac.new(key, f"{msg_id}.{ts}.".encode() + raw, hashlib.sha256).digest())
    for part in sigs.split(" "):
        if _SIG_RE.match(part) and hmac.compare_digest(part[3:].encode("ascii"), expected):
            return True
    return False


class HookView(APIView):
    """POST hook/ — вебхук поставщика. Без HF_WEBHOOK_SECRET — 404 (основной путь — опрос).

    Телу деньги не доверяем: по событию задача просто опрашивается сейчас же
    (pipeline.poke) тем же кодом, что и по расписанию.
    """

    authentication_classes = []
    permission_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = SCOPE_HOOK
    content_negotiation_class = _IgnoreAccept

    def post(self, request, *args, **kwargs):
        secret = str(getattr(settings, "HF_WEBHOOK_SECRET", "") or "").strip()
        if not secret:
            return Response({"error_code": "not_found"}, status=http.HTTP_404_NOT_FOUND)
        raw = request.body or b""
        if len(raw) > HOOK_MAX_BODY:
            return Response({"error_code": "too_large"}, status=http.HTTP_400_BAD_REQUEST)
        if not verify_signature(secret, request.headers, raw):
            logger.warning("creative hook: подпись не принята")
            return Response({"error_code": "invalid_signature"}, status=http.HTTP_400_BAD_REQUEST)
        try:
            body = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return Response({"ok": True, "status": "ignored"})
        if not isinstance(body, dict):
            return Response({"ok": True, "status": "ignored"})
        request_id = str(body.get("request_id") or "")[:64]
        state = str(body.get("status") or "")[:16]
        msg_id = str(request.headers.get("webhook-id") or "")
        event_key = hashlib.sha256((msg_id or f"{request_id}|{state}").encode("utf-8")).hexdigest()
        try:
            with transaction.atomic():
                CreativeWebhookEvent.objects.create(
                    event_key=event_key, provider_request_id=request_id, status=state,
                    payload={"request_id": request_id, "status": state})
        except IntegrityError:
            return Response({"ok": True, "status": "duplicate"})
        if request_id:
            transaction.on_commit(partial(pipeline.poke, request_id))
            CreativeWebhookEvent.objects.filter(event_key=event_key).update(processed=True)
        return Response({"ok": True})


__all__ = ["ToolsView", "CatalogView", "UploadsView", "QuoteView", "RunView", "JobsView",
           "JobDetailView", "JobCancelView", "CharactersView", "CharacterHideView", "HookView",
           "verify_signature"]
