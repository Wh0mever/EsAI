"""Голос и долгие генерации: то, чего сайту не нужно, а боту — необходимо.

Оба эндпоинта пользовательские (JWT), а не сервисные: списания идут от
имени человека и попадают в его историю точно так же, как из чата.
"""
from __future__ import annotations

import logging
import math
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle, UserRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication

from plans.tiers import can_use_model
from plans.wallet import InsufficientTokens, available_tokens, charge_tokens

from . import stt
from .models import AiChatMessage, AiChatSession, GenerationJob

logger = logging.getLogger(__name__)


class TranscribeAPIView(APIView):
    """POST /api/ai/transcribe/ — голосовое → текст.

    multipart: file, lang. Цена известна до вызова модели, поэтому нехватка
    кредитов отбивается сразу (402), а списание идёт только за успех.
    """

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "stt"

    def post(self, request):
        upload = request.FILES.get("file")
        if not upload:
            return Response({"detail": "no_file"}, status=status.HTTP_400_BAD_REQUEST)
        size = int(getattr(upload, "size", 0) or 0)
        if size > stt.max_bytes():
            return Response({"detail": "file_too_big", "max_bytes": stt.max_bytes()},
                            status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
        lang = str(request.data.get("lang") or "ru")[:5]

        try:
            mp3, seconds, volume = stt.convert_to_mp3(upload.read())
        except stt.SttError as exc:
            logger.warning("stt: конвертация не удалась: %s", exc)
            return Response({"detail": "bad_audio"}, status=status.HTTP_400_BAD_REQUEST)
        if seconds > stt.max_seconds():
            return Response({"detail": "too_long", "max_seconds": stt.max_seconds(),
                             "seconds": round(seconds, 1)},
                            status=status.HTTP_400_BAD_REQUEST)
        if stt.is_silent(volume, seconds):
            # Тишину модели не показываем: она выдумает текст, а человек заплатит.
            return Response({"text": "", "seconds": round(seconds, 1), "tokens_charged": 0,
                             "balance_tokens": int(getattr(request.user, "token_balance", 0) or 0),
                             "silent": True})

        price = stt.price_for(seconds)
        try:
            request.user.refresh_from_db(fields=["token_balance"])
        except Exception:
            pass
        balance = int(getattr(request.user, "token_balance", 0) or 0)
        # Свободный остаток: кредиты, обещанные идущим генерациям (видео чата,
        # сцены мультстудии, дубли видеостудии), на распознавание не тратятся.
        free = available_tokens(request.user, balance)
        if free < price:
            return Response({
                "error": "Недостаточно кредитов для распознавания.",
                "error_code": "insufficient_balance",
                "balance_tokens": free,
                "required_estimate": price,
            }, status=status.HTTP_402_PAYMENT_REQUIRED)

        try:
            text = stt.transcribe_audio(mp3, lang=lang)
        except stt.SttError as exc:
            logger.warning("stt: распознавание не удалось: %s", exc)
            return Response({"detail": "stt_failed"}, status=status.HTTP_502_BAD_GATEWAY)

        charged = 0
        if text and price > 0:
            try:
                balance = charge_tokens(request.user, price, "stt",
                                        meta={"seconds": round(seconds, 1),
                                              "model": stt.model_id()},
                                        respect_reserves=True)
                charged = price
            except InsufficientTokens as exc:
                # Баланс изменился, пока модель слушала: берём что осталось
                # (свободного — резервы идущих генераций не трогаем).
                balance = exc.total
                if exc.balance > 0:
                    balance = charge_tokens(request.user, exc.balance, "stt",
                                            meta={"seconds": round(seconds, 1),
                                                  "partial": True},
                                            respect_reserves=True)
                    charged = exc.balance
        return Response({
            "text": text,
            "seconds": round(seconds, 1),
            "tokens_charged": charged,
            "balance_tokens": balance,
        })


# ------------------------------------------------------------------ jobs ---

def _cancel_key(job_uid: str) -> str:
    return f"ai:job:cancel:{job_uid}"


# Дольше этого задача не живёт: у run_generation_job time_limit=900 с, и запас
# сверху — на ожидание в очереди и на то, что воркер добивает хвосты.
JOB_STALE_AFTER = 1800


def _worker_gone(job) -> bool:
    """Воркера у задачи больше нет: она старше жёсткого лимита времени.

    Пока задача моложе срока, за неё отвечает живой воркер — он и закроет её,
    и вернёт слот дневного лимита сам (generation.py). Дальше этого срока
    возвращаться некому: прежний прогон убит по time_limit или перезапуском.
    """
    return (job.started_at or job.created_at) <= timezone.now() - timedelta(seconds=JOB_STALE_AFTER)


def _expire_stale_jobs(user) -> int:
    """Закрыть задачи, чей воркер уже не вернётся, и вернуть их слот лимита.

    Воркера могли перезапустить посреди генерации — тогда задача навсегда
    остаётся в running, а замок «один ролик за раз» отвечает 409 на КАЖДУЮ
    следующую попытку: завершить её больше некому. Слот дневного лимита при
    этом тоже висит зарезервированным, хотя ролика человек не получил.
    """
    from .handlers import _release_daily_request

    closed = 0
    for job in GenerationJob.objects.filter(user=user, status__in=GenerationJob.ACTIVE_STATES):
        if not _worker_gone(job):
            continue
        # Условие по статусу в самом UPDATE: воркер мог закрыть задачу сам,
        # пока мы её осматривали, — его итог затирать нельзя.
        if GenerationJob.objects.filter(
                pk=job.pk, status__in=GenerationJob.ACTIVE_STATES).update(
                status=GenerationJob.STATUS_FAILED, error="job_stale",
                error_code="job_stale", finished_at=timezone.now()):
            _release_daily_request(user)
            closed += 1
    return closed


class GenerationJobCreateView(APIView):
    """POST /api/ai/jobs/ — поставить видео в очередь.

    Тело — как у чата (message, model, session_id, attachments, video_*),
    плюс notify: "telegram", если результат нужно прислать в бот. Все гейты
    чата повторяются здесь ДО постановки: премиум-лок, точная цена, дневной
    лимит. Ответ 202 с id задачи; результат — GET /api/ai/jobs/<id>/.
    """

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]
    throttle_classes = [UserRateThrottle]

    def post(self, request):
        from .handlers import (
            _openrouter_config,
            _premium_locked_error,
            _release_daily_request,
            _reserve_daily_request,
            _resolve_gpt_model,
            _video_model_params,
        )

        data = request.data or {}
        user = request.user
        kind = str(data.get("kind") or GenerationJob.KIND_VIDEO)
        if kind != GenerationJob.KIND_VIDEO:
            return Response({"detail": "unsupported_kind"}, status=status.HTTP_400_BAD_REQUEST)

        message = str(data.get("message") or "").strip()
        if not message:
            return Response({"error": "No message provided"}, status=status.HTTP_400_BAD_REQUEST)

        model_obj = _resolve_gpt_model(data.get("model"))
        if not model_obj or getattr(model_obj, "category", "") != "video":
            return Response({"error": "video_model_required", "error_code": "bad_model"},
                            status=status.HTTP_400_BAD_REQUEST)
        if not can_use_model(user, model_obj):
            payload = _premium_locked_error()
            return Response(payload, status=int(payload.pop("http_status", 403) or 403))
        selected = (model_obj.openrouter_id or model_obj.name or "").strip()
        if not selected:
            return Response({"error": "model_misconfigured"}, status=status.HTTP_400_BAD_REQUEST)
        if not _openrouter_config().get("api_key"):
            return Response({"error": "OpenRouter is not configured"},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)

        # Один ролик за раз: параллельные генерации путают человека и
        # съедают баланс быстрее, чем он успевает это заметить. Но «за раз»
        # считается только среди живых задач — зависшую сначала закрываем,
        # иначе она заблокировала бы видео навсегда.
        _expire_stale_jobs(user)
        if GenerationJob.objects.filter(user=user, status__in=GenerationJob.ACTIVE_STATES).exists():
            return Response({"detail": "job_in_progress", "error_code": "job_in_progress"},
                            status=status.HTTP_409_CONFLICT)

        # Точная цена известна заранее — считаем её той же функцией, что и генерация.
        try:
            want_duration = int(data.get("video_duration") or 0) or None
        except (TypeError, ValueError):
            want_duration = None
        want_resolution = str(data.get("video_resolution") or "").strip() or None
        try:
            params = _video_model_params(
                selected, _openrouter_config(),
                want_duration or int(getattr(settings, "VIDEO_GEN_DURATION", 5) or 5),
                want_resolution or str(getattr(settings, "VIDEO_GEN_RESOLUTION", "720p")),
            )
            duration = int(params["duration"])
            resolution = str(params["resolution"])
        except Exception:
            duration = want_duration or int(getattr(settings, "VIDEO_GEN_DURATION", 5) or 5)
            resolution = want_resolution or str(getattr(settings, "VIDEO_GEN_RESOLUTION", "720p"))
        # Та же цена, что спишет генерация: с разрешением и не ниже себестоимости.
        from .handlers import _openrouter_video_catalog
        from .video_cost import video_credits

        try:
            spec = _openrouter_video_catalog(selected)
        except Exception:
            spec = {}
        try:
            from .aspect import resolve as _resolve_aspect

            price_ar = _resolve_aspect(str(data.get("aspect_ratio") or "").strip() or None,
                                       str(data.get("message") or ""),
                                       (spec or {}).get("supported_aspect_ratios") or [])
        except Exception:
            price_ar = None
        frames = (1 if str(data.get("video_first_frame") or "").strip() else 0) +             (1 if str(data.get("video_last_frame") or "").strip() else 0)
        from .pricing import PriceUnavailable

        try:
            need = video_credits(model_obj, spec, resolution, duration, images=frames, aspect=price_ar)
        except PriceUnavailable as exc:
            # Режим наценки без себестоимости: в очередь не ставим, тариф не подставляем.
            return Response(exc.payload(), status=status.HTTP_503_SERVICE_UNAVAILABLE)

        try:
            user.refresh_from_db(fields=["token_balance"])
        except Exception:
            pass
        balance = int(getattr(user, "token_balance", 0) or 0)
        # Ролики «снимается дольше» (задача delayed) ещё не списаны, но спишутся
        # при довозе — их цену вычитаем, как и в самой генерации.
        from vstudio.reserve import vstudio_reserved  # и дубли видеостудии в работе

        from .generation import reserved_video_credits, video_balance_error

        refusal = video_balance_error(balance, reserved_video_credits(user) + vstudio_reserved(user), need)
        if refusal:
            return Response(refusal, status=status.HTTP_402_PAYMENT_REQUIRED)

        allowed, _used, limit = _reserve_daily_request(user)
        if not allowed:
            return Response({
                "error": "Достигнут дневной лимит запросов.",
                "error_code": "daily_limit_reached",
                "limit": limit,
            }, status=status.HTTP_429_TOO_MANY_REQUESTS)

        attachments = data.get("attachments")
        attachments = attachments if isinstance(attachments, list) else None
        session_ref = data.get("session_id") or data.get("chat_id")
        try:
            with transaction.atomic():
                session = None
                if session_ref:
                    from .handlers import _resolve_session_for_user

                    session = _resolve_session_for_user(user, session_ref, for_update=True)
                    if not session:
                        _release_daily_request(user)
                        return Response({"error": "Session not found"},
                                        status=status.HTTP_404_NOT_FOUND)
                else:
                    session = AiChatSession.objects.create(
                        user=user, title=message[:60] or "New Chat", chat_mode="text-chat")
                AiChatMessage.objects.create(session=session, role="user", content=message,
                                             attachments=attachments)
                proto = request.headers.get("X-Forwarded-Proto") or (
                    "https" if request.is_secure() else "http")
                host = request.get_host() or ""
                job = GenerationJob.objects.create(
                    user=user, session=session, kind=kind, need_credits=need,
                    notify=str(data.get("notify") or "")[:16],
                    params={
                        "model": selected,
                        "model_pk": model_obj.pk,
                        "message": message,
                        "attachments": attachments,
                        "origin_base": f"{proto}://{host}" if host else None,
                        "video_duration": want_duration,
                        "video_resolution": want_resolution,
                        "aspect_ratio": str(data.get("aspect_ratio") or "").strip() or None,
                        "video_first_frame": str(data.get("video_first_frame") or "").strip() or None,
                        "video_last_frame": str(data.get("video_last_frame") or "").strip() or None,
                        "extend_video_url": str(data.get("extend_video_url") or "").strip() or None,
                        "lang": str(data.get("lang") or "ru")[:5],
                    },
                )
        except Exception:
            logger.exception("job create failed")
            _release_daily_request(user)
            return Response({"error": "internal_error"},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        from .tasks import run_generation_job

        job_pk = job.pk

        def _enqueue() -> None:
            # Ставим в очередь только ПОСЛЕ коммита: запрос целиком живёт в
            # транзакции (ATOMIC_REQUESTS), и воркер, взявший задачу раньше
            # коммита, не находил её в базе («no_job») — ролик не снимался,
            # а слот дневного лимита оставался занятым.
            try:
                queue = getattr(settings, "CELERY_MEDIA_QUEUE", "") or None
                async_result = run_generation_job.apply_async(
                    args=[job_pk], **({"queue": queue} if queue else {}))
                GenerationJob.objects.filter(pk=job_pk).update(
                    celery_task_id=str(async_result.id or ""))
            except Exception:
                logger.exception("job enqueue failed")
                # Задача уже в базе: закрываем её, бот увидит failed при опросе.
                if GenerationJob.objects.filter(
                        pk=job_pk, status=GenerationJob.STATUS_QUEUED).update(
                        status=GenerationJob.STATUS_FAILED, error="queue_unavailable",
                        error_code="queue_unavailable", finished_at=timezone.now()):
                    _release_daily_request(user)

        transaction.on_commit(_enqueue)

        return Response({**job.public(), "duration": duration, "eta_seconds": 150},
                        status=status.HTTP_202_ACCEPTED)


class GenerationJobDetailView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, uid: str):
        job = GenerationJob.objects.filter(uid=uid, user=request.user).select_related("session").first()
        if not job:
            return Response({"detail": "not_found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(job.public())


class GenerationJobCancelView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, uid: str):
        from .handlers import _release_daily_request

        job = GenerationJob.objects.filter(uid=uid, user=request.user).first()
        if not job:
            return Response({"detail": "not_found"}, status=status.HTTP_404_NOT_FOUND)
        if not job.is_active:
            return Response(job.public())
        cache.set(_cancel_key(job.uid), "1", 3600)
        # Слот дневного лимита возвращаем только там, где вернуть его больше
        # некому: задачу из очереди воркер пропустит по статусу, а у зависшей
        # воркера уже нет. Живая running-задача вернёт слот сама, увидев флаг
        # отмены (generation.py), — сделай это ещё и здесь, и человек получал
        # бы за каждую отмену лишний запрос сверх дневного лимита.
        refund = job.status == GenerationJob.STATUS_QUEUED or _worker_gone(job)
        # Закрываем задачу сразу, не дожидаясь воркера. Очередь её пропустит по
        # статусу, а начатую остановит флаг отмены выше. Ждать было нельзя:
        # пока задача числится активной, следующий запуск получает 409, и
        # «Отменить» не отменяет ничего — а у running-задачи воркера может уже
        # и не быть.
        if GenerationJob.objects.filter(
                pk=job.pk, status__in=GenerationJob.ACTIVE_STATES).update(
                status=GenerationJob.STATUS_CANCELED, finished_at=timezone.now(),
                error_code="canceled") and refund:
            _release_daily_request(request.user)
        job.refresh_from_db()
        return Response(job.public())


class GenerationJobListView(APIView):
    """GET /api/ai/jobs/ — последние задачи человека (активная — первой)."""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        rows = (GenerationJob.objects.filter(user=request.user)
                .select_related("session").order_by("-created_at")[:10])
        return Response([j.public() for j in rows])
