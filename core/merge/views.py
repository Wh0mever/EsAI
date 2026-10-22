"""API склейки (/api/merge/).

Путь человека:
  1. GET  config/                 — цена, пределы (открыт и гостю: страница с карточкой входа)
  2. GET  sources/?type=&page=    — свои готовые видео для выбора фрагментов
  3. POST /  · PATCH <id>/        — склейка: название, формат, заполнение, порядок фрагментов
  4. POST <id>/render/            — запуск: резерв цены, задача в очереди media
  5. GET  <id>/                   — опрос состояния (раз в 3 с, пока queued/rendering)
  6. GET  <id>/download/          — скачать готовый ролик
Свои видео (Build MU): GET/POST uploads/ — список «Мои файлы» и загрузка
(multipart, поле file), DELETE uploads/<id>/ — удалить; в склейку — {type: "upload", id}.
Тело любого отказа — {"error": "<по-русски>", "error_code": "<код>", …}, как в видеостудии.
"""
from __future__ import annotations

import logging

from django.core.cache import cache
from django.core.files.storage import default_storage
from django.db import transaction
from django.http import FileResponse
from rest_framework import status as http
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication

from adminapi.permissions import IsStaff
from core.langutils import request_lang
from vstudio.errors import error_body, exception_handler

from . import services, uploads
from .config import (ASPECTS, DEFAULT_PRICE, FITS, MAX_PRICE, MB, PRICE_KEY, UPLOAD_MAX_BYTES,
                     limits, price_credits, upload_limits)
from .models import MergeProject
from .serializers import project_brief, project_json
from .services import MergeError
from .sources import LIST_TYPES, TYPES, list_page

logger = logging.getLogger(__name__)

LIST_PAGE_SIZE = 50

# Отдач файла одного владельца разом (по входу и по ссылке ?t= вместе) и
# срок жизни счётчика: место, не освобождённое упавшим процессом, само истечёт.
DOWNLOAD_SLOTS = 2
DOWNLOAD_SLOT_TTL = 15 * 60
MSG_DOWNLOADS_BUSY = "Этот ролик уже скачивается. Дождитесь окончания и попробуйте снова."

# Одна загрузка своего видео за раз у человека: после тела запрос держит поток
# gunicorn (их 24 на весь сайт) на разбор и обложку — до 50 с, а счётчик
# «20 в час» не атомарный: пачка параллельных запросов прошла бы его целиком.
# Срок — страховка на упавший процесс; обычно место освобождается сразу.
UPLOAD_SLOT_TTL = 120
MSG_UPLOAD_BUSY = "Уже загружается другое видео. Дождитесь окончания и загрузите следующее."
# Тело отказанной загрузки дочитываем, но не больше этого: без этого gunicorn
# закрывает соединение с непрочитанным телом, nginx ещё пишет его и вместо
# нашего ответа (401 для обновления токена, отказ с текстом) отдаёт 502.
DRAIN_LIMIT = UPLOAD_MAX_BYTES + 8 * MB
DRAIN_CHUNK = MB


class ReadThrottle(UserRateThrottle):
    scope = "merge_read"
    rate = "120/min"


class WriteThrottle(UserRateThrottle):
    scope = "merge_write"
    rate = "60/min"


class RenderThrottle(UserRateThrottle):
    scope = "merge_render"
    rate = "10/min"


class DownloadThrottle(UserRateThrottle):
    scope = "merge_download"
    rate = "30/min"


class UploadThrottle(UserRateThrottle):
    # Каждая загрузка — до 90 МБ на диск и разбор ffmpeg на двух ядрах сервера.
    scope = "merge_upload"
    rate = "20/hour"


def _refusal(exc: MergeError) -> Response:
    return Response(exc.body(), status=exc.status)


class MergeAPIView(APIView):
    """JWT, вход обязателен, свой счётчик запросов на метод, форма ошибок студии."""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]
    throttles: dict = {}

    def get_throttles(self):
        method = str(getattr(self.request, "method", "GET") or "GET").upper()
        return [self.throttles.get(method, ReadThrottle)()]

    def get_exception_handler(self):
        return exception_handler


def _balance(user, need: int) -> dict:
    """{balance, reserved, available, after}: хватит ли на склейку (кнопка «не хватает N»)."""
    from django.contrib.auth import get_user_model

    from vstudio.reserve import total_reserved

    balance = int(get_user_model().objects.filter(pk=user.pk)
                  .values_list("token_balance", flat=True).first() or 0)
    reserved = total_reserved(user)
    available = max(0, balance - reserved)
    return {"balance": balance, "reserved": reserved, "available": available,
            "after": available - int(need)}


