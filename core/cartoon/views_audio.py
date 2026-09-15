"""API звука студии: дорожки сцены, генерация, загрузка своего голоса, сведение.

  GET    audio/config/              — включена ли озвучка, цены и ограничения
  GET    audio/voices/              — готовые голоса
  GET    scenes/<id>/audio/         — дорожки сцены
  PATCH  scenes/<id>/audio/         — громкость звука самой сцены
  POST   scenes/<id>/audio/voice/   — ИИ-реплика {text, voice_id, character_id}
  POST   scenes/<id>/audio/music/   — музыка {prompt, seconds}
  POST   scenes/<id>/audio/sfx/     — звуковой эффект {prompt, seconds?}
  POST   scenes/<id>/audio/upload/  — свой голос файлом или с диктофона
  POST   scenes/<id>/audio/mix/     — свести дорожки с видео сцены
  PATCH  audio/<id>/                — момент начала и громкость дорожки
  DELETE audio/<id>/
"""
from __future__ import annotations

import logging

from django.core.cache import cache
from django.core.files.storage import default_storage
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from . import audio
from .models import CartoonAudioTrack, CartoonScene
from .views import StudioAPIView, StudioPublicAPIView, _no_credits, _pick_character

logger = logging.getLogger(__name__)


def _url(path: str) -> str:
    return default_storage.url(path) if path else ""


def track_json(t: CartoonAudioTrack) -> dict:
    return {
        "id": t.pk,
        "kind": t.kind,
        "text": t.text,
        "voice_id": t.voice_id,
        "voice_name": t.voice_name,
        "character": ({"id": t.character_id, "name": t.character.name} if t.character_id else None),
        "file": _url(t.file),
        "duration": t.duration,
        "start_sec": t.start_sec,
        "volume": t.volume,
        "credits_spent": t.credits_spent,
    }


def _scene_audio_json(scene) -> dict:
    return {
        "scene_id": scene.pk,
        "sound_volume": scene.sound_volume,
        "has_video": bool(scene.video),
        "mixed_video": _url(scene.mixed_video),
        "tracks": [track_json(t) for t in scene.audio_tracks.select_related("character").order_by("start_sec", "id")],
    }


def _my_scene(request, pk):
    return get_object_or_404(CartoonScene.objects.select_related("project", "character", "project__character"),
                             pk=pk, project__user=request.user)


