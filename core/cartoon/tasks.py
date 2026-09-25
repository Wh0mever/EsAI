"""Фоновые задачи студии: генерация сцены и сборка мультфильма.

Почему через Celery, а не в веб-запросе: кадр рисуется секунды, а видео —
минуты. Держать HTTP-соединение всё это время нельзя, поэтому фронт создаёт
сцену, получает её id и опрашивает состояние.

Деньги списываются ПО ФАКТУ каждого шага. Если видео не получилось, за него не
берём ничего; кадр при этом уже сделан, остаётся у пользователя и оплачен.
Это честнее, чем брать всё вперёд и возвращать при сбое.
"""
from __future__ import annotations

import logging
import time
from datetime import timedelta

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from django.conf import settings
from django.db import DatabaseError, transaction
from django.db.models import Q
from django.utils import timezone

from plans.wallet import InsufficientTokens

from .models import CartoonProject, CartoonScene
from .director import ensure_video_prompt
from .pricing import scene_video_credits
from .services import (CustomSceneRejected, assemble_project, charge, draw_custom_keyframe,
                       draw_linked_keyframe, ensure_custom_prompt,
                       generate_scene_video, human_error, last_frame_of, previous_anchor,
                       get_or_create_keyframe, pooled_keyframe, preset_for_scene,
                       remember_pair_video)

logger = logging.getLogger(__name__)

# Лимиты съёмки. Кадр (до ~4 мин), промпт и отправка (до ~4 мин), ожидание
# ролика (services.VIDEO_POLL_SECONDS — 12 мин), скачивание (до 5 мин) и
# последний кадр. Общий лимит Celery (9/10 мин) был меньше одного только
# ожидания: задачу убивали на середине, и сцена навсегда оставалась «Оживляется».
RENDER_SOFT_LIMIT = 30 * 60
RENDER_HARD_LIMIT = RENDER_SOFT_LIMIT + 60
ASSEMBLE_SOFT_LIMIT = 15 * 60
ASSEMBLE_HARD_LIMIT = ASSEMBLE_SOFT_LIMIT + 60

# Уборка оборвавшейся работы (fail_stale_work). Живая съёмка отмечает сцену раз
# в минуту, поэтому двадцать минут тишины — это обрыв, а не долгий ролик.
# «Ожидает» — задача ещё в очереди media, там можно и постоять: очередь общая
# (compose: celery_media, три места), и каждая съёмка впереди занимает место до
# получаса. Поэтому ждём STALE_QUEUED_AFTER плюс по лимиту съёмки на каждый
# «круг» стоящих впереди, но не дольше STALE_QUEUED_CAP.
STALE_WORK_AFTER = timedelta(minutes=20)
STALE_QUEUED_AFTER = timedelta(minutes=45)
STALE_QUEUED_CAP = timedelta(hours=6)
MEDIA_SLOTS = 3
HEARTBEAT_EVERY = 60

STALE_SCENE_ERROR = "Съёмка оборвалась — кредиты за видео не списаны, попробуйте ещё раз"
STALE_MOVIE_ERROR = "Склейка оборвалась — попробуйте собрать мультфильм ещё раз"
TIMEOUT_SCENE_ERROR = "Съёмка заняла слишком долго — кредиты за видео не списаны, попробуйте ещё раз"
NO_CREDITS_FRAME_ERROR = "Не хватило кредитов на кадр — пополните баланс и снимите сцену снова"
NO_CREDITS_VIDEO_ERROR = ("Не хватило кредитов на видео: баланс ушёл на другое, пока сцена снималась. "
                          "Пополните баланс и переснимите — кадр сохранён, второй раз за него "
                          "платить не придётся.")

# Состояния, в которых сценой владеет задача съёмки.
_TASK_STATES = (CartoonScene.STATUS_KEYFRAME, CartoonScene.STATUS_VIDEO)


class _SceneGone(Exception):
    """Сцену удалили или её съёмку уже прервали — выдавать ролик некуда."""


def _fail(scene, text: str, notify: bool = True) -> None:
    """Сцена не снялась. Условным UPDATE: удалённую сцену не воскрешаем и на ней
    не падаем, а сцену, которую уже перезапустили, не затираем."""
    scene.status = CartoonScene.STATUS_FAILED
    scene.error = str(text or "")[:500]
    updated = CartoonScene.objects.filter(pk=scene.pk, status__in=_TASK_STATES).update(
        status=CartoonScene.STATUS_FAILED, error=scene.error, updated_at=timezone.now())
    if updated and notify:
        _notify_scene(scene, ok=False)


