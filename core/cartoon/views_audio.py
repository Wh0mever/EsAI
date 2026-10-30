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
  POST   scenes/<id>/audio/line/    — озвучить реплику готовой сцены голосом героя {voice_id?}
  DELETE scenes/<id>/audio/line/    — вернуть голос модели
  PATCH  projects/<id>/hero-voice/  — голос героя на весь мультфильм {character_id, voice_id}
  POST   projects/<id>/voice-plan/  — ИИ пишет реплики на все сцены (бесплатно)
  POST   projects/<id>/voice-all/   — озвучить весь мультфильм по плану
  PATCH  audio/<id>/                — момент начала и громкость дорожки
  DELETE audio/<id>/
"""
from __future__ import annotations

import logging

import math
import uuid

from django.core.cache import cache
from django.core.files.storage import default_storage
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from . import audio, director, voiceover
from .models import CartoonAudioTrack, CartoonProject, CartoonScene
from .tasks import voice_movie
from .views import StudioAPIView, StudioPublicAPIView, _lang, _no_credits, _pick_character, scene_json

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
        "status": t.status,
        "error": t.error,
        "credits_planned": t.credits_planned,
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
        "dialogue_is_speech": scene.dialogue_is_speech,
        "speech_window": audio.window_json(scene),
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
    """Свободный остаток: резервы идущих генераций (сцены, видео чата, дубли
    видеостудии) на звук не тратятся."""
    from plans.wallet import available_tokens

    return available_tokens(user, int(getattr(user, "token_balance", 0) or 0))


def _data(request) -> dict:
    """Тело запроса словарём: клиент может прислать массив или строку."""
    data = getattr(request, "data", None)
    return data if isinstance(data, dict) else {}


def _start_and_volume(data) -> tuple[float, float]:
    try:
        start = float(data.get("start_sec") or 0)
    except (TypeError, ValueError):
        start = 0.0
    # NaN и бесконечность проходят сквозь min/max, поэтому проверяем отдельно.
    if not math.isfinite(start):
        start = 0.0
    try:
        volume = float(data.get("volume") if data.get("volume") is not None else 1.0)
    except (TypeError, ValueError):
        volume = 1.0
    if not math.isfinite(volume):
        volume = 1.0
    return (max(0.0, min(600.0, start)),
            max(audio.VOLUME_MIN, min(audio.VOLUME_MAX, volume)))


def _drop_mix(scene) -> None:
    """Пометить сведённый ролик сцены устаревшим.

    Дорожки изменились, а mixed_video ещё старый: пока его не пересобрали, в
    ленте играл бы прежний звук — например удалённая реплика. Пустое поле
    значит «играть исходное видео», а сведут заново при закрытии окна звука,
    после съёмки или перед сборкой мультфильма.
    """
    if scene.mixed_video:
        scene.mixed_video = ""
        scene.save(update_fields=["mixed_video", "updated_at"])


def _queue(request, scene, *, kind, price, text, seconds=0):
    """Поставить музыку или эффект в очередь и сразу ответить человеку.

    Минутная мелодия делается у провайдера дольше минуты. Раньше веб-запрос ждал
    её до конца, не укладывался в лимит Cloudflare (100 с) и человек видел
    «The origin web server returned an invalid or incomplete response». Теперь
    дорожка появляется сразу в состоянии «готовится», а звук делает фоновая
    задача; кредиты списываются, только когда звук готов.
    """
    from datetime import timedelta

    from django.utils import timezone

    from .tasks import make_audio

    if _balance(request.user) < price:
        return _no_credits(price, _balance(request.user))
    # Двойной клик не должен заказать (и оплатить) два одинаковых звука.
    fresh = timezone.now() - timedelta(minutes=5)
    if CartoonAudioTrack.objects.filter(scene__project__user=request.user,
                                        status=CartoonAudioTrack.STATUS_PENDING,
                                        created_at__gte=fresh).exists():
        return Response({"detail": "Предыдущий звук ещё делается — подождите немного"},
                        status=status.HTTP_429_TOO_MANY_REQUESTS)
    start, volume = _start_and_volume(_data(request))
    track = CartoonAudioTrack.objects.create(
        scene=scene, kind=kind, text=text, start_sec=start, volume=volume,
        status=CartoonAudioTrack.STATUS_PENDING, credits_planned=price,
        seconds_asked=float(seconds or 0))
    try:
        make_audio.delay(track.pk)
    except Exception:
        logger.exception("звук студии: задача не поставилась")
        track.delete()
        return Response({"detail": "Очередь занята — попробуйте через минуту"},
                        status=status.HTTP_503_SERVICE_UNAVAILABLE)
    return Response(track_json(track), status=status.HTTP_202_ACCEPTED)


def _generate(request, scene, *, kind, price, reason, make, text="", voice_id="", voice_name="",
              character=None, meta=None, old_line=None):
    """Сгенерировать звук, сохранить и только потом списать.

    Реплика героя (KIND_LINE) ещё и сводится до списания: человек платит за голос,
    который уже слышен в сцене, а сбой ffmpeg стоит ему ноль. Прежняя реплика
    (old_line) заменяется той же транзакцией, что и списание.
    """
    from plans.wallet import InsufficientTokens

    from .services import charge

    if _balance(request.user) < price:
        return _no_credits(price, _balance(request.user))
    # Замок держится дольше самой долгой генерации и снимается досрочно в
    # finally. Именной: чужой запрос не должен снимать наш.
    lock, token = f"studio:audio:{request.user.pk}", uuid.uuid4().hex
    if not cache.add(lock, token, timeout=600):
        return Response({"detail": "Предыдущий звук ещё делается — подождите пару секунд"},
                        status=status.HTTP_429_TOO_MANY_REQUESTS)
    try:
        from ai import genlog

        entry = genlog.start(
            user=request.user, kind=kind if kind in ("voice", "music", "sfx") else "voice",
            source="studio", provider="elevenlabs", model=voice_id or kind, prompt=text,
            credits_planned=price, scene_id=scene.pk, params=meta or {})
        is_line = kind == CartoonAudioTrack.KIND_LINE
        draft = None
        try:
            raw = make()
            path, duration = audio.save_audio(raw)
            if is_line:
                draft = voiceover.draft_line(scene, path, duration, text=text, voice_id=voice_id,
                                             voice_name=voice_name, character=character, price=price)
        except audio.AudioNotConfigured:
            entry.failed("ключ ElevenLabs не задан")
            return Response({"detail": "Озвучка пока не подключена"},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except Exception as exc:
            entry.failed(str(exc)[:500])
            logger.exception("звук студии (%s): генерация не удалась", kind)
            return Response({"detail": "Не получилось сделать звук — попробуйте ещё раз"},
                            status=status.HTTP_502_BAD_GATEWAY)
        charge_meta = {"scene": scene.pk, "kind": kind, **(meta or {})}
        try:
            if draft is None:
                charge(request.user, price, reason, meta=charge_meta, respect_reserves=True)
            else:
                with transaction.atomic():
                    # Голос делался секунды: сцену могли запустить в пересъёмку.
                    if not CartoonScene.objects.select_for_update().filter(
                            pk=scene.pk, status=CartoonScene.STATUS_READY, video=scene.video).exists():
                        raise voiceover.SceneMoved()
                    # Под замком строки: «Озвучить весь мультфильм» не ждёт эту кнопку.
                    if draft.rival(old_line) is not None:
                        raise voiceover.Superseded("реплику уже озвучили")
                    charge(request.user, price, reason, meta=charge_meta, respect_reserves=True)
                    draft.install()
        except InsufficientTokens:
            if draft is not None:
                draft.drop()
            else:
                default_storage.delete(path)
            # Звук провайдер сделал и деньги за него взял, а человек не получил.
            entry.lost("не хватило кредитов к моменту готовности")
            return _no_credits(price, _balance(request.user))
        except voiceover.SceneMoved:
            draft.drop()
            entry.lost("сцену начали переснимать, пока делался голос")
            return Response({"detail": "Сцену уже переснимают — озвучьте её, когда съёмка закончится",
                             "error_code": "scene_busy"}, status=status.HTTP_409_CONFLICT)
        except voiceover.Superseded as exc:
            draft.drop()
            entry.lost(str(exc))
            return Response(track_json(voiceover.line_track(scene)))
        except Exception as exc:
            # Провайдеру за звук заплачено: запись журнала должна пережить откат запроса.
            logger.exception("звук студии (%s): списание не прошло", kind)
            if draft is not None:
                draft.drop()
            else:
                default_storage.delete(path)
            entry.lost(str(exc)[:500])
            return Response({"detail": "Не получилось сделать звук — попробуйте ещё раз"},
                            status=status.HTTP_502_BAD_GATEWAY)
        if draft is not None:
            track = draft.track
        else:
            start, volume = _start_and_volume(_data(request))
            track = CartoonAudioTrack.objects.create(
                scene=scene, kind=kind, character=character, voice_id=voice_id, voice_name=voice_name,
                text=text, file=path, duration=duration, start_sec=start, volume=volume, credits_spent=price)
            # Сведённый ролик устарел: в нём ещё нет новой дорожки.
            _drop_mix(scene)
        entry.delivered(credits=price, result_url=_url(path))
    finally:
        if cache.get(lock) == token:
            cache.delete(lock)
    return Response(track_json(track), status=status.HTTP_201_CREATED)


class AudioConfigView(StudioPublicAPIView):
    def get(self, request):
        return Response({
            "enabled": audio.is_configured(),
            # Голос героя входит в цену «Снять» для всех: гостю цена считается на его стороне.
            "line_voice": audio.is_configured() and audio.line_mode() == "on",
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


class VoicePreviewView(StudioPublicAPIView):
    """GET — пример голоса на языке человека (по-русски, а не родной английский)."""

    def get(self, request, voice_id):
        if (resp := _need_config()):
            return resp
        lang = str(request.query_params.get("lang") or "").lower()
        if lang not in audio.PREVIEW_LINES:
            lang = _lang(request)
        try:
            path = audio.voice_preview(voice_id, lang)
        except Exception:
            logger.exception("пример голоса %s не получился", voice_id)
            return Response({"detail": "Пример пока недоступен"},
                            status=status.HTTP_502_BAD_GATEWAY)
        return Response({"url": _url(path)})


class SceneAudioView(StudioAPIView):
    def get(self, request, pk):
        return Response(_scene_audio_json(_my_scene(request, pk)))

    def patch(self, request, pk):
        scene = _my_scene(request, pk)
        data = _data(request)
        if "sound_volume" in data:
            _, volume = _start_and_volume({"volume": data.get("sound_volume")})
            scene.sound_volume = volume
            scene.save(update_fields=["sound_volume", "updated_at"])
            _drop_mix(scene)
        return Response(_scene_audio_json(scene))


class SceneVoiceView(StudioAPIView):
    def post(self, request, pk):
        if (resp := _need_config()):
            return resp
        scene = _my_scene(request, pk)
        data = _data(request)
        text = " ".join(str(data.get("text") or "").split())
        voice_id = str(data.get("voice_id") or "").strip()[:64]
        if len(text) < 1:
            return Response({"detail": "Напишите текст реплики"}, status=status.HTTP_400_BAD_REQUEST)
        if len(text) > audio.MAX_VOICE_CHARS:
            return Response({"detail": f"Реплика длиннее {audio.MAX_VOICE_CHARS} символов"},
                            status=status.HTTP_400_BAD_REQUEST)
        if not audio.valid_voice_id(voice_id):
            return Response({"detail": "Выберите голос"}, status=status.HTTP_400_BAD_REQUEST)
        # Справочник голосов — украшение подписи: его сбой не должен мешать
        # озвучке, которая и без названия голоса прекрасно работает.
        try:
            voice_name = next((v["name"] for v in (audio.list_voices() or []) if v["id"] == voice_id), "")
        except Exception:
            logger.warning("справочник голосов недоступен, пишу реплику без названия голоса")
            voice_name = ""
        character = _pick_character(request, data.get("character_id"))
        return _generate(request, scene, kind=CartoonAudioTrack.KIND_VOICE, price=audio.voice_price(text),
                         reason="cartoon_voice", make=lambda: audio.tts(text, voice_id), text=text,
                         voice_id=voice_id, voice_name=voice_name, character=character,
                         meta={"chars": len(text)})


class SceneLineView(StudioAPIView):
    """Голос героя вместо голоса модели у готовой сцены — без пересъёмки.

    POST {voice_id?} — озвучить реплику: тем же голосом героя или новым, и новый
    голос становится голосом героя на весь мультфильм. Цена известна заранее
    (line_voice_price), списание — за готовый и уже сведённый голос.
    DELETE — «Вернуть голос модели»: убрать дорожку и свести заново.
    """

    def _voice(self, request, scene, character):
        """(голос, None) или (None, ответ-отказ). Голос — {"voice_id", "voice_name"}."""
        voice_id = str(_data(request).get("voice_id") or "").strip()[:64]
        if not voice_id:
            try:
                return voiceover.hero_voice(scene.project, character, scene.voice_hint), None
            except Exception:
                logger.exception("голос героя сцены %s не выбрался", scene.pk)
                return None, Response({"detail": "Голоса сейчас недоступны — попробуйте позже"},
                                      status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return _catalog_voice(voice_id)

    def post(self, request, pk):
        if (resp := _need_config()):
            return resp
        scene = _my_scene(request, pk)
        if not audio.line_enabled(request.user):
            return Response({"detail": "Озвучка реплик пока недоступна", "error_code": "line_voice_off"},
                            status=status.HTTP_403_FORBIDDEN)
        text = (scene.dialogue or "").strip()
        if not text:
            return Response({"detail": "Сначала напишите реплику героя", "error_code": "no_dialogue"},
                            status=status.HTTP_400_BAD_REQUEST)
        if scene.status != CartoonScene.STATUS_READY or not scene.video:
            return Response({"detail": "Озвучить можно готовую сцену", "error_code": "scene_not_ready"},
                            status=status.HTTP_400_BAD_REQUEST)
        # Снято до автоозвучки или слова поправили: режиссёр их не видел, а это может быть описание.
        if director.unjudged(scene):
            director.judge_lines([scene])
        if not scene.dialogue_is_speech:
            return Response({"detail": "Похоже на описание, а не на слова героя — напишите, что он говорит вслух",
                             "error_code": "not_speech"}, status=status.HTTP_400_BAD_REQUEST)
        character = scene.character or scene.project.character
        if not character:
            return Response({"detail": "Сначала выберите героя"}, status=status.HTTP_400_BAD_REQUEST)
        voice, refused = self._voice(request, scene, character)
        if refused is not None:
            return refused
        voice_id, voice_name = voice["voice_id"], voice.get("voice_name", "")
        chosen = bool(str(_data(request).get("voice_id") or "").strip())
        lang = voiceover.line_lang(scene)
        try:
            # Сводим сами, до списания: другой ffmpeg затёр бы результат.
            with audio.mix_lock(scene.pk, wait=False):
                old = voiceover.line_track(scene)
                if old is not None and old.text == text and old.voice_id == voice_id:
                    # Те же слова тем же голосом: второго синтеза и второго списания не будет.
                    response = Response(track_json(old))
                else:
                    response = _generate(request, scene, kind=CartoonAudioTrack.KIND_LINE,
                                         price=audio.voice_price(text), reason="cartoon_voice",
                                         make=lambda: audio.tts(text, voice_id, lang=lang), text=text,
                                         voice_id=voice_id, voice_name=voice_name, character=character,
                                         meta={"chars": len(text)}, old_line=old)
        except audio.MixBusy:
            return Response({"detail": "Сцена уже сводится"}, status=status.HTTP_429_TOO_MANY_REQUESTS)
        if response.status_code not in (status.HTTP_200_OK, status.HTTP_201_CREATED):
            return response
        if response.status_code == status.HTTP_200_OK and not scene.mixed_video:
            # Голос подписан на карточке, а сведение когда-то не удалось: чиним бесплатно.
            try:
                audio.remix_scene(scene, wait=False)
            except Exception:
                logger.exception("сцена %s: реплика не свелась повторно", scene.pk)
        # Голос запоминаем только за состоявшуюся озвучку: неудачная «смена» героя не меняет.
        # Вернулись к голосу, который уже звучит в сцене, — это тоже выбор голоса героя.
        if response.status_code == status.HTTP_201_CREATED or chosen:
            voiceover.set_hero_voice(scene.project, character, voice)
        return Response({**response.data, "scene": scene_json(scene, _lang(request)),
                         "hero_voices": scene.project.hero_voices or {}}, status=response.status_code)

    def delete(self, request, pk):
        scene = _my_scene(request, pk)
        if scene.status in voiceover.WORKING_STATES:
            return Response({"detail": "Сцена сейчас снимается — голос можно будет вернуть после съёмки",
                             "error_code": "scene_busy"}, status=status.HTTP_400_BAD_REQUEST)
        deleted, _ = scene.audio_tracks.filter(kind=CartoonAudioTrack.KIND_LINE).delete()
        if deleted:
            try:
                audio.remix_scene(scene, wait=False)
            except Exception:
                # Дорожки уже нет. Пустое сведение значит «играть исходный ролик», а
                # остальные дорожки сведут при закрытии окна звука или перед склейкой.
                logger.exception("сцена %s: после возврата голоса не свелась", scene.pk)
                _drop_mix(scene)
        return Response({**_scene_audio_json(scene), "scene": scene_json(scene, _lang(request))})


class SceneMusicView(StudioAPIView):
    def post(self, request, pk):
        if (resp := _need_config()):
            return resp
        scene = _my_scene(request, pk)
        prompt = " ".join(str(_data(request).get("prompt") or "").split())[:400]
        try:
            seconds = float(_data(request).get("seconds") or 0)
        except (TypeError, ValueError):
            seconds = 0
        if not math.isfinite(seconds):
            seconds = 0
        if len(prompt) < 3:
            return Response({"detail": "Опишите музыку хотя бы парой слов"}, status=status.HTTP_400_BAD_REQUEST)
        if not (audio.MUSIC_MIN_SEC <= seconds <= audio.MUSIC_MAX_SEC):
            return Response({"detail": f"Длительность — от {audio.MUSIC_MIN_SEC} до {audio.MUSIC_MAX_SEC} секунд"},
                            status=status.HTTP_400_BAD_REQUEST)
        return _queue(request, scene, kind=CartoonAudioTrack.KIND_MUSIC,
                      price=audio.music_price(seconds), text=prompt, seconds=seconds)


class SceneSfxView(StudioAPIView):
    def post(self, request, pk):
        if (resp := _need_config()):
            return resp
        scene = _my_scene(request, pk)
        prompt = " ".join(str(_data(request).get("prompt") or "").split())[:300]
        raw_sec = _data(request).get("seconds")
        seconds = None
        if raw_sec not in (None, ""):
            try:
                seconds = float(raw_sec)
            except (TypeError, ValueError):
                seconds = None
            if seconds is not None and not math.isfinite(seconds):
                seconds = None
            if seconds is not None and not (audio.SFX_MIN_SEC <= seconds <= audio.SFX_MAX_SEC):
                return Response({"detail": f"Длительность эффекта — от {audio.SFX_MIN_SEC} до {audio.SFX_MAX_SEC} с"},
                                status=status.HTTP_400_BAD_REQUEST)
        if len(prompt) < 3:
            return Response({"detail": "Опишите звук хотя бы парой слов"}, status=status.HTTP_400_BAD_REQUEST)
        return _queue(request, scene, kind=CartoonAudioTrack.KIND_SFX,
                      price=audio.sfx_price(), text=prompt, seconds=seconds or 0)


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
        # Расширение — только из короткого списка: оно уходит в имя файла для
        # ffmpeg, а по нему выбирается разборщик (плейлист .m3u8 читал бы чужие
        # файлы и ходил бы в сеть).
        suffix = audio.upload_suffix(upload.name)
        if not suffix:
            return Response({"detail": "Этот формат не подходит — загрузите запись MP3, M4A, WAV, "
                                       "OGG, WEBM, AMR, 3GP или FLAC"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            path, duration = audio.save_audio(upload.read(), suffix=suffix,
                                              max_seconds=audio.UPLOAD_MAX_SECONDS)
        except audio.AudioTooLong:
            return Response({"detail": f"Запись длиннее {audio.UPLOAD_MAX_SECONDS // 60} минут"},
                            status=status.HTTP_400_BAD_REQUEST)
        except Exception:
            logger.exception("свой голос: файл не прочитался")
            return Response({"detail": "Не получилось прочитать запись — попробуйте другой файл"},
                            status=status.HTTP_400_BAD_REQUEST)
        data = _data(request)
        start, volume = _start_and_volume(data)
        character = _pick_character(request, data.get("character_id"))
        track = CartoonAudioTrack.objects.create(
            scene=scene, kind=CartoonAudioTrack.KIND_OWN, character=character,
            text=str(data.get("label") or "")[:200], file=path, duration=duration,
            start_sec=start, volume=volume)
        _drop_mix(scene)
        return Response(track_json(track), status=status.HTTP_201_CREATED)


class SceneMixView(StudioAPIView):
    def post(self, request, pk):
        scene = _my_scene(request, pk)
        if not scene.video:
            return Response(_scene_audio_json(scene))
        # Замок берёт сам remix_scene; сюда — без ожидания. Раньше вьюха брала
        # тот же замок заранее, и remix_scene минуту ждал саму вьюху — каждое
        # сведение шло 60 секунд и держало веб-воркер.
        try:
            audio.remix_scene(scene, wait=False)
        except audio.MixBusy:
            return Response({"detail": "Сцена уже сводится"}, status=status.HTTP_429_TOO_MANY_REQUESTS)
        except Exception:
            logger.exception("сведение сцены %s не удалось", scene.pk)
            return Response({"detail": "Не получилось свести звук со сценой"},
                            status=status.HTTP_502_BAD_GATEWAY)
        return Response(_scene_audio_json(scene))


class AudioTrackDetailView(StudioAPIView):
    def _track(self, request, pk):
        return get_object_or_404(CartoonAudioTrack.objects.select_related("scene", "character"),
                                 pk=pk, scene__project__user=request.user)

    def patch(self, request, pk):
        track = self._track(request, pk)
        data = _data(request)
        fields = []
        if "start_sec" in data:
            track.start_sec, _ = _start_and_volume({"start_sec": data.get("start_sec")})
            fields.append("start_sec")
        if "volume" in data:
            _, track.volume = _start_and_volume({"volume": data.get("volume")})
            fields.append("volume")
        if fields:
            track.save(update_fields=fields)
            _drop_mix(track.scene)
        return Response(track_json(track))

    def delete(self, request, pk):
        track = self._track(request, pk)
        scene = track.scene
        track.delete()
        # Иначе удалённая реплика продолжала бы звучать из старого сведения.
        _drop_mix(scene)
        return Response(status=status.HTTP_204_NO_CONTENT)


def _catalog_voice(voice_id: str):
    """Голос из каталога: ({"voice_id", "voice_name"}, None) или (None, ответ-отказ).

    Чужих голосов не берём: id уходит в адрес запроса к провайдеру и закрепляется
    за героем на весь мультфильм.
    """
    if not audio.valid_voice_id(voice_id):
        return None, Response({"detail": "Выберите голос"}, status=status.HTTP_400_BAD_REQUEST)
    try:
        voices = audio.list_voices() or []
    except Exception:
        logger.exception("голоса ElevenLabs не загрузились")
        voices = []
    if not voices:
        return None, Response({"detail": "Голоса сейчас недоступны — попробуйте позже"},
                              status=status.HTTP_503_SERVICE_UNAVAILABLE)
    found = next((v for v in voices if v.get("id") == voice_id), None)
    if found is None:
        return None, Response({"detail": "Такого голоса нет в списке"}, status=status.HTTP_400_BAD_REQUEST)
    return {"voice_id": voice_id, "voice_name": found.get("name", "")}, None


class ProjectHeroVoiceView(StudioAPIView):
    """PATCH {character_id, voice_id} — голос героя на весь мультфильм.

    Уже озвученные сцены не трогаем и не переозвучиваем за деньги сами: новый
    голос ляжет на следующие съёмки и по кнопке «Сменить» на карточке.
    """

    def patch(self, request, pk):
        project = get_object_or_404(CartoonProject, pk=pk, user=request.user)
        data = _data(request)
        character = _pick_character(request, data.get("character_id"))
        if not character:
            return Response({"detail": "Выберите героя"}, status=status.HTTP_400_BAD_REQUEST)
        voice, refused = _catalog_voice(str(data.get("voice_id") or "").strip()[:64])
        if refused is not None:
            return refused
        voiceover.set_hero_voice(project, character, voice)
        return Response({"hero_voices": project.hero_voices})


# ---------------------------------------- озвучить весь мультфильм ---------

# Почему план пуст: (счётчик плана, код для переводов, текст). Важнее то, что человек может сделать.
_EMPTY_PLAN = (
    ("unshot", "unshot", "Реплики озвучатся сами при съёмке — сначала снимите сцены"),
    ("working", "working", "Сцены снимаются — голос появится вместе с ними"),
    ("descriptions", "descriptions", "В сценах описания, а не слова героя: напишите, что он говорит вслух"),
    ("line_voiced", "voiced", "Озвучивать нечего: все реплики уже озвучены"),
    ("erased", "erased", "Реплику стёрли, а голос остался — уберите его в окне «Звук»"),
)


class ProjectVoicePlanView(StudioAPIView):
    """POST — реплики на все сцены и итоговая цена. Ничего не списывает.

    Клиент: «система автоматически считает все реплики и показывает итоговую
    стоимость до запуска». Поэтому план отделён от озвучки: человек видит, что
    скажут герои, и сколько это стоит, и только потом решает.
    """

    def post(self, request, pk):
        if (resp := _need_config()):
            return resp
        project = get_object_or_404(CartoonProject, pk=pk, user=request.user)
        lock = f"studio:voiceplan:{request.user.pk}"
        if not cache.add(lock, "1", timeout=60):
            return Response({"detail": "Реплики уже придумываются — подождите"},
                            status=status.HTTP_429_TOO_MANY_REQUESTS)
        # Язык берём тот, на котором человек смотрит студию, а не язык браузера.
        lang = str(_data(request).get("lang") or "").strip().lower()
        if lang not in ("ru", "en", "kg"):
            lang = _lang(request)
        try:
            plan = voiceover.build_plan(project, lang)
        except voiceover.NoVoices:
            logger.warning("озвучка мультфильма %s: список голосов пуст", project.pk)
            return Response({"detail": "Голоса сейчас недоступны — попробуйте позже"},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except voiceover.PlanFailed:
            logger.exception("озвучка мультфильма %s: реплики не написались", project.pk)
            return Response({"detail": "Не получилось придумать реплики — попробуйте ещё раз"},
                            status=status.HTTP_502_BAD_GATEWAY)
        finally:
            cache.delete(lock)
        if not plan["lines"]:
            for key, code, text in _EMPTY_PLAN:
                if plan.get(key):
                    break
            else:
                code, text = "empty", "Сначала добавьте сцены в ленту"
            return Response({"detail": text, "error_code": code}, status=status.HTTP_400_BAD_REQUEST)
        plan["balance"] = _balance(request.user)
        return Response(plan)


class ProjectVoiceAllView(StudioAPIView):
    """POST {lines, replace} — озвучить весь мультфильм по (поправленному) плану."""

    def post(self, request, pk):
        if (resp := _need_config()):
            return resp
        project = get_object_or_404(CartoonProject, pk=pk, user=request.user)
        scenes = {row["pk"]: row for row in project.scenes.values("pk", "dialogue", "dialogue_is_speech")}
        line_on = audio.line_ready(request.user)
        raw_lines = _data(request).get("lines") or []
        if not isinstance(raw_lines, list) or not raw_lines:
            return Response({"detail": "Нечего озвучивать"}, status=status.HTTP_400_BAD_REQUEST)
        if len(raw_lines) > voiceover.MAX_LINES:
            return Response({"detail": f"За один раз можно озвучить {voiceover.MAX_LINES} сцен"},
                            status=status.HTTP_400_BAD_REQUEST)

        plan, total, seen = [], 0, set()
        for item in raw_lines:
            if not isinstance(item, dict):
                continue
            try:
                scene_id = int(item.get("scene_id"))
            except (TypeError, ValueError):
                continue
            text = " ".join(str(item.get("text") or "").split())[:voiceover.MAX_LINE_CHARS]
            voice_id = str(item.get("voice_id") or "").strip()[:64]
            scene = scenes.get(scene_id)
            # Реплика человека заморожена: что бы ни прислал клиент, озвучиваем
            # её текст из сцены, а описание вслух не читаем.
            spoken = (scene["dialogue"] or "").strip() if scene and line_on else ""
            if spoken and not scene["dialogue_is_speech"]:
                continue
            text = spoken or text
            # Одна сцена — одна реплика: повтор в списке иначе оплатился бы
            # дважды, а озвучка с replace оставила бы одну дорожку.
            if scene_id in seen or scene is None or not text:
                continue
            if not audio.valid_voice_id(voice_id):
                continue
            seen.add(scene_id)
            total += audio.voice_price(text)
            plan.append({"scene_id": scene_id, "text": text, "voice_id": voice_id,
                         "voice_name": str(item.get("voice_name") or "")[:120], "line": bool(spoken)})
        if not plan:
            return Response({"detail": "Нечего озвучивать"}, status=status.HTTP_400_BAD_REQUEST)
        if _balance(request.user) < total:
            return _no_credits(total, _balance(request.user))

        lock = voiceover.lock_key(project.pk)
        token = uuid.uuid4().hex
        # Пока задача стоит в очереди, замок держится столько же, сколько
        # считается живой очередь; начав работу, задача продлевает его после
        # каждой реплики. Если воркер умер (деплой, перезапуск), прогресс
        # перестаёт обновляться — такой запуск считается брошенным, и человек
        # может начать заново, а не ждать, глядя на «озвучиваю 3 из 12».
        # Прежний запуск, если он всё же проснётся, увидит чужой замок и
        # остановится до списания (voiceover.voice_project).
        if not cache.add(lock, token, timeout=voiceover.QUEUED_STALE_AFTER):
            if not voiceover.is_stale(voiceover.get_progress(project.pk)):
                return Response({"detail": "Мультфильм уже озвучивается"},
                                status=status.HTTP_429_TOO_MANY_REQUESTS)
            cache.set(lock, token, voiceover.QUEUED_STALE_AFTER)
        voiceover.set_progress(project.pk, done=0, total=len(plan), error="", spent=0,
                               finished=False, queued=True)
        try:
            voice_movie.delay(project.pk, plan, bool(_data(request).get("replace", True)), token,
                              dict(project.hero_voices or {}))
        except Exception:
            if cache.get(lock) == token:
                cache.delete(lock)
            voiceover.clear_progress(project.pk)
            logger.exception("озвучка мультфильма %s: задача не поставилась", project.pk)
            return Response({"detail": "Очередь занята — попробуйте через минуту"},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response({"count": len(plan), "total_credits": total,
                         "voicing": voiceover.get_progress(project.pk)},
                        status=status.HTTP_202_ACCEPTED)