class ConfigView(MergeAPIView):
    """GET config/ — цена и пределы; гостю тоже (страница показывает карточку входа)."""

    permission_classes = [AllowAny]

    def get(self, request):
        price = price_credits()
        user = request.user if request.user and request.user.is_authenticated else None
        return Response({
            "price_credits": price,
            "limits": limits(),
            "aspects": list(ASPECTS),
            "fits": list(FITS),
            "source_types": list(TYPES),
            "authenticated": user is not None,
            "balance": _balance(user, price) if user else None,
            "uploads": upload_limits(),
        })


class SourcesView(MergeAPIView):
    """GET sources/?type=vstudio|cartoon|cartoon_scene|cartoon_movie|chat&page=1."""

    def get(self, request):
        kind = str(request.query_params.get("type") or "").strip()
        if kind not in LIST_TYPES:
            return Response(error_body("bad_request", "Неизвестный вид видео.", field="type"),
                            status=http.HTTP_400_BAD_REQUEST)
        try:
            page = int(request.query_params.get("page") or 1)
        except (TypeError, ValueError):
            page = 1
        page = min(max(1, page), 1000)
        return Response(list_page(request.user, kind, page, lang=request_lang(request)))


class ProjectsView(MergeAPIView):
    """GET — «Мои склейки» (новые сверху); POST — новая склейка."""

    throttles = {"POST": WriteThrottle}

    def get(self, request):
        try:
            page = min(max(1, int(request.query_params.get("page") or 1)), 1000)
        except (TypeError, ValueError):
            page = 1
        start = (page - 1) * LIST_PAGE_SIZE
        rows = list(MergeProject.objects.filter(user=request.user)
                    .order_by("-updated_at", "-id")[start:start + LIST_PAGE_SIZE + 1])
        active = (MergeProject.objects.filter(user=request.user, status__in=MergeProject.ACTIVE)
                  .values_list("uid", flat=True).first())
        return Response({
            "results": [project_brief(p) for p in rows[:LIST_PAGE_SIZE]],
            "page": page,
            "has_more": len(rows) > LIST_PAGE_SIZE,
            "active_id": active,
            "price_credits": price_credits(),
            "limits": limits(),
        })

    def post(self, request):
        data = request.data if isinstance(request.data, dict) else {}
        lang = request_lang(request)
        try:
            project = services.create_project(request.user, data, lang=lang)
        except MergeError as exc:
            return _refusal(exc)
        live = services.live_sources(request.user, project, lang=lang)
        return Response(project_json(project, live=live, price=price_credits()),
                        status=http.HTTP_201_CREATED)


class ProjectDetailView(MergeAPIView):
    """GET (опрос), PATCH (правка списком целиком), DELETE <id>/."""

    throttles = {"PATCH": WriteThrottle, "DELETE": WriteThrottle}

    def get(self, request, uid):
        lang = request_lang(request)
        try:
            project = services.get_project(request.user, uid)
        except MergeError as exc:
            return _refusal(exc)
        live = services.live_sources(request.user, project, lang=lang)
        return Response(project_json(project, live=live, price=price_credits()))

    def patch(self, request, uid):
        data = request.data if isinstance(request.data, dict) else None
        lang = request_lang(request)
        if data is None:
            return _refusal(MergeError("bad_request", services.MSG_BAD_ITEMS))
        try:
            project = services.update_project(request.user, uid, data, lang=lang)
        except MergeError as exc:
            return _refusal(exc)
        live = services.live_sources(request.user, project, lang=lang)
        return Response(project_json(project, live=live, price=price_credits()))

    def delete(self, request, uid):
        try:
            services.delete_project(request.user, uid)
        except MergeError as exc:
            return _refusal(exc)
        return Response(status=http.HTTP_204_NO_CONTENT)


def take_upload_slot(user_id, prefix: str = "merge:upload", ttl: int = UPLOAD_SLOT_TTL) -> str | None:
    """Занять место загрузки человека: ключ, "" — кэш недоступен (грузим без
    учёта, как и скачивания), None — его загрузка уже идёт. prefix — своё место
    у треков звука (merge:audio-upload): видео и трек грузятся независимо; ttl —
    дольше самого долгого запроса, иначе место истекло бы посреди него."""
    key = f"{prefix}:{user_id}"
    try:
        return key if cache.add(key, 1, ttl) else None
    except Exception:
        logger.warning("склейка: место загрузки не проверилось", exc_info=True)
        return ""


def release_upload_slot(key: str) -> None:
    if not key:
        return
    try:
        cache.delete(key)
    except Exception:
        logger.warning("склейка: место загрузки не освободилось", exc_info=True)