def _close_entry(entry, text: str) -> None:
    """Провайдер ролик снял (и взял деньги), а человек его не получил — в разбор."""
    try:
        if entry is not None and entry.is_open():
            entry.lost(text[:500])
    except Exception:
        logger.exception("журнал генераций не закрылся")


def _heartbeat(scene_id: int, clock=time.monotonic):
    """Отметка «съёмка жива» раз в минуту — по ней уборка не трогает долгий ролик."""
    last = [clock()]

    def beat() -> None:
        now = clock()
        if now - last[0] < HEARTBEAT_EVERY:
            return
        last[0] = now
        try:
            CartoonScene.objects.filter(pk=scene_id, status=CartoonScene.STATUS_VIDEO).update(
                updated_at=timezone.now())
        except DatabaseError:
            logger.warning("сцена %s: отметка съёмки не записалась", scene_id)

    return beat


def _draw_frame(scene, preset, character, aspect: str) -> tuple[str, int, dict]:
    """Кадр сцены БЕЗ списания: (путь, цена, meta). Списывает render_scene —
    вместе с сохранением кадра, одной транзакцией."""
    if not scene.custom_text:
        # Кадр, который человек уже видел в примерке или «Кадр заново» (и за
        # который заплатил), лежит в общем запасе — снимаем с него. Раньше вторая
        # и дальше сцены рисовали новый кадр «с оглядкой» на прошлую: показали
        # одно, сняли другое и взяли за кадр второй раз.
        pooled = pooled_keyframe(scene.preset_id, character, aspect)
        if pooled:
            return pooled, 0, {}
    anchor = previous_anchor(scene)
    if anchor:
        # Не первая сцена: рисуем с оглядкой на конец предыдущей, иначе герой и
        # обстановка меняются от сцены к сцене.
        path, price = draw_linked_keyframe(scene, character, None, anchor, aspect)
        return path, price, {"scene": scene.pk, "linked": True, "character": character.pk}
    if scene.custom_text:
        path, price = draw_custom_keyframe(scene, character, None, aspect)
        return path, price, {"scene": scene.pk, "custom": True, "character": character.pk}
    path, price = get_or_create_keyframe(preset, character, None, aspect)
    return path, price, {"preset": preset.pk, "character": character.pk, "scene": scene.pk}


@shared_task(bind=True, max_retries=0, soft_time_limit=RENDER_SOFT_LIMIT,
             time_limit=RENDER_HARD_LIMIT)
