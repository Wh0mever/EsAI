"""API звука склейки (Build MA): /api/merge/<id>/audio/… — только владельцу.

  GET    <id>/audio/                — дорожки, звук роликов, громкости, цены, пределы, включена ли озвучка
  PATCH  <id>/audio/                — {clip_sound, music_volume, voice_volume, voice_start_fragment}
  POST   <id>/audio/voice/          — голос за кадром {text, voice_id, start_fragment, price?, request_id?}
  POST   <id>/audio/music/          — музыка по описанию {prompt, price?, request_id?}: 202, делает задача
  POST   <id>/audio/music/upload/   — свой трек (multipart, поле file), бесплатно
  DELETE <id>/audio/<track_id>/     — убрать дорожку
Голоса и их примеры — общие с мультстудией: /api/cartoon/audio/voices/ и
/api/cartoon/audio/voices/<id>/preview/. Тело отказа — как во всей склейке:
{"error": "<по-русски>", "error_code": "<код>", …}; контракт — CONTRACT_M.md §10.
"""
from __future__ import annotations

from django.db import transaction
from django.utils.decorators import method_decorator
from rest_framework import status as http
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from . import audio, services
from .services import MergeError
from .views import (MergeAPIView, WriteThrottle, _balance, _refusal, drain_body, release_upload_slot,
                    take_upload_slot)

MSG_UPLOAD_BUSY = "Уже загружается другой трек — дождитесь окончания."
# Место загрузки трека живёт дольше самого долгого запроса: строгий разбор (20 с)
# + пересборка save_audio (до 180 с) + её проверка (до 60 с). С прежними 120 с
# место истекало посреди запроса, и человек запускал второй рядом с первым.
AUDIO_UPLOAD_SLOT_TTL = 6 * 60


class AudioThrottle(UserRateThrottle):
    # Каждый заказ — платный вызов ElevenLabs; двойной клик ловит audio_busy.
    scope = "merge_audio"
    rate = "10/min"


class AudioUploadThrottle(UserRateThrottle):
    # Как свои видео: файл до 20 МБ на диск и разбор ffmpeg на двух ядрах.
    scope = "merge_audio_upload"
    rate = "20/hour"


def _state(user, uid, track=None, *, balance: bool = False) -> dict:
    body = audio.state(services.get_project(user, uid))
    if isinstance(track, dict):
        # Повтор заказа, чью дорожку уже заменили или убрали: какой она ушла (audio._remove).
        body["track"] = track
    elif track is not None:
        track.refresh_from_db()
        body["track"] = audio.track_json(track, body["fragments"])
    if balance:
        body["balance"] = _balance(user, 0)
    return body


class AudioView(MergeAPIView):
    """GET — всё о звуке склейки; PATCH — звук роликов, громкости, фрагмент голоса."""

    throttles = {"PATCH": WriteThrottle}

    def get(self, request, uid):
        try:
            return Response(_state(request.user, uid))
        except MergeError as exc:
            return _refusal(exc)

    def patch(self, request, uid):
        try:
            audio.update_settings(request.user, uid, request.data)
            return Response(_state(request.user, uid))
        except MergeError as exc:
            return _refusal(exc)


# Голос делается в самом запросе: вне транзакции запроса резерв виден всем гейтам
# сразу, а вызов провайдера не держит ни транзакцию, ни замок строки пользователя.
@method_decorator(transaction.non_atomic_requests, name="dispatch")
class VoiceView(MergeAPIView):
    """POST — голос за кадром. 201 — сделан и оплачен; 200 — тот же request_id уже был."""

    throttles = {"POST": AudioThrottle}

    def post(self, request, uid):
        try:
            row, created = audio.generate_voice(request.user, uid, request.data)
            body = _state(request.user, uid, row, balance=True)
        except MergeError as exc:
            return _refusal(exc)
        return Response(body, status=http.HTTP_201_CREATED if created else http.HTTP_200_OK)


class MusicView(MergeAPIView):
    """POST — музыка по описанию. 202 — заказ в резерве, музыку делает задача
    (опрашивайте GET audio/); 200 — тот же request_id уже был."""

    throttles = {"POST": AudioThrottle}

    def post(self, request, uid):
        try:
            row, created = audio.queue_music(request.user, uid, request.data)
            body = _state(request.user, uid, row, balance=True)
        except MergeError as exc:
            return _refusal(exc)
        return Response(body, status=http.HTTP_202_ACCEPTED if created else http.HTTP_200_OK)


@method_decorator(transaction.non_atomic_requests, name="dispatch")
class MusicUploadView(MergeAPIView):
    """POST — свой трек вместо музыки (multipart, поле file) → 201. Бесплатно."""

    parser_classes = [MultiPartParser]
    throttles = {"POST": AudioUploadThrottle}

    def post(self, request, uid):
        slot = take_upload_slot(request.user.pk, prefix="merge:audio-upload", ttl=AUDIO_UPLOAD_SLOT_TTL)
        if slot is None:
            return _refusal(MergeError("audio_upload_busy", MSG_UPLOAD_BUSY, 429))
        try:
            # Размер — до разбора тела: 20 МБ не пишем на диск зря.
            audio.precheck(request.META.get("CONTENT_LENGTH"))
            row = audio.upload_music(request.user, uid, request.FILES.get("file"))
            body = _state(request.user, uid, row)
        except MergeError as exc:
            return _refusal(exc)
        finally:
            release_upload_slot(slot)
        return Response(body, status=http.HTTP_201_CREATED)

    def finalize_response(self, request, response, *args, **kwargs):
        # Отказ до разбора тела (401, 429, размер) — тело всё равно дочитать: nginx его
        # уже принял, и без этого вместо нашего ответа человек получил бы 502.
        if str(getattr(request, "method", "")).upper() == "POST" and response.status_code >= 400:
            drain_body(request)
        return super().finalize_response(request, response, *args, **kwargs)


class TrackView(MergeAPIView):
    """DELETE — убрать дорожку (не ту, что ещё делается) → 200 и состояние звука."""

    throttles = {"DELETE": WriteThrottle}

    def delete(self, request, uid, track):
        try:
            audio.delete_track(request.user, uid, track)
            return Response(_state(request.user, uid))
        except MergeError as exc:
            return _refusal(exc)