def _need_config():
    if not audio.is_configured():
        return Response({"detail": "Озвучка пока не подключена"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    return None


def _balance(user) -> int:
    return int(getattr(user, "token_balance", 0) or 0)


def _start_and_volume(data) -> tuple[float, float]:
    try:
        start = max(0.0, min(600.0, float(data.get("start_sec") or 0)))
    except (TypeError, ValueError):
        start = 0.0
    try:
        volume = float(data.get("volume") if data.get("volume") is not None else 1.0)
    except (TypeError, ValueError):
        volume = 1.0
    return start, max(audio.VOLUME_MIN, min(audio.VOLUME_MAX, volume))


def _generate(request, scene, *, kind, price, reason, make, text="", voice_id="", voice_name="",
              character=None, meta=None):
    """Сгенерировать звук, сохранить и только потом списать."""
    from plans.wallet import InsufficientTokens

    from .services import charge

    if _balance(request.user) < price:
        return _no_credits(price, _balance(request.user))
    lock = f"studio:audio:{request.user.pk}"
    if not cache.add(lock, "1", timeout=180):
        return Response({"detail": "Предыдущий звук ещё делается — подождите пару секунд"},
                        status=status.HTTP_429_TOO_MANY_REQUESTS)
    try:
        try:
            raw = make()
            path, duration = audio.save_audio(raw)
        except audio.AudioNotConfigured:
            return Response({"detail": "Озвучка пока не подключена"},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except Exception as exc:
            logger.exception("звук студии (%s): генерация не удалась", kind)
            return Response({"detail": "Не получилось сделать звук — попробуйте ещё раз",
                             "error": str(exc)[:200]}, status=status.HTTP_502_BAD_GATEWAY)
        try:
            charge(request.user, price, reason, meta={"scene": scene.pk, "kind": kind, **(meta or {})})
        except InsufficientTokens:
            default_storage.delete(path)
            return _no_credits(price, _balance(request.user))
        start, volume = _start_and_volume(request.data or {})
        track = CartoonAudioTrack.objects.create(
            scene=scene, kind=kind, character=character, voice_id=voice_id, voice_name=voice_name,
            text=text, file=path, duration=duration, start_sec=start, volume=volume, credits_spent=price)
    finally:
        cache.delete(lock)
    return Response(track_json(track), status=status.HTTP_201_CREATED)


class AudioConfigView(StudioPublicAPIView):
    def get(self, request):
        return Response({
            "enabled": audio.is_configured(),
            "prices": audio.prices(),
            "limits": {"voice_chars": audio.MAX_VOICE_CHARS,
                       "music_sec": [audio.MUSIC_MIN_SEC, audio.MUSIC_MAX_SEC],
                       "sfx_sec": [audio.SFX_MIN_SEC, audio.SFX_MAX_SEC],
                       "upload_mb": audio.UPLOAD_MAX_BYTES // (1024 * 1024)},
        })


class VoicesView(StudioPublicAPIView):
    def get(self, request):
        try:
            return Response(audio.list_voices())
        except Exception:
            logger.exception("голоса ElevenLabs не загрузились")
            return Response([])


class SceneAudioView(StudioAPIView):
    def get(self, request, pk):
        return Response(_scene_audio_json(_my_scene(request, pk)))

    def patch(self, request, pk):
        scene = _my_scene(request, pk)
        if "sound_volume" in (request.data or {}):
            _, volume = _start_and_volume({"volume": request.data.get("sound_volume")})
            scene.sound_volume = volume
            scene.save(update_fields=["sound_volume", "updated_at"])
        return Response(_scene_audio_json(scene))


class SceneVoiceView(StudioAPIView):
    def post(self, request, pk):
        if (resp := _need_config()):
            return resp
        scene = _my_scene(request, pk)
        text = " ".join(str((request.data or {}).get("text") or "").split())
        voice_id = str((request.data or {}).get("voice_id") or "").strip()[:64]
        if len(text) < 1:
            return Response({"detail": "Напишите текст реплики"}, status=status.HTTP_400_BAD_REQUEST)
        if len(text) > audio.MAX_VOICE_CHARS:
            return Response({"detail": f"Реплика длиннее {audio.MAX_VOICE_CHARS} символов"},
                            status=status.HTTP_400_BAD_REQUEST)
        if not voice_id:
            return Response({"detail": "Выберите голос"}, status=status.HTTP_400_BAD_REQUEST)
        voice_name = next((v["name"] for v in (audio.list_voices() or []) if v["id"] == voice_id), "")
        character = _pick_character(request, (request.data or {}).get("character_id"))
        return _generate(request, scene, kind=CartoonAudioTrack.KIND_VOICE, price=audio.voice_price(text),
                         reason="cartoon_voice", make=lambda: audio.tts(text, voice_id), text=text,
                         voice_id=voice_id, voice_name=voice_name, character=character,
                         meta={"chars": len(text)})


class SceneMusicView(StudioAPIView):
    def post(self, request, pk):
        if (resp := _need_config()):
            return resp
        scene = _my_scene(request, pk)
        prompt = " ".join(str((request.data or {}).get("prompt") or "").split())[:400]
        try:
            seconds = float((request.data or {}).get("seconds") or 0)
        except (TypeError, ValueError):
            seconds = 0
        if len(prompt) < 3:
            return Response({"detail": "Опишите музыку хотя бы парой слов"}, status=status.HTTP_400_BAD_REQUEST)
        if not (audio.MUSIC_MIN_SEC <= seconds <= audio.MUSIC_MAX_SEC):
            return Response({"detail": f"Длительность — от {audio.MUSIC_MIN_SEC} до {audio.MUSIC_MAX_SEC} секунд"},
                            status=status.HTTP_400_BAD_REQUEST)
        return _generate(request, scene, kind=CartoonAudioTrack.KIND_MUSIC, price=audio.music_price(seconds),
                         reason="cartoon_music", make=lambda: audio.music(prompt, seconds), text=prompt,
                         meta={"seconds": seconds})


class SceneSfxView(StudioAPIView):
    def post(self, request, pk):
        if (resp := _need_config()):
            return resp
        scene = _my_scene(request, pk)
        prompt = " ".join(str((request.data or {}).get("prompt") or "").split())[:300]
        raw_sec = (request.data or {}).get("seconds")
        seconds = None
        if raw_sec not in (None, ""):
            try:
                seconds = float(raw_sec)
            except (TypeError, ValueError):
                seconds = None
            if seconds is not None and not (audio.SFX_MIN_SEC <= seconds <= audio.SFX_MAX_SEC):
                return Response({"detail": f"Длительность эффекта — от {audio.SFX_MIN_SEC} до {audio.SFX_MAX_SEC} с"},
                                status=status.HTTP_400_BAD_REQUEST)
        if len(prompt) < 3:
            return Response({"detail": "Опишите звук хотя бы парой слов"}, status=status.HTTP_400_BAD_REQUEST)
        return _generate(request, scene, kind=CartoonAudioTrack.KIND_SFX, price=audio.sfx_price(),
                         reason="cartoon_sfx", make=lambda: audio.sound_effect(prompt, seconds), text=prompt)


class SceneUploadAudioView(StudioAPIView):
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request, pk):
        scene = _my_scene(request, pk)
        upload = request.FILES.get("file")
        if not upload:
            return Response({"detail": "Выберите или запишите звук"}, status=status.HTTP_400_BAD_REQUEST)
        if upload.size > audio.UPLOAD_MAX_BYTES:
            return Response({"detail": f"Файл больше {audio.UPLOAD_MAX_BYTES // (1024 * 1024)} МБ"},
                            status=status.HTTP_400_BAD_REQUEST)
        name = (upload.name or "").lower()
        suffix = "." + name.rsplit(".", 1)[-1] if "." in name else ".bin"
        try:
            path, duration = audio.save_audio(upload.read(), suffix=suffix[:8])
        except Exception:
            logger.exception("свой голос: файл не прочитался")
            return Response({"detail": "Не получилось прочитать запись — попробуйте другой файл"},
                            status=status.HTTP_400_BAD_REQUEST)
        start, volume = _start_and_volume(request.data or {})
        character = _pick_character(request, (request.data or {}).get("character_id"))
        track = CartoonAudioTrack.objects.create(
            scene=scene, kind=CartoonAudioTrack.KIND_OWN, character=character,
            text=str((request.data or {}).get("label") or "")[:200], file=path, duration=duration,
            start_sec=start, volume=volume)
        return Response(track_json(track), status=status.HTTP_201_CREATED)


class SceneMixView(StudioAPIView):
    def post(self, request, pk):
        scene = _my_scene(request, pk)
        if not scene.video:
            return Response(_scene_audio_json(scene))
        lock = f"studio:mix:{scene.pk}"
        if not cache.add(lock, "1", timeout=120):
            return Response({"detail": "Сцена уже сводится"}, status=status.HTTP_429_TOO_MANY_REQUESTS)
        try:
            audio.remix_scene(scene)
        except Exception:
            logger.exception("сведение сцены %s не удалось", scene.pk)
            return Response({"detail": "Не получилось свести звук со сценой"},
                            status=status.HTTP_502_BAD_GATEWAY)
        finally:
            cache.delete(lock)
        return Response(_scene_audio_json(scene))


class AudioTrackDetailView(StudioAPIView):
    def _track(self, request, pk):
        return get_object_or_404(CartoonAudioTrack.objects.select_related("scene", "character"),
                                 pk=pk, scene__project__user=request.user)

    def patch(self, request, pk):
        track = self._track(request, pk)
        data = request.data or {}
        fields = []
        if "start_sec" in data:
            track.start_sec, _ = _start_and_volume({"start_sec": data.get("start_sec")})
            fields.append("start_sec")
        if "volume" in data:
            _, track.volume = _start_and_volume({"volume": data.get("volume")})
            fields.append("volume")
        if fields:
            track.save(update_fields=fields)
        return Response(track_json(track))

    def delete(self, request, pk):
        track = self._track(request, pk)
        track.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