def render_scene(self, scene_id: int) -> dict:
    """Кадр → видео для одной сцены. Ошибки не роняют задачу, а пишутся в сцену."""
    scene = CartoonScene.objects.filter(pk=scene_id).select_related(
        "project", "project__character", "character",
        "preset", "preset__image_model", "preset__video_model"
    ).first()
    if not scene:
        return {"status": "no_scene"}

    # Съёмку ведёт ровно одна задача: забираем сцену из «Ожидает» условным
    # UPDATE. Вторая копия задачи (повторная доставка) или задача, дождавшаяся
    # очереди, когда сцену уже объявили оборвавшейся и перезапустили, сюда не
    # пройдёт — и не снимет и не спишет второй раз.
    first = CartoonScene.STATUS_VIDEO if scene.keyframe else CartoonScene.STATUS_KEYFRAME
    if not CartoonScene.objects.filter(pk=scene.pk, status=CartoonScene.STATUS_NEW).update(
            status=first, updated_at=timezone.now()):
        return {"status": "not_queued"}
    scene.status = first

    project = scene.project
    # У сцены может быть свой герой — тогда мультфильм собирается из нескольких
    # персонажей. Не задан — берём героя всего мультфильма.
    character = scene.character or project.character
    preset = scene.preset
    user = project.user

    if not character:
        _fail(scene, "У мультфильма не выбран персонаж", notify=False)
        return {"status": "no_character"}

    # Своя сцена: промпт из описания человека формируется до любых трат —
    # отказ модели («такое снимать нельзя») не должен стоить ему кредитов.
    if scene.custom_text:
        try:
            ensure_custom_prompt(scene)
        except CustomSceneRejected as exc:
            _fail(scene, str(exc))
            return {"status": "custom_rejected"}
        except Exception:
            logger.exception("сцена %s: описание не превратилось в сцену", scene_id)
            _fail(scene, "Не удалось разобрать описание — попробуйте ещё раз или опишите сцену иначе")
            return {"status": "custom_failed"}
        preset = preset_for_scene(scene)

    # --- 1) кадр сцены ---
    if not scene.keyframe:
        aspect = project.aspect_ratio or "16:9"
        try:
            path, frame_price, meta = _draw_frame(scene, preset, character, aspect)
        except Exception as exc:
            logger.exception("сцена %s: кадр не получился", scene_id)
            _fail(scene, human_error(exc, "image"))
            return {"status": "keyframe_failed"}
        try:
            # Кадр оплачивается одной транзакцией с сохранением: сцену могли
            # удалить, пока он рисовался, — тогда и не списываем.
            with transaction.atomic():
                if not CartoonScene.objects.select_for_update().filter(
                        pk=scene.pk, status=CartoonScene.STATUS_KEYFRAME).exists():
                    raise _SceneGone()
                charge(user, frame_price, "cartoon_keyframe", meta=meta)
                scene.keyframe = path
                scene.credits_spent += frame_price
                scene.save(update_fields=["keyframe", "credits_spent", "updated_at"])
        except _SceneGone:
            return {"status": "gone"}
        except InsufficientTokens:
            logger.warning("сцена %s: не хватило кредитов на кадр", scene_id)
            _fail(scene, NO_CREDITS_FRAME_ERROR)
            return {"status": "no_credits"}
        except Exception:
            logger.exception("сцена %s: кадр не сохранился", scene_id)
            _fail(scene, "Кадр не получился — попробуйте ещё раз")
            return {"status": "keyframe_failed"}

    # --- 2) видео из кадра ---
    if not CartoonScene.objects.filter(pk=scene.pk, status__in=_TASK_STATES).update(
            status=CartoonScene.STATUS_VIDEO, updated_at=timezone.now()):
        return {"status": "gone"}
    scene.status = CartoonScene.STATUS_VIDEO
    entry = None
    _video_entry_closed = False
    # Одна формула на витрину, проверку баланса и списание (pricing.py).
    video_price = scene_video_credits(preset)
    try:
        # Промпт съёмки: разложенное по секундам действие, реплика героя и
        # запрет типовых артефактов. Собирается один раз на сцену.
        plan = ensure_video_prompt(scene, character, preset, int(preset.duration or 5))
        # Журнал генераций: по нему в админке видно, кто и что снимал, и
        # сверяются списания провайдера.
        from ai import genlog

        entry = genlog.start(
            user=user, kind="video", source="studio", model=preset.video_model.openrouter_id,
            prompt=plan["prompt"], scene_id=scene.pk,
            credits_planned=video_price,
            params={"duration": preset.duration, "aspect_ratio": project.aspect_ratio or "",
                    "project": project.pk})
        try:
            scene.video = generate_scene_video(preset, scene.keyframe,
                                               prompt=plan["prompt"],
                                               negative=plan.get("negative", ""),
                                               character=character,
                                               aspect=project.aspect_ratio or "",
                                               entry=entry,
                                               heartbeat=_heartbeat(scene.pk))
        except Exception as video_exc:
            # Провайдер запрос принял (есть ID) — значит мог взять деньги, а
            # ролика у человека нет: это в разбор, а не просто «ошибка».
            import requests as _rq

            accepted = bool(getattr(getattr(entry, "row", None), "polling_url", ""))
            # Сетевой сбой без ответа (таймаут, обрыв) — провайдер мог успеть
            # принять запрос: это ровно сценарий потерянного ролика 21.09.
            no_answer = isinstance(video_exc, (_rq.Timeout, _rq.ConnectionError))
            if accepted or no_answer:
                entry.lost(str(video_exc)[:500])
            else:
                entry.failed(str(video_exc)[:500])
            raise
        # Последний кадр пригодится следующей сцене как опора.
        scene.last_frame = last_frame_of(scene.video)
        # Деньги и сцена — одной транзакцией, и только пока сцена жива и всё ещё
        # снимается. Раньше списание проходило, а сохранение удалённой сцены
        # падало: деньги ушли, ролика нет.
        with transaction.atomic():
            if not CartoonScene.objects.select_for_update().filter(
                    pk=scene.pk, status=CartoonScene.STATUS_VIDEO).exists():
                raise _SceneGone()
            charge(user, video_price, "cartoon_scene",
                   meta={"scene": scene.pk, "project": project.pk})
            scene.credits_spent += video_price
            scene.status = CartoonScene.STATUS_READY
            scene.error = ""
            # Прошлое сведение относилось к прошлому ролику: если его не сбросить,
            # после пересъёмки в ленте продолжал бы играть старый вариант.
            scene.mixed_video = ""
            scene.save(update_fields=["video", "last_frame", "mixed_video", "credits_spent",
                                      "status", "error", "updated_at"])
        # Адрес, а не путь к файлу: из админки «результат» открывался как
        # /admin-new/cartoon/scenes/<файл>.mp4 и давал 404.
        from django.core.files.storage import default_storage as _storage

        entry.delivered(credits=video_price, result_url=_storage.url(scene.video))
        _video_entry_closed = True
        # Звук, набранный до съёмки, накладывается сам (клиент: «в итоге всё
        # автоматически объединяется»). Сбой сведения не портит снятую сцену.
        try:
            from .audio import remix_scene

            remix_scene(scene)
        except Exception:
            logger.exception("сцена %s: звук не свёлся после съёмки", scene_id)
        # Готовая пара «библиотечный герой + сцена» становится движущимся
        # превью для всех. Сбой здесь не должен портить уже снятую сцену.
        try:
            remember_pair_video(scene)
        except Exception:
            logger.exception("сцена %s: ролик не лёг в общий запас", scene_id)
        _notify_scene(scene, ok=True)
        return {"status": "ready", "scene": scene.pk}
    except _SceneGone:
        logger.warning("сцена %s: удалена или прервана до выдачи ролика", scene_id)
        _close_entry(entry, f"сцену удалили или прервали до выдачи ролика: {scene.video}")
        return {"status": "gone"}
    except InsufficientTokens:
        # Баланс ушёл на другое, пока шла съёмка (запуск сцены уже учитывает
        # другие снимающиеся сцены). Ролик снят и оплачен провайдеру — в разбор.
        logger.warning("сцена %s: не хватило кредитов к моменту готовности", scene_id)
        _close_entry(entry, f"не хватило кредитов к моменту готовности: {scene.video}")
        _fail(scene, NO_CREDITS_VIDEO_ERROR)
        return {"status": "no_credits"}
    except Exception as exc:
        logger.exception("сцена %s: видео не получилось", scene_id)
        # Ролик снят и оплачен провайдеру, но сломалось списание или сохранение:
        # запись не должна остаться «в работе» навсегда — это в разбор.
        if not _video_entry_closed:
            _close_entry(entry, f"ролик снят, но не выдан: {exc}")
        # Кадр остаётся: пересоздать видео можно с ним же, не сдвинув героя.
        _fail(scene, TIMEOUT_SCENE_ERROR if isinstance(exc, SoftTimeLimitExceeded)
              else human_error(exc, "video"))
        return {"status": "video_failed"}


