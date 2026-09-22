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

from celery import shared_task
from django.conf import settings

from .models import CartoonProject, CartoonScene
from .director import ensure_video_prompt
from .services import (CustomSceneRejected, assemble_project, charge, draw_custom_keyframe,
                       draw_linked_keyframe, ensure_custom_prompt, generate_keyframe,
                       generate_scene_video, human_error, last_frame_of, previous_anchor,
                       get_or_create_keyframe, preset_for_scene, remember_pair_video)

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=0)
def render_scene(self, scene_id: int) -> dict:
    """Кадр → видео для одной сцены. Ошибки не роняют задачу, а пишутся в сцену."""
    scene = CartoonScene.objects.filter(pk=scene_id).select_related(
        "project", "project__character", "character",
        "preset", "preset__image_model", "preset__video_model"
    ).first()
    if not scene:
        return {"status": "no_scene"}

    project = scene.project
    # У сцены может быть свой герой — тогда мультфильм собирается из нескольких
    # персонажей. Не задан — берём героя всего мультфильма.
    character = scene.character or project.character
    preset = scene.preset
    user = project.user

    if not character:
        scene.status = CartoonScene.STATUS_FAILED
        scene.error = "У мультфильма не выбран персонаж"
        scene.save(update_fields=["status", "error", "updated_at"])
        return {"status": "no_character"}

    # Своя сцена: промпт из описания человека формируется до любых трат —
    # отказ модели («такое снимать нельзя») не должен стоить ему кредитов.
    if scene.custom_text:
        try:
            ensure_custom_prompt(scene)
        except CustomSceneRejected as exc:
            scene.status = CartoonScene.STATUS_FAILED
            scene.error = str(exc)[:500]
            scene.save(update_fields=["status", "error", "updated_at"])
            _notify_scene(scene, ok=False)
            return {"status": "custom_rejected"}
        except Exception as exc:
            logger.exception("сцена %s: описание не превратилось в сцену", scene_id)
            scene.status = CartoonScene.STATUS_FAILED
            scene.error = f"Не удалось разобрать описание: {exc}"[:500]
            scene.save(update_fields=["status", "error", "updated_at"])
            _notify_scene(scene, ok=False)
            return {"status": "custom_failed"}
        preset = preset_for_scene(scene)

    # --- 1) кадр сцены ---
    if not scene.keyframe:
        scene.status = CartoonScene.STATUS_KEYFRAME
        scene.save(update_fields=["status", "updated_at"])
        try:
            # Кадр мог быть нарисован раньше — при примерке героя на эту же
            # сцену. Тогда он берётся из запаса, и человек не платит дважды.
            aspect = project.aspect_ratio or "16:9"
            anchor = previous_anchor(scene)
            if anchor:
                # Не первая сцена: рисуем с оглядкой на конец предыдущей,
                # иначе герой и обстановка меняются от сцены к сцене.
                scene.keyframe, frame_price = draw_linked_keyframe(scene, character, user,
                                                                   anchor, aspect)
            elif scene.custom_text:
                scene.keyframe, frame_price = draw_custom_keyframe(scene, character, user, aspect)
            else:
                scene.keyframe, frame_price = get_or_create_keyframe(preset, character, user,
                                                                     aspect)
            scene.credits_spent += frame_price
            scene.save(update_fields=["keyframe", "credits_spent", "updated_at"])
        except Exception as exc:
            logger.exception("сцена %s: кадр не получился", scene_id)
            scene.status = CartoonScene.STATUS_FAILED
            scene.error = human_error(exc, "image")[:500]
            scene.save(update_fields=["status", "error", "updated_at"])
            _notify_scene(scene, ok=False)
            return {"status": "keyframe_failed"}

    # --- 2) видео из кадра ---
    scene.status = CartoonScene.STATUS_VIDEO
    scene.save(update_fields=["status", "updated_at"])
    entry = None
    _video_entry_closed = False
    try:
        # Промпт съёмки: разложенное по секундам действие, реплика героя и
        # запрет типовых артефактов. Собирается один раз на сцену.
        plan = ensure_video_prompt(scene, character, preset, int(preset.duration or 5))
        # Журнал генераций: по нему в админке видно, кто и что снимал, и
        # сверяются списания провайдера.
        from ai import genlog
        from .pricing import video_credits as _planned

        entry = genlog.start(
            user=user, kind="video", source="studio", model=preset.video_model.openrouter_id,
            prompt=plan["prompt"], scene_id=scene.pk,
            credits_planned=_planned(preset.video_model, preset.duration),
            params={"duration": preset.duration, "aspect_ratio": project.aspect_ratio or "",
                    "project": project.pk})
        try:
            scene.video = generate_scene_video(preset, scene.keyframe,
                                               prompt=plan["prompt"],
                                               negative=plan.get("negative", ""),
                                               character=character,
                                               aspect=project.aspect_ratio or "",
                                               entry=entry)
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
        from .pricing import video_credits

        video_price = video_credits(preset.video_model, preset.duration)
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
        entry.delivered(credits=video_price, result_url=scene.video)
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
    except Exception as exc:
        logger.exception("сцена %s: видео не получилось", scene_id)
        # Ролик снят и оплачен провайдеру, но сломалось списание или сохранение:
        # запись не должна остаться «в работе» навсегда — это в разбор.
        try:
            if entry is not None and not _video_entry_closed and entry.is_open():
                entry.lost(f"ролик снят, но не выдан: {exc}"[:500])
        except Exception:
            logger.exception("сцена %s: журнал генераций не закрылся", scene_id)
        scene.status = CartoonScene.STATUS_FAILED
        # Кадр остаётся: пересоздать видео можно с ним же, не сдвинув героя.
        scene.error = human_error(exc, "video")[:500]
        scene.save(update_fields=["status", "error", "updated_at"])
        _notify_scene(scene, ok=False)
        return {"status": "video_failed"}