def drain_body(request, limit: int = DRAIN_LIMIT) -> int:
    """Дочитать (и выбросить) тело запроса, которое отказ не разбирал. Байт прочитано."""
    raw = getattr(request, "_request", request)
    read = 0
    try:
        while read < limit:
            chunk = raw.read(min(DRAIN_CHUNK, limit - read))
            if not chunk:
                break
            read += len(chunk)
    except Exception:
        logger.info("склейка: тело отказа не дочиталось", exc_info=True)
    return read


class UploadsView(MergeAPIView):
    """GET uploads/ — свои видео («Мои файлы») и занятое место;
    POST uploads/ — загрузить своё видео (multipart, поле file) → 201 карточка."""

    parser_classes = [MultiPartParser]
    throttles = {"POST": UploadThrottle}

    def get(self, request):
        return Response(uploads.listing(request.user, lang=request_lang(request)))

    def post(self, request):
        lang = request_lang(request)
        slot = take_upload_slot(request.user.pk)
        if slot is None:
            return _refusal(MergeError("upload_busy", MSG_UPLOAD_BUSY, 429))
        try:
            # Размер и квота по числу файлов — до разбора тела: 90 МБ не пишем на диск зря.
            uploads.precheck(request.user, request.META.get("CONTENT_LENGTH"))
            row = uploads.accept(request.user, request.FILES.get("file"), lang=lang)
        except MergeError as exc:
            return _refusal(exc)
        finally:
            release_upload_slot(slot)
        return Response(uploads.card(row, lang), status=http.HTTP_201_CREATED)

    def finalize_response(self, request, response, *args, **kwargs):
        # Любой отказ загрузки (401 и 429 до самого метода, отказы precheck) —
        # тело дочитать: nginx его уже принял и отдаёт целиком.
        if str(getattr(request, "method", "")).upper() == "POST" and response.status_code >= 400:
            drain_body(request)
        return super().finalize_response(request, response, *args, **kwargs)


class UploadDetailView(MergeAPIView):
    """DELETE uploads/<id>/ — удалить своё видео (не во время его склейки)."""

    throttles = {"DELETE": WriteThrottle}

    def delete(self, request, uid):
        try:
            uploads.delete_upload(request.user, uid)
        except MergeError as exc:
            return _refusal(exc)
        return Response(status=http.HTTP_204_NO_CONTENT)


class RenderView(MergeAPIView):
    """POST <id>/render/ — запуск. 202 — поставлена; 200 — уже шла (повторный клик)."""

    throttles = {"POST": RenderThrottle}

    def post(self, request, uid):
        data = request.data if isinstance(request.data, dict) else {}
        lang = request_lang(request)
        try:
            project, started = services.start_render(request.user, uid, data, lang=lang)
        except MergeError as exc:
            return _refusal(exc)
        price = price_credits()
        body = project_json(project, price=price)
        body["balance"] = _balance(request.user, 0)
        return Response(body, status=http.HTTP_202_ACCEPTED if started else http.HTTP_200_OK)


def _slot_key(owner_id) -> str:
    return f"merge:download:{owner_id}"


def take_download_slot(owner_id) -> str | None:
    """Занять место скачивания владельца: ключ места, "" — счётчик недоступен
    (качаем без учёта), None — мест нет."""
    key = _slot_key(owner_id)
    try:
        cache.add(key, 0, DOWNLOAD_SLOT_TTL)
        taken = cache.incr(key)
        cache.touch(key, DOWNLOAD_SLOT_TTL)
    except Exception:
        logger.warning("склейка: счётчик скачиваний недоступен", exc_info=True)
        return ""
    if taken > DOWNLOAD_SLOTS:
        release_download_slot(key)
        return None
    return key


def release_download_slot(key: str) -> None:
    if not key:
        return
    try:
        if cache.decr(key) < 0:
            cache.set(key, 0, DOWNLOAD_SLOT_TTL)
    except ValueError:
        pass  # срок ключа вышел раньше — освобождать нечего
    except Exception:
        logger.warning("склейка: место скачивания не освободилось", exc_info=True)


class _SlotFileResponse(FileResponse):
    """Отдача файла, которая освобождает место скачивания, когда закрывается."""

    def __init__(self, *args, slot: str = "", **kwargs):
        self._slot = slot
        super().__init__(*args, **kwargs)

    def close(self):
        try:
            super().close()
        finally:
            slot, self._slot = self._slot, ""
            release_download_slot(slot)