@shared_task(bind=True, max_retries=0)
def make_audio(self, track_id: int) -> dict:
    """Сделать музыку или эффект для дорожки. Списание — только за готовый звук."""
    from django.core.files.storage import default_storage

    from ai import genlog

    from . import audio
    from .models import CartoonAudioTrack

    track = (CartoonAudioTrack.objects.select_related("scene__project__user")
             .filter(pk=track_id, status=CartoonAudioTrack.STATUS_PENDING).first())
    if not track:
        return {"status": "no_track"}
    user = track.scene.project.user
    music = track.kind == CartoonAudioTrack.KIND_MUSIC
    entry = genlog.start(
        user=user, kind="music" if music else "sfx", source="studio", provider="elevenlabs",
        model="music_v1" if music else "eleven_text_to_sound_v2", prompt=track.text,
        credits_planned=track.credits_planned, scene_id=track.scene_id,
        params={"seconds": track.seconds_asked})

    def fail(text: str, shown: str) -> dict:
        entry.failed(text)
        track.status = CartoonAudioTrack.STATUS_FAILED
        track.error = shown[:300]
        track.save(update_fields=["status", "error"])
        return {"status": "failed"}

    try:
        raw = (audio.music(track.text, track.seconds_asked) if music
               else audio.sound_effect(track.text, track.seconds_asked or None))
        path, duration = audio.save_audio(raw)
    except Exception as exc:
        logger.exception("звук студии: дорожка %s не получилась", track_id)
        text = str(exc)
        # Отказ провайдера — словами: «попробуйте ещё раз» бессмысленно, если
        # музыка не открыта на тарифе ElevenLabs (случай 22.09: 402 paid_plan_required).
        if "paid_plan_required" in text or "not available for free users" in text:
            shown = "Музыка временно недоступна — мы уже знаем. Кредиты не списаны."
        elif "http 402" in text or "quota" in text.lower():
            shown = "Сервис звука временно недоступен — кредиты не списаны, попробуйте позже."
        elif "http 429" in text:
            shown = "Сервис звука перегружен — подождите минуту и попробуйте снова."
        else:
            shown = "Не получилось сделать звук — попробуйте ещё раз"
        return fail(text[:500], shown)
    try:
        with transaction.atomic():
            charge(user, track.credits_planned,
                   "cartoon_music" if music else "cartoon_sfx",
                   meta={"scene": track.scene_id, "kind": track.kind, "track": track.pk})
            track.file = path
            track.duration = duration
            track.credits_spent = track.credits_planned
            track.status = CartoonAudioTrack.STATUS_READY
            track.save(update_fields=["file", "duration", "credits_spent", "status"])
    except InsufficientTokens:
        default_storage.delete(path)
        return fail("не хватило кредитов к моменту готовности", "Не хватило кредитов")
    entry.delivered(credits=track.credits_spent, result_url=default_storage.url(path))
    # Сцена уже снята — звук сразу ложится на ролик.
    try:
        if track.scene.video:
            audio.remix_scene(track.scene)
    except Exception:
        logger.exception("звук студии: сцена %s не свелась", track.scene_id)
    return {"status": "ready"}