@shared_task(bind=True, max_retries=0)
def make_audio(self, track_id: int) -> dict:
    """Сделать музыку или эффект для дорожки. Списание — только за готовый звук."""
    from django.core.files.storage import default_storage
    from django.db import transaction

    from ai import genlog
    from plans.wallet import InsufficientTokens

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

    from .voiceover import lock_key, set_progress, voice_project

    project = CartoonProject.objects.select_related("user").filter(pk=project_id).first()
    if not project:
        cache.delete(lock_key(project_id))
        return {"status": "no_project"}
    try:
        return voice_project(project, plan or [], replace)
    except Exception:
        # Прогресс должен закрыться в любом случае: иначе студия будет вечно
        # показывать «озвучиваю» и не даст запустить заново.
        set_progress(project_id, error="failed", finished=True)
        raise
    finally:
        # Снимаем только свой замок: чужой мог принадлежать новому запуску.
        if not token or cache.get(lock_key(project_id)) == token:
            cache.delete(lock_key(project_id))


@shared_task(bind=True, max_retries=0)
def assemble_movie(self, project_id: int) -> dict:
    """Склеить готовые сцены проекта в один ролик. Склейка бесплатна."""
    project = CartoonProject.objects.filter(pk=project_id).first()
    if not project:
        return {"status": "no_project"}

    project.status = CartoonProject.STATUS_ASSEMBLING
    project.error = ""
    project.save(update_fields=["status", "error", "updated_at"])
    try:
        project.result_video = assemble_project(project)
        project.status = CartoonProject.STATUS_READY
        project.save(update_fields=["result_video", "status", "updated_at"])
        _notify_movie(project, ok=True)
        return {"status": "ready", "video": project.result_video}
    except Exception as exc:
        logger.exception("проект %s: склейка не удалась", project_id)
        project.status = CartoonProject.STATUS_FAILED
        project.error = str(exc)[:500]
        project.save(update_fields=["status", "error", "updated_at"])
        _notify_movie(project, ok=False)
        return {"status": "failed"}


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