class DownloadView(MergeAPIView):
    """GET <id>/download/ — mp4 вложением, только владельцу.

    Владелец — по токену входа (Authorization) или по подписанной ссылке
    ?t=… из download_url: обычная ссылка <a href> заголовок не несёт.
    Кнопка «Скачать» на странице берёт сам файл из /media/ (его отдаёт nginx),
    сюда приходят переходы по download_url.

    Нагрузка. Ролик — до ~150 МБ, а потоков у API на весь сайт 24 (3 воркера
    gunicorn по 8). Поэтому отдача просит nginx буферизовать (иначе поток
    держится всё скачивание, см. ниже), и у одного владельца не больше
    DOWNLOAD_SLOTS отдач разом: страховка, если буфер nginx не сработал.
    """

    permission_classes = [AllowAny]
    throttles = {"GET": DownloadThrottle}

    def get(self, request, uid):
        user = request.user if request.user and request.user.is_authenticated else None
        uid = str(uid or "").lower()
        if user is not None:
            project = MergeProject.objects.filter(user=user, uid=uid).first()
        else:
            token = request.query_params.get("t")
            if not token:
                return Response(error_body("unauthorized"), status=http.HTTP_401_UNAUTHORIZED)
            owner = services.token_user_id(token, uid)
            project = (MergeProject.objects.filter(user_id=owner, uid=uid).first()
                       if owner else None)
        if project is None:
            return _refusal(MergeError("project_not_found", services.MSG_NOT_FOUND, 404))
        if project.status != MergeProject.STATUS_READY or not project.result_video:
            return _refusal(MergeError("not_ready", services.MSG_NOT_READY, 409))
        slot = take_download_slot(project.user_id)
        if slot is None:
            return _refusal(MergeError("downloads_busy", MSG_DOWNLOADS_BUSY, 429,
                                       max=DOWNLOAD_SLOTS))
        try:
            handle = default_storage.open(project.result_video, "rb")
        except (FileNotFoundError, OSError):
            release_download_slot(slot)
            logger.error("склейка %s: файл %s не открылся", project.uid, project.result_video)
            return _refusal(MergeError("file_missing", services.MSG_FILE_GONE, 410))
        response = _SlotFileResponse(handle, slot=slot, as_attachment=True,
                                     filename=services.download_name(project), content_type="video/mp4")
        response["Cache-Control"] = "private, no-store"
        # /api/ в nginx идёт без буфера (ради потокового ответа чата), и тогда
        # поток gunicorn держится, пока телефон тянет весь ролик — минуты. С
        # этим заголовком nginx сам дочитывает файл к себе и отпускает поток
        # примерно за секунду. Без nginx заголовок ничего не делает.
        response["X-Accel-Buffering"] = "yes"
        return response


class ManageSettingsView(APIView):
    """GET / PATCH manage/settings/ — цена склейки для карточки в «Настройках» админки.

    {"price_credits": 25} — своя цена (0 — бесплатно); null или "" — вернуть
    цену из кода (20). Только сотрудники; правка пишется в журнал действий.
    """

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsStaff]

    @staticmethod
    def _payload() -> dict:
        from adminapi.runtime import get_runtime

        stored = get_runtime(PRICE_KEY, "")
        return {"price_credits": price_credits(), "default_price_credits": DEFAULT_PRICE,
                "overridden": stored not in ("", None)}

    def get(self, request):
        return Response(self._payload())

    def patch(self, request):
        from adminapi.runtime import delete_runtime, set_runtime
        from audit.services import log_admin_action

        data = request.data if isinstance(request.data, dict) else {}
        if "price_credits" not in data:
            return Response({"detail": "Нечего сохранять: пришлите price_credits"},
                            status=http.HTTP_400_BAD_REQUEST)
        raw = data["price_credits"]
        value = None
        if not (raw is None or (isinstance(raw, str) and not raw.strip())):
            # Только целое: «12.5» или true в цене — ошибка формы, а не 12 или 1.
            if isinstance(raw, int) and not isinstance(raw, bool):
                value = raw
            elif isinstance(raw, str) and raw.strip().isdigit():
                value = int(raw.strip())
            if value is None or not 0 <= value <= MAX_PRICE:
                text = f"Цена склейки — целое число от 0 до {MAX_PRICE}"
                return Response({"detail": text, "errors": {"price_credits": text}},
                                status=http.HTTP_400_BAD_REQUEST)
        before = price_credits()
        with transaction.atomic():
            if value is None:
                delete_runtime(PRICE_KEY)
            else:
                set_runtime(PRICE_KEY, value)
            after = value if value is not None else DEFAULT_PRICE
            if after != before:
                log_admin_action(request.user, "settings.edit",
                                 before={PRICE_KEY: before}, after={PRICE_KEY: after},
                                 request=request)
        return Response(self._payload())