@shared_task(bind=True, max_retries=0)
def voice_movie(self, project_id: int, plan: list, replace: bool = True, token: str = "") -> dict:
    """Озвучить все реплики мультфильма. Каждая реплика оплачивается по факту.

    В очереди, а не во вьюхе: десять реплик — это десятки секунд у ElevenLabs
    плюс сведение ffmpeg, и держать на этом веб-воркер нельзя.
    """
    from django.core.cache import cache

    from .voiceover import lock_key, lock_owned, set_progress, voice_project

    project = CartoonProject.objects.select_related("user").filter(pk=project_id).first()
    if not project:
        if not token or cache.get(lock_key(project_id)) == token:
            cache.delete(lock_key(project_id))
        return {"status": "no_project"}
    try:
        return voice_project(project, plan or [], replace, token=token)
    except Exception:
        # Прогресс должен закрыться в любом случае: иначе студия будет вечно
        # показывать «озвучиваю» и не даст запустить заново. Но только свой:
        # чужой прогресс принадлежит новому запуску.
        if lock_owned(project_id, token):
            set_progress(project_id, error="failed", finished=True)
        raise
    finally:
        # Снимаем только свой замок: чужой мог принадлежать новому запуску.
        if not token or cache.get(lock_key(project_id)) == token:
            cache.delete(lock_key(project_id))


def _assembly_error(exc) -> str:
    """Причина сбоя склейки — словами. Сырой текст исключения остаётся в логе:
    раньше человек видел «Склейка не удалась: [Errno 2] …»."""
    if isinstance(exc, SoftTimeLimitExceeded):
        return "Склейка заняла слишком долго — попробуйте собрать мультфильм ещё раз"
    if "нет готовых сцен" in str(exc):
        return "Нет готовых сцен — снимите хотя бы одну и соберите снова"
    return "Не получилось склеить мультфильм — попробуйте собрать ещё раз"


@shared_task(bind=True, max_retries=0, soft_time_limit=ASSEMBLE_SOFT_LIMIT,
             time_limit=ASSEMBLE_HARD_LIMIT)
