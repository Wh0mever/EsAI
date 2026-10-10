"""REST API видеостудии: /api/vstudio/ (спецификация §8).

Главные правила, ради которых вьюхи устроены именно так:
- клиент передаёт только uid, никаких URL; все выборки — по user=request.user,
  чужой uid неотличим от несуществующего (404 с тем же кодом);
- цену считает только сервер и одним путём: quote и запуск зовут одну и ту же
  prepare() (компилятор + pricing), поэтому «цена на кнопке» = резерв = списание;
- запуск идемпотентен по client_request_id, резерв — под замком строки
  пользователя (reserve.spend_gate), задача ставится только после коммита
  (transaction.on_commit) — воркер не увидит дубль, которого ещё нет в базе;
- флаг VSTUDIO_MODE: off — 403 vstudio_disabled везде, кроме models/ и
  showcase/ (они отвечают пустыми списками); staff — генерировать может
  только is_staff;
- у каждого вида запросов свой throttle scope, общий лимит 120/мин не тратим.

Тела отказов — всегда {"error", "error_code", …} (vstudio.errors).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import partial

from django.conf import settings
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.db.models import Count, IntegerField, OuterRef, Prefetch, Q, Subquery
from django.db.models.functions import Coalesce
from django.utils import timezone
from rest_framework import status as http
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication

from ai.models import GPTModels
from plans.tiers import can_use_model, user_tier

from . import caps as caps_mod
from . import compiler, notify, pipeline, pricing, reserve, showcase
from . import prompt_doc as pd
from . import serializers as S
from .assets import AssetError, from_take_last_frame, ingest_upload, single_upload
from .errors import StudioError, exception_handler
from .models import TAKE_OPEN, Asset, Project, Shot, ShotInput, Take

logger = logging.getLogger(__name__)

MODES = ("off", "staff", "on")
MODELS_CACHE_S = 600          # §8.2: список моделей — кэш 10 минут на тариф
MODELS_CACHE_DEGRADED_S = 60  # каталог не ответил — не держим урезанный список 10 минут
MODELS_CACHE_KEY = "vstudio:models:v1:{tier}"
MAX_POLL_IDS = 30

SCOPE_READ = "vstudio_read"
SCOPE_WRITE = "vstudio_write"
SCOPE_QUOTE = "vstudio_quote"
SCOPE_RUN = "vstudio_run"
SCOPE_POLL = "vstudio_poll"
SCOPE_UPLOAD = "vstudio_upload"


# ---------------------------------------------------------------- флаг и доступ

def studio_mode() -> str:
    """VSTUDIO_MODE: off | staff | on.

    Сверху — необязательная правка из админки (AppSetting «vstudio_mode»),
    как у криптооплаты: выключить студию можно без выкладки. Чтение — в
    savepoint: сбой запроса к настройкам не должен ломать транзакцию запроса.
    """
    mode = str(getattr(settings, "VSTUDIO_MODE", "staff") or "staff").strip().lower()
    try:
        from adminapi.runtime import get_runtime

        with transaction.atomic():
            override = str(get_runtime("vstudio_mode", "") or "").strip().lower()
        if override in MODES:
            mode = override
    except Exception:
        logger.debug("vstudio: правка vstudio_mode не прочиталась", exc_info=True)
    return mode if mode in MODES else "staff"


def can_generate(user, mode: str) -> bool:
    """Может ли человек пользоваться студией при этом режиме.

    on — все (гость видит цены, запуск всё равно требует входа); staff — только
    is_staff (обкатка), остальным «скоро откроется»; off — никто.
    """
    if mode == "on":
        return True
    if mode == "staff":
        return bool(user and getattr(user, "is_authenticated", False) and getattr(user, "is_staff", False))
    return False


class StudioOpen(BasePermission):
    """403 vstudio_disabled, если режим не пускает этого человека."""

    def has_permission(self, request, view):
        if not can_generate(request.user, studio_mode()):
            raise StudioError("vstudio_disabled")
        return True


def _user(request):
    user = getattr(request, "user", None)
    return user if user is not None and getattr(user, "is_authenticated", False) else None


class StudioAPIView(APIView):
    """База всех вьюх студии: JWT, флаг, свой throttle scope на метод, форма ошибок.

    scopes — {метод: scope}; ScopedRateThrottle читает throttle_scope в момент
    проверки, поэтому GET и PATCH одного адреса считаются в разных счётчиках.
    Для BE-10 (assist/condense/) — наследоваться отсюда же.
    """

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated, StudioOpen]
    throttle_classes = [ScopedRateThrottle]
    scopes: dict = {}
    default_scope = SCOPE_READ

    @property
    def throttle_scope(self):
        method = str(getattr(getattr(self, "request", None), "method", "") or "GET").upper()
        return self.scopes.get(method, self.default_scope)

    def get_exception_handler(self):
        return exception_handler


class PublicStudioView(StudioAPIView):
    """AllowAny (models/, quote/, showcase/): то, что видит гость.

    Без AnonRateThrottle. Общий anon-счётчик (30/мин) делят все гости за одним
    IP — NAT мобильного оператора — и все остальные анонимные запросы сайта, а
    первый экран студии сам делает несколько запросов подряд: гость ловил бы
    429 ещё до первого клика. Свой scope и так считает гостей по IP.
    """

    permission_classes = [AllowAny]


# ---------------------------------------------------------------- модель и компиляция

def resolve_model(model_ref: str):
    """(GPTModels | None, Caps | None, spec | None). Caps None — модель скрыта (§3.1)."""
    model_obj = (GPTModels.objects.filter(openrouter_id=model_ref)
                 .order_by("-vstudio_enabled", "-is_active", "pk").first())
    if model_obj is None:
        return None, None, None
    fam = caps_mod.family_of(model_obj.openrouter_id)
    if fam is None:
        return model_obj, None, None
    if fam.kind == caps_mod.KIND_VIDEO:
        spec = caps_mod.catalog_spec(model_obj.openrouter_id)
        return model_obj, caps_mod.for_model(model_obj, spec=spec), spec
    return model_obj, caps_mod.for_model(model_obj), None


@dataclass
class Prepared:
    """Всё, что знает сервер о запросе: для quote, запуска и повтора одинаково."""

    req: S.ShotRequest
    model_obj: object
    caps: object
    spec: object
    doc: object
    compiled: compiler.Compiled
    price: pricing.Price
    assets: dict

    @property
    def credits(self):
        return self.price.credits

    def eta_s(self) -> int:
        kind = self.caps.kind if self.caps else self.req.kind
        ref = self.model_obj.openrouter_id if self.model_obj else self.req.model_ref
        try:
            return int(pipeline.eta_seconds(ref, kind, default=self.caps.eta_s if self.caps else None))
        except Exception:
            return int(pipeline.default_eta(ref, kind))


def prepare(user, req: S.ShotRequest, *, allow_deleted: bool = False) -> Prepared:
    """Модель → входы человека → документ → компилятор → цена. Без записи в БД.

    Материалы ищутся только среди своих (owned_by): чужой uid «не найден».
    Включённый, но не найденный материал — asset_not_found, а не молчаливый
    пропуск: иначе номера @Image N у сервера и у человека разошлись бы, и модель
    получила бы не те фото. Если его упоминает текст, компилятор и так скажет
    mention_not_attached — второй раз не дублируем.
    """
    model_obj, caps, spec = resolve_model(req.model_ref)
    assets: dict = {}
    if req.inputs and user is not None:
        uids = {row["asset"] for row in req.inputs}
        assets = {a.uid: a for a in Asset.objects.owned_by(user).filter(uid__in=uids)}
    resolved, missing = [], []
    for row in req.inputs:
        asset = assets.get(row["asset"])
        if asset is None:
            missing.append(row)
            continue
        resolved.append(compiler.ResolvedInput(compiler.AssetView.from_asset(asset), row["slot"],
                                               row["position"], row["role"], row["included"]))

    doc = req.doc
    pre_errors: list = []
    pre_warnings: list = []
    if req.text is not None:
        try:
            parsed = pd.from_text(req.text, resolved)
        except pd.PromptDocError:
            doc = None  # компилятор ответит prompt_doc_invalid
        else:
            doc, pre_errors, pre_warnings = parsed.doc, list(parsed.errors), list(parsed.warnings)

    compiled = compiler.compile(
        caps, req.kind, doc, resolved, req.params,
        site_base=str(getattr(settings, "SITE_BASE_URL", "") or ""),
        inline_refs=bool(getattr(settings, "VSTUDIO_INLINE_REFS", False)),
        allow_deleted=allow_deleted)
    if compiled.doc is not None:
        # Компилятор привязал теги, набранные текстом: храним то, что ушло модели.
        doc = compiled.doc
        # tag_unknown и video_refs_unsupported компилятор теперь находит сам —
        # из разбора prompt_text берём только то, чего у него нет (без двойных плашек).
        seen_issues = {(i.get("code"), str((i.get("params") or {}).get("text") or ""))
                       for i in compiled.errors + compiled.warnings}
        pre_errors = [i for i in pre_errors
                      if (i.get("code"), str((i.get("params") or {}).get("text") or "")) not in seen_issues]
        pre_warnings = [i for i in pre_warnings
                        if (i.get("code"), str((i.get("params") or {}).get("text") or "")) not in seen_issues]

    mentioned = set(pd.ref_uids(doc)) if pd.is_valid(doc) else set()
    missing_errors, seen = [], set()
    for row in missing:
        uid = row["asset"]
        if not row["included"] or uid in mentioned or uid in seen:
            continue
        seen.add(uid)
        missing_errors.append(compiler.issue("asset_not_found", asset=uid, slot=row["slot"], n=None,
                                             label=None, fix={"action": "exclude_inputs", "assets": [uid]}))
    if missing_errors or pre_errors:
        compiled.errors[:0] = missing_errors + pre_errors
        compiled.body = {}  # с ошибками запускать нельзя — тела нет
    if pre_warnings:
        compiled.warnings[:0] = pre_warnings

    price = pricing.price(compiled, model_obj, caps, spec=spec) if caps is not None else pricing.NO_PRICE
    return Prepared(req=req, model_obj=model_obj, caps=caps, spec=spec, doc=doc, compiled=compiled,
                    price=price, assets=assets)


def _fallback_meter(p: Prepared) -> dict:
    """Счётчик, когда компилятор не дошёл до него (модель недоступна, документ кривой)."""
    text = pd.plain_text(p.doc) if pd.is_valid(p.doc) else str(p.req.text or "")
    return {"chars": len(text), "words": len(text.split()), "soft_words": None,
            "hard_chars": pd.MAX_TEXT_CHARS, "level": "ok"}


def quote_json(p: Prepared, user) -> dict:
    """QuoteJSON (§8.3): ошибки компилятора — внутри ответа, баланс null для гостя."""
    c = p.compiled
    return {
        "credits": p.credits,
        "breakdown": [dict(line) for line in p.price.breakdown],
        "balance": reserve.balance_snapshot(user, p.credits) if user is not None else None,
        "mode": c.mode or None,
        "effective": c.effective or {},
        "labels": c.labels or {},
        "serialized_prompt": c.serialized_prompt or "",
        "errors": c.errors,
        "warnings": c.warnings,
        "meter": c.meter or _fallback_meter(p),
        "dropped": c.dropped,
        "eta_s": p.eta_s(),
    }


def _premium_locked() -> StudioError:
    extra = {}
    try:
        from ai.handlers import _premium_locked_error

        payload = _premium_locked_error()
        if payload.get("min_package_kgs") is not None:
            extra["min_package_kgs"] = payload["min_package_kgs"]
    except Exception:
        pass
    return StudioError("premium_locked", **extra)


def check_can_run(user, p: Prepared, quoted: int) -> int:
    """Проверки перед резервом (§6.3, шаги 3–5). Возвращает цену в кредитах.

    Порядок: тариф (403 premium_locked) → ошибки компилятора (422, или 503 при
    service_misconfigured) → цена есть → совпала с кнопкой (409 price_changed).
    Молча другую сумму не списываем ни в какую сторону.
    """
    c = p.compiled
    if p.model_obj is not None and p.caps is not None and not can_use_model(user, p.model_obj):
        raise _premium_locked()
    lists = {"errors": c.errors, "warnings": c.warnings}
    codes = {e.get("code") for e in c.errors}
    if "service_misconfigured" in codes:
        raise StudioError("service_misconfigured", **lists)
    if "prompt_doc_invalid" in codes:
        raise StudioError("prompt_doc_invalid", **lists)
    if c.errors:
        raise StudioError("blocked", **lists)
    credits = p.credits
    if not credits or credits <= 0 or not c.body:
        # Цены нет без ошибок компилятора — каталог модели не ответил. Не
        # запускаем «бесплатно» и не гадаем сумму.
        raise StudioError("blocked", errors=[compiler.issue("model_unavailable")], warnings=c.warnings)
    if int(quoted) != int(credits):
        raise StudioError("price_changed", credits=credits,
                          breakdown=[dict(line) for line in p.price.breakdown])
    return int(credits)


def _create_take(*, user, shot: Shot, project: Project, p: Prepared, quoted: int, cid: str):
    """Take в резерве (+ pending-ассет картинки: сразу чип в лотке). Внутри spend_gate."""
    c = p.compiled
    pending = None
    if shot.kind == Shot.KIND_IMAGE:
        pending = Asset.objects.create(
            user=user, project=project, kind=Asset.KIND_IMAGE, source=Asset.SOURCE_GENERATED_IMAGE,
            status=Asset.STATUS_PENDING, width=None, height=None,
            meta={"prompt": (shot.prompt_text or "")[:2000], "model": shot.model_ref})
    take = Take.objects.create(
        user=user, shot=shot, project=project, kind=shot.kind, mode=c.mode, model_ref=shot.model_ref,
        status=Take.STATUS_QUEUED, serialized_prompt=c.serialized_prompt, request_body=c.body,
        effective=c.effective, dropped=c.dropped, warnings=c.warnings, credits_quoted=int(quoted),
        credits_reserved=int(p.credits), charge_state=Take.CHARGE_RESERVED, client_request_id=cid,
        result_asset=pending)
    if pending is not None:
        meta = {**pending.meta, "take": take.uid}
        Asset.objects.filter(pk=pending.pk).update(origin_take=take, meta=meta)
        pending.origin_take, pending.meta = take, meta
    Project.touch(project.pk)
    return take


def _enqueue_after_commit(take: Take) -> None:
    # Воркер не должен увидеть дубль раньше, чем он появится в базе.
    transaction.on_commit(partial(pipeline.enqueue_start, take))


# ---------------------------------------------------------------- выборки

def projects_qs(user):
    """Проекты человека с числом открытых дублей и превью — одним запросом на страницу."""
    open_sq = (Take.objects.filter(project=OuterRef("pk"), status__in=TAKE_OPEN).order_by()
               .values("project").annotate(c=Count("pk")).values("c"))
    thumb_sq = S.project_thumb_qs(OuterRef("pk"))[:1]
    return (Project.objects.filter(user=user)
            .annotate(open_n=Coalesce(Subquery(open_sq, output_field=IntegerField()), 0),
                      thumb_path=Subquery(thumb_sq)))


def shots_qs(user):
    return (Shot.objects.filter(user=user).select_related("project", "model", "forked_from")
            .prefetch_related(
                Prefetch("inputs", queryset=ShotInput.objects.select_related("asset")),
                Prefetch("takes", queryset=Take.objects.filter(user=user).select_related("result_asset")
                         .order_by("created_at", "pk"))))


def takes_qs(user):
    return Take.objects.filter(user=user).select_related("shot", "result_asset")


def _get_owned(qs, uid, code: str):
    """Своя строка по uid или 404 с кодом; кривой uid — тот же 404 (не раскрываем)."""
    obj = qs.filter(uid=uid).first() if S.is_uid(uid) else None
    if obj is None:
        raise StudioError(code)
    return obj


def run_payload(take: Take, user) -> dict:
    """RunShotResponse: {project (полный ProjectJSON), shot, take, asset, balance}."""
    take = takes_qs(user).get(pk=take.pk)
    shot = shots_qs(user).get(pk=take.shot_id)
    project = projects_qs(user).get(pk=take.project_id)
    return {
        "project": S.project_json(project),
        "shot": S.shots_json([shot])[0],
        "take": S.take_lite(take, S.TakeContext([take])),
        "asset": S.asset_json(take.result_asset) if take.kind == Take.KIND_IMAGE else None,
        "balance": reserve.balance_snapshot(user),
    }


def retry_payload(take: Take, user) -> dict:
    take = takes_qs(user).get(pk=take.pk)
    return {"take": S.take_lite(take, S.TakeContext([take])), "balance": reserve.balance_snapshot(user)}


def _existing_take(user, cid: str):
    return Take.objects.filter(user=user, client_request_id=cid).first()


# ---------------------------------------------------------------- модели

def _model_json(model_obj, caps, spec, *, locked: bool) -> dict:
    prices = pricing.model_prices(model_obj, caps, spec=spec)
    try:
        eta = int(pipeline.eta_seconds(model_obj.openrouter_id, caps.kind, default=caps.eta_s))
    except Exception:
        eta = int(caps.eta_s)
    out = {
        "id": model_obj.openrouter_id,
        "name": caps.name,
        "badge": caps.badge,
        "locked": bool(locked),
        "eta_s": eta,
        "price_from": prices.get("price_from"),
        "caps": caps_mod.to_json(caps),
        "defaults": caps_mod.defaults(caps),
    }
    if prices.get("price") is not None:
        out["price"] = prices["price"]
    if prices.get("per_image") is not None:
        out["per_image"] = prices["per_image"]
    return out


def models_catalog(user) -> dict:
    """{video: [ModelJSON], image: [ModelJSON]} — кэш 10 минут на тариф.

    locked зависит только от тарифа (can_use_model: guest/free видят замок на
    платных моделях, paid — нет), поэтому ключ кэша — тариф. Одна сломанная
    модель список не роняет; если каталог OpenRouter не ответил, урезанный
    список держим в кэше минуту, а не десять.
    """
    tier = user_tier(user)
    key = MODELS_CACHE_KEY.format(tier=tier)
    try:
        cached = cache.get(key)
    except Exception:
        cached = None
    if cached is not None:
        return cached

    rows: dict = {caps_mod.KIND_VIDEO: [], caps_mod.KIND_IMAGE: []}
    seen: set = set()
    degraded = False
    for model_obj in GPTModels.objects.filter(is_active=True, vstudio_enabled=True).order_by("sort_order", "id"):
        ref = model_obj.openrouter_id
        if not ref or ref in seen:
            continue
        try:
            fam = caps_mod.family_of(ref)
            if fam is None:
                continue
            if fam.kind == caps_mod.KIND_VIDEO:
                spec = caps_mod.catalog_spec(ref)
                if not spec:
                    degraded = True
                    continue
                caps = caps_mod.for_model(model_obj, spec=spec)
            else:
                spec = None
                caps = caps_mod.for_model(model_obj)
            if caps is None:
                continue
            seen.add(ref)
            rows[caps.kind].append(((caps.sort, caps.name.lower()),
                                    _model_json(model_obj, caps, spec,
                                                locked=not can_use_model(user, model_obj))))
        except Exception:
            degraded = True
            logger.exception("vstudio models: модель %s не попала в список", ref)
    out = {kind: [row for _, row in sorted(items, key=lambda r: r[0])] for kind, items in rows.items()}
    try:
        cache.set(key, out, MODELS_CACHE_DEGRADED_S if degraded else MODELS_CACHE_S)
    except Exception:
        pass
    return out


class ModelsView(PublicStudioView):
    """GET models/ — {mode, available, video, image}. Доступно всем и при любом режиме:
    по нему фронт решает, показывать студию или «скоро откроется»."""

    scopes = {"GET": SCOPE_READ}

    def get(self, request):
        mode = studio_mode()
        available = can_generate(request.user, mode)
        catalog = {"video": [], "image": []} if mode == "off" else models_catalog(request.user)
        return Response({"mode": mode, "available": available,
                         "video": catalog.get("video", []), "image": catalog.get("image", [])})


class ShowcaseView(PublicStudioView):
    """GET showcase/ — {items, reel_size}: работы для первого экрана, отобранные владельцем.

    Открыто всем, как и models/: первый экран показывает их гостю до входа.
    Что именно уходит наружу — vstudio.showcase.public_json. Студия выключена
    (off) — витрины нет. reel_size — сколько работ берёт карусель (настройка
    панели): в кэш списка не входит и читается на каждый ответ, иначе новое
    значение ждало бы на сайте до пяти минут.
    """

    scopes = {"GET": SCOPE_READ}

    def get(self, request):
        items = [] if studio_mode() == "off" else showcase.public_items()
        return Response({"items": items, "reel_size": showcase.reel_size()})


# ---------------------------------------------------------------- цена

class QuoteView(PublicStudioView):
    """POST quote/ — цена и все проверки компилятора. 200 даже с ошибками компилятора.

    Гость может спросить цену только без материалов (свои фото есть только у
    вошедших). {shot: uid} — цена «Повторить» для своего кадра.
    """

    permission_classes = [AllowAny, StudioOpen]
    # Свой scope, а не общий anon-счётчик (см. PublicStudioView): цена
    # пересчитывается на каждую паузу в наборе текста (700 мс) — гость ловил бы
    # 429 на кнопке. vstudio_quote (90/мин) и так считает гостей по IP.
    scopes = {"POST": SCOPE_QUOTE}

    def post(self, request):
        data = S.body_dict(request)
        user = _user(request)
        allow_deleted = False
        if data.get("shot") is not None:
            if user is None:
                raise StudioError("unauthorized")
            shot = _get_owned(shots_qs(user), data.get("shot"), "shot_not_found")
            req = S.request_from_shot(shot)
            # Повтор старого кадра: удалённое фото ещё живёт, пока на него ссылаются.
            allow_deleted = True
        else:
            req = S.parse_shot_request(data)
            if user is None and req.inputs:
                raise StudioError("unauthorized")
        return Response(quote_json(prepare(user, req, allow_deleted=allow_deleted), user))


# ---------------------------------------------------------------- запуск

class ShotsView(StudioAPIView):
    """POST shots/ — запуск: 202 {project, shot, take, asset?, balance}; 200 при повторе
    того же client_request_id (двойной клик и обрыв сети не платят дважды)."""

    scopes = {"POST": SCOPE_RUN}

    def post(self, request):
        user = request.user
        data = S.body_dict(request)
        cid = S.parse_client_request_id(data)
        existing = _existing_take(user, cid)
        if existing is not None:
            return Response(run_payload(existing, user), status=http.HTTP_200_OK)

        quoted = S.parse_quoted(data)
        req = S.parse_shot_request(data)
        origin = S.parse_origin(data, req.kind)
        forked = None
        raw_fork = data.get("forked_from")
        if raw_fork not in (None, ""):
            if not S.is_uid(raw_fork):
                raise S.bad("forked_from")
            # Связь «Изменён из» — только для истории; чужой или удалённый кадр — без связи.
            forked = Shot.objects.filter(user=user, uid=raw_fork).first()
        project = None
        if req.project_uid:
            project = _get_owned(Project.objects.filter(user=user), req.project_uid, "project_not_found")

        p = prepare(user, req)
        credits = check_can_run(user, p, quoted)
        c = p.compiled
        doc = pd.validate(p.doc)  # чистая копия: компилятор уже проверил, ошибок нет

        try:
            with reserve.spend_gate(user, credits, kind=req.kind, client_request_id=cid):
                if project is None:
                    project = Project.objects.create(
                        user=user, title=S.auto_title(c.prompt_text),
                        settings={"kind": req.kind, "model": p.model_obj.openrouter_id, "params": req.params})
                elif not project.title:
                    Project.objects.filter(pk=project.pk, title="").update(title=S.auto_title(c.prompt_text))
                shot = Shot.objects.create(
                    user=user, project=project, kind=req.kind, origin=origin, model=p.model_obj,
                    model_ref=p.model_obj.openrouter_id, prompt_doc=doc, prompt_text=c.prompt_text,
                    params=req.params, forked_from=forked)
                ShotInput.objects.bulk_create([
                    ShotInput(shot=shot, asset=p.assets[row["asset"]], slot=row["slot"],
                              position=row["position"], role=row["role"], included=row["included"])
                    for row in c.inputs])
                take = _create_take(user=user, shot=shot, project=project, p=p, quoted=quoted, cid=cid)
        except reserve.AlreadyStarted as started:
            return Response(run_payload(started.take, user), status=http.HTTP_200_OK)
        except reserve.SpendRefused as refused:
            return Response(refused.payload, status=refused.status)
        except IntegrityError:
            # Второй запрос того же клика успел раньше (vs_take_idem): отвечаем его дублем.
            existing = _existing_take(user, cid)
            if existing is None:
                raise
            return Response(run_payload(existing, user), status=http.HTTP_200_OK)

        _enqueue_after_commit(take)
        logger.info("vstudio run take=%s shot=%s model=%s credits=%s", take.uid, shot.uid,
                    take.model_ref, credits)
        return Response(run_payload(take, user), status=http.HTTP_202_ACCEPTED)


class ShotRetryView(StudioAPIView):
    """POST shots/<uid>/retry/ — новый дубль того же кадра по новой цене: 202 {take, balance}."""

    scopes = {"POST": SCOPE_RUN}

    def post(self, request, uid):
        user = request.user
        shot = _get_owned(shots_qs(user), uid, "shot_not_found")
        data = S.body_dict(request)
        cid = S.parse_client_request_id(data)
        existing = _existing_take(user, cid)
        if existing is not None:
            return Response(retry_payload(existing, user), status=http.HTTP_200_OK)
        quoted = S.parse_quoted(data)

        p = prepare(user, S.request_from_shot(shot), allow_deleted=True)
        credits = check_can_run(user, p, quoted)
        try:
            with reserve.spend_gate(user, credits, kind=shot.kind, client_request_id=cid):
                take = _create_take(user=user, shot=shot, project=shot.project, p=p, quoted=quoted, cid=cid)
        except reserve.AlreadyStarted as started:
            return Response(retry_payload(started.take, user), status=http.HTTP_200_OK)
        except reserve.SpendRefused as refused:
            return Response(refused.payload, status=refused.status)
        except IntegrityError:
            existing = _existing_take(user, cid)
            if existing is None:
                raise
            return Response(retry_payload(existing, user), status=http.HTTP_200_OK)

        _enqueue_after_commit(take)
        logger.info("vstudio retry take=%s shot=%s credits=%s", take.uid, shot.uid, credits)
        return Response(retry_payload(take, user), status=http.HTTP_202_ACCEPTED)


# ---------------------------------------------------------------- дубли

class TakesView(StudioAPIView):
    """GET takes/?ids=a,b,c (≤30) — опрос статусов. Ставит vstudio:seen: пока
    страница открыта, пуши о готовности не нужны (§6.6)."""

    scopes = {"GET": SCOPE_POLL}

    def get(self, request):
        raw = str(request.query_params.get("ids") or "")
        ids = []
        for part in raw.split(","):
            part = part.strip()
            if S.is_uid(part) and part not in ids:
                ids.append(part)
        if len(ids) > MAX_POLL_IDS:
            raise S.bad("ids", f"Не больше {MAX_POLL_IDS} генераций за один запрос.")
        notify.mark_seen(request.user.pk)
        if not ids:
            return Response({"items": []})
        found = {t.uid: t for t in takes_qs(request.user).filter(uid__in=ids)}
        ordered = [found[uid] for uid in ids if uid in found]
        return Response({"items": S.take_lites(ordered)})


class ActiveTakesView(StudioAPIView):
    """GET takes/active/ — открытые дубли по всем проектам («Восстановили N генераций»)."""

    scopes = {"GET": SCOPE_READ}

    def get(self, request):
        takes = (takes_qs(request.user).select_related("project").filter(status__in=TAKE_OPEN)
                 .order_by("created_at", "pk"))
        return Response({"items": S.take_lites(takes, with_project=True)})


class TakeDetailView(StudioAPIView):
    """GET takes/<uid>/ — TakeJSON с «Что ушло модели»."""

    scopes = {"GET": SCOPE_READ}

    def get(self, request, uid):
        take = _get_owned(takes_qs(request.user), uid, "take_not_found")
        return Response(S.take_json(take, S.TakeContext([take])))


class TakeCancelView(StudioAPIView):
    """POST takes/<uid>/cancel/ — только из queued; иначе 409 already_submitted
    (ушедшее провайдеру уже оплачено нами — отменить нельзя)."""

    scopes = {"POST": SCOPE_WRITE}

    def post(self, request, uid):
        take = _get_owned(Take.objects.filter(user=request.user), uid, "take_not_found")
        if not pipeline.cancel(take.pk):
            raise StudioError("already_submitted")
        take = takes_qs(request.user).get(pk=take.pk)
        return Response(S.take_lite(take, S.TakeContext([take])))


# ---------------------------------------------------------------- проекты

class ProjectsView(StudioAPIView):
    """GET projects/?q=&archived=0&before=<iso>&limit=30 — «История»; POST — новый проект."""

    scopes = {"GET": SCOPE_READ, "POST": SCOPE_WRITE}

    def get(self, request):
        qp = request.query_params
        archived = S.parse_bool_flag(qp.get("archived"), default=False)
        needle = str(qp.get("q") or "").strip()[:200]
        before = S.parse_before(qp.get("before"))
        limit = S.parse_limit(qp.get("limit"), default=30, maximum=100)
        qs = projects_qs(request.user).filter(is_archived=archived)
        if needle:
            # Поиск по истории — и по названию, и по тексту запросов (prompt_text с @Image N).
            in_prompts = Shot.objects.filter(user=request.user, prompt_text__icontains=needle).values("project_id")
            qs = qs.filter(Q(title__icontains=needle) | Q(pk__in=in_prompts))
        if before is not None:
            qs = qs.filter(last_activity_at__lt=before)
        rows = list(qs.order_by("-last_activity_at", "-pk")[: limit + 1])
        more = len(rows) > limit
        rows = rows[:limit]
        return Response({"items": [S.project_json(p) for p in rows],
                         "next": S.iso(rows[-1].last_activity_at) if more and rows else None})

    def post(self, request):
        data = S.body_dict(request)
        project = Project.objects.create(user=request.user, title=S.parse_title(data.get("title")))
        return Response(S.project_json(projects_qs(request.user).get(pk=project.pk)),
                        status=http.HTTP_201_CREATED)


class ProjectDetailView(StudioAPIView):
    """GET / PATCH / DELETE projects/<uid>/. DELETE — мягко в архив, 204."""

    scopes = {"GET": SCOPE_READ, "PATCH": SCOPE_WRITE, "DELETE": SCOPE_WRITE}

    def get(self, request, uid):
        return Response(S.project_json(_get_owned(projects_qs(request.user), uid, "project_not_found")))

    def patch(self, request, uid):
        project = _get_owned(Project.objects.filter(user=request.user), uid, "project_not_found")
        data = S.body_dict(request)
        fields = []
        if "title" in data:
            project.title = S.parse_title(data.get("title"))
            fields.append("title")
        if "settings" in data:
            # Фронт шлёт настройки целиком (со своими by_kind) — заменяем, не сливаем.
            project.settings = S.parse_settings(data.get("settings"))
            fields.append("settings")
        if "is_archived" in data:
            if not isinstance(data.get("is_archived"), bool):
                raise S.bad("is_archived")
            project.is_archived = data["is_archived"]
            fields.append("is_archived")
        if fields:
            project.save(update_fields=fields + ["updated_at"])
        return Response(S.project_json(projects_qs(request.user).get(pk=project.pk)))

    def delete(self, request, uid):
        project = _get_owned(Project.objects.filter(user=request.user), uid, "project_not_found")
        if not project.is_archived:
            project.is_archived = True
            project.save(update_fields=["is_archived", "updated_at"])
        return Response(status=http.HTTP_204_NO_CONTENT)


class ProjectShotsView(StudioAPIView):
    """GET projects/<uid>/shots/?before=<shot_uid>&limit=20 — лента.

    Страница — от новых к старым (прокрутка вверх подгружает старые), внутри
    страницы — по возрастанию; next — uid самого старого кадра страницы.
    """

    scopes = {"GET": SCOPE_READ}

    def get(self, request, uid):
        user = request.user
        project = _get_owned(Project.objects.filter(user=user), uid, "project_not_found")
        qp = request.query_params
        limit = S.parse_limit(qp.get("limit"), default=20, maximum=50)
        qs = shots_qs(user).filter(project=project)
        before = qp.get("before")
        if before not in (None, ""):
            if not S.is_uid(before):
                raise S.bad("before")
            pivot = Shot.objects.filter(user=user, project=project, uid=before).values("pk", "created_at").first()
            if pivot is None:
                return Response({"items": [], "next": None})
            qs = qs.filter(Q(created_at__lt=pivot["created_at"])
                           | Q(created_at=pivot["created_at"], pk__lt=pivot["pk"]))
        rows = list(qs.order_by("-created_at", "-pk")[: limit + 1])
        more = len(rows) > limit
        rows = rows[:limit]
        rows.reverse()
        return Response({"items": S.shots_json(rows), "next": rows[0].uid if more and rows else None})


# ---------------------------------------------------------------- материалы

class AssetsView(StudioAPIView):
    """GET assets/?kind=image&source=&before=<iso>&limit=60 — «Мои материалы»;
    POST assets/ — загрузка ровно одного фото (201 новое, 200 — то же фото уже было)."""

    scopes = {"GET": SCOPE_READ, "POST": SCOPE_UPLOAD}
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request):
        qp = request.query_params
        kind = str(qp.get("kind") or Asset.KIND_IMAGE)
        if kind not in dict(Asset.KIND_CHOICES):
            raise S.bad("kind")
        source = str(qp.get("source") or "")
        if source and source not in dict(Asset.SOURCE_CHOICES):
            raise S.bad("source")
        before = S.parse_before(qp.get("before"))
        limit = S.parse_limit(qp.get("limit"), default=60, maximum=100)
        qs = Asset.objects.owned_by(request.user).alive().filter(kind=kind)
        if source:
            qs = qs.filter(source=source)
        if before is not None:
            qs = qs.filter(created_at__lt=before)
        rows = list(qs.order_by("-created_at", "-pk")[: limit + 1])
        more = len(rows) > limit
        rows = rows[:limit]
        return Response({"items": [S.asset_json(a) for a in rows],
                         "next": S.iso(rows[-1].created_at) if more and rows else None})

    def post(self, request):
        try:
            upload = single_upload(request.FILES)
        except AssetError as err:
            return Response(err.response_data(), status=err.status)
        project = None
        raw = request.data.get("project") if hasattr(request.data, "get") else None
        if raw not in (None, ""):
            if not S.is_uid(raw):
                raise S.bad("project")
            project = _get_owned(Project.objects.filter(user=request.user), raw, "project_not_found")
        try:
            ingested = ingest_upload(request.user, upload, project)
        except AssetError as err:
            return Response(err.response_data(), status=err.status)
        return Response(S.asset_json(ingested.asset),
                        status=http.HTTP_201_CREATED if ingested.created else http.HTTP_200_OK)


class AssetDetailView(StudioAPIView):
    """DELETE assets/<uid>/ — мягкое удаление (файл живёт, пока на него ссылаются кадры)."""

    scopes = {"DELETE": SCOPE_WRITE}

    def delete(self, request, uid):
        asset = _get_owned(Asset.objects.owned_by(request.user), uid, "asset_not_found")
        if asset.deleted_at is None:
            # Условный UPDATE: повторное удаление не сдвигает дату (от неё считаются 30 дней).
            Asset.objects.filter(pk=asset.pk, deleted_at__isnull=True).update(deleted_at=timezone.now())
            # Удалённая работа не должна ещё пять минут висеть в публичной витрине.
            showcase.forget_assets([asset.pk])
        return Response(status=http.HTTP_204_NO_CONTENT)


class AssetFromTakeView(StudioAPIView):
    """POST assets/from-take/ {take, at:"last_frame"} — «Последний кадр → первый»."""

    scopes = {"POST": SCOPE_WRITE}

    def post(self, request):
        data = S.body_dict(request)
        at = data.get("at") or "last_frame"
        if at != "last_frame":
            raise S.bad("at")
        take = _get_owned(Take.objects.filter(user=request.user).select_related("result_asset"),
                          data.get("take"), "take_not_found")
        try:
            ingested = from_take_last_frame(take)
        except AssetError as err:
            return Response(err.response_data(), status=err.status)
        return Response(S.asset_json(ingested.asset),
                        status=http.HTTP_201_CREATED if ingested.created else http.HTTP_200_OK)


__all__ = [
    "StudioAPIView", "PublicStudioView", "StudioOpen", "studio_mode", "can_generate", "prepare",
    "Prepared", "resolve_model", "quote_json", "check_can_run", "models_catalog",
    "ModelsView", "ShowcaseView", "QuoteView", "ShotsView", "ShotRetryView", "TakesView",
    "ActiveTakesView", "TakeDetailView", "TakeCancelView", "ProjectsView", "ProjectDetailView",
    "ProjectShotsView", "AssetsView", "AssetDetailView", "AssetFromTakeView",
]