def assemble_movie(self, project_id: int) -> dict:
    """Склеить готовые сцены проекта в один ролик. Склейка бесплатна."""
    # Склейку ведёт ровно одна задача: забираем проект условным UPDATE и
    # отмечаем начало работы. Раньше задача ставила «Собирается» безусловно:
    # проект, который уборка уже объявила оборвавшимся, оживал, а старая задача
    # из очереди склеивала рядом с новой, поставленной повторным нажатием.
    started = timezone.now()
    if not CartoonProject.objects.filter(
            pk=project_id, status=CartoonProject.STATUS_ASSEMBLING,
            assembly_started_at__isnull=True).update(
            assembly_started_at=started, error="", updated_at=started):
        return {"status": "not_queued"}
    project = CartoonProject.objects.filter(pk=project_id).first()
    if not project:
        return {"status": "no_project"}
    # Итог пишем только в свой запуск: его не объявили оборвавшимся и не
    # перезапустили, пока шла склейка.
    mine = CartoonProject.objects.filter(pk=project_id, status=CartoonProject.STATUS_ASSEMBLING,
                                         assembly_started_at=started)
    try:
        video = assemble_project(project)
        if not mine.update(result_video=video, status=CartoonProject.STATUS_READY,
                           updated_at=timezone.now()):
            logger.warning("мультфильм %s: склейка уже не наша, итог не записан", project_id)
            return {"status": "gone"}
        project.result_video, project.status = video, CartoonProject.STATUS_READY
        _notify_movie(project, ok=True)
        return {"status": "ready", "video": project.result_video}
    except Exception as exc:
        logger.exception("проект %s: склейка не удалась", project_id)
        project.status = CartoonProject.STATUS_FAILED
        project.error = _assembly_error(exc)
        if mine.update(status=project.status, error=project.error, updated_at=timezone.now()):
            _notify_movie(project, ok=False)
        return {"status": "failed"}


def _queue_allowance(queued_at) -> timedelta:
    """Сколько задача, вставшая в очередь media в queued_at, может в ней простоять,
    прежде чем её сочтут потерянной. Впереди — живые съёмки и сцены, поставленные
    раньше; каждые MEDIA_SLOTS из них — ещё до одного лимита съёмки ожидания."""
    fresh = timezone.now() - STALE_WORK_AFTER
    ahead = CartoonScene.objects.filter(
        Q(status__in=_TASK_STATES, updated_at__gte=fresh)
        | Q(status=CartoonScene.STATUS_NEW, updated_at__lt=queued_at)).count()
    wait = STALE_QUEUED_AFTER + timedelta(seconds=RENDER_HARD_LIMIT) * (ahead // MEDIA_SLOTS)
    return min(wait, STALE_QUEUED_CAP)


def _lose_open_entries(scene_id: int) -> None:
    """Запись журнала оборвавшейся съёмки — в разбор: провайдер мог снять и взять деньги."""
    try:
        from ai import genlog
        from ai.models import GenerationLog

        rows = GenerationLog.objects.filter(source=GenerationLog.SOURCE_STUDIO, scene_id=scene_id,
                                            status__in=GenerationLog.OPEN_STATES)
        for row in rows:
            genlog.Entry(row).lost("съёмка оборвалась (задачу остановили), ролик не выдан")
    except Exception:
        logger.exception("сцена %s: журнал оборвавшейся съёмки не закрылся", scene_id)


@shared_task
def fail_stale_work() -> dict:
    """Закрыть съёмки и склейки, которые оборвались: деплой, убитый воркер, лимит.

    Без этого сцена навсегда оставалась «Оживляется»: крутилка вечная, удалить
    её нельзя (идёт съёмка), а цена держится в резерве баланса. Живая съёмка
    отмечает сцену раз в минуту (heartbeat в generate_scene_video), поэтому сюда
    попадает только то, что молчит дольше STALE_WORK_AFTER. Денег здесь не
    трогаем: видео оплачивается только по готовности, значит, и не списано.
    """
    now = timezone.now()
    out = {"scenes": 0, "projects": 0}
    stale = list(CartoonScene.objects.filter(
        Q(status__in=_TASK_STATES, updated_at__lt=now - STALE_WORK_AFTER)
        | Q(status=CartoonScene.STATUS_NEW, updated_at__lt=now - STALE_QUEUED_AFTER)
    ).select_related("project__user", "preset").order_by("updated_at", "id")[:200])
    for scene in stale:
        if (scene.status == CartoonScene.STATUS_NEW
                and scene.updated_at >= now - _queue_allowance(scene.updated_at)):
            continue  # ещё ждёт своей очереди за чужими съёмками
        # Условно — по тому же состоянию и той же отметке времени: если съёмка
        # как раз ожила, её не трогаем.
        if not CartoonScene.objects.filter(pk=scene.pk, status=scene.status,
                                           updated_at=scene.updated_at).update(
                status=CartoonScene.STATUS_FAILED, error=STALE_SCENE_ERROR, updated_at=now):
            continue
        out["scenes"] += 1
        logger.warning("сцена %s: съёмка оборвалась в состоянии %s", scene.pk, scene.status)
        _lose_open_entries(scene.pk)
        scene.status, scene.error = CartoonScene.STATUS_FAILED, STALE_SCENE_ERROR
        _notify_scene(scene, ok=False)
    for project in CartoonProject.objects.filter(
            status=CartoonProject.STATUS_ASSEMBLING,
            updated_at__lt=now - STALE_WORK_AFTER).order_by("id")[:200]:
        # Задача ещё не взялась за склейку — она стоит в общей очереди media за
        # съёмками. Двадцать минут отсчитываем только от начала работы (задача
        # отмечает его и сдвигает updated_at), а очереди даём своё время.
        if (project.assembly_started_at is None
                and project.updated_at >= now - _queue_allowance(project.updated_at)):
            continue
        # Условно по отметке времени: задача могла взяться за склейку только что.
        if CartoonProject.objects.filter(pk=project.pk, status=CartoonProject.STATUS_ASSEMBLING,
                                         updated_at=project.updated_at).update(
                status=CartoonProject.STATUS_FAILED, error=STALE_MOVIE_ERROR, updated_at=now):
            out["projects"] += 1
            logger.warning("мультфильм %s: склейка оборвалась", project.pk)
    return out


def _notify_scene(scene, ok: bool) -> None:
    """Сказать человеку в Telegram, что сцена готова (или нет)."""
    try:
        from django.core.files.storage import default_storage

        from botapi.tasks import notify

        project = scene.project
        user = project.user
        title = scene.preset.title if scene.preset_id else "сцена"
        base = (getattr(settings, "SITE_BASE_URL", "") or "https://esai.kg").rstrip("/")
        studio = f"{base}/studio?project={project.pk}"
        if ok:
            video_url = ""
            try:
                if scene.video and default_storage.size(scene.video) <= 20 * 1024 * 1024:
                    video_url = base + default_storage.url(scene.video)
            except Exception:
                video_url = ""
            notify(user, "ready",
                   f"🎬 Сцена «{title}» готова! Списано {scene.credits_spent} кр.",
                   url=studio, url_label="Открыть в студии", video_url=video_url or None)
        else:
            notify(user, "ready",
                   f"😕 Сцена «{title}» не получилась: {scene.error[:120]}\n"
                   "Кредиты за видео не списаны.",
                   url=studio, url_label="Открыть в студии")
    except Exception:
        logger.exception("сцена %s: уведомление не ушло", scene.pk)


def _notify_movie(project, ok: bool) -> None:
    try:
        from django.core.files.storage import default_storage

        from botapi.tasks import notify

        base = (getattr(settings, "SITE_BASE_URL", "") or "https://esai.kg").rstrip("/")
        studio = f"{base}/studio?project={project.pk}"
        scenes = project.scenes.filter(status=CartoonScene.STATUS_READY).count()
        if ok:
            video_url = ""
            try:
                if project.result_video and default_storage.size(project.result_video) <= 20 * 1024 * 1024:
                    video_url = base + default_storage.url(project.result_video)
            except Exception:
                video_url = ""
            notify(project.user, "ready",
                   f"🎞 Мультфильм «{project.title}» готов! Сцен: {scenes}.",
                   url=studio, url_label="Открыть в студии", video_url=video_url or None)
        else:
            notify(project.user, "ready",
                   f"😕 Мультфильм «{project.title}» не собрался: {project.error[:120]}",
                   url=studio, url_label="Открыть в студии")
    except Exception:
        logger.exception("проект %s: уведомление не ушло", project.pk)
