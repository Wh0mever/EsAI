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
from .services import (CustomSceneRejected, assemble_project, charge, draw_custom_keyframe,
                       ensure_custom_prompt, generate_keyframe, generate_scene_video,
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
            if scene.custom_text:
                scene.keyframe, frame_price = draw_custom_keyframe(scene, character, user)
            else:
                scene.keyframe, frame_price = get_or_create_keyframe(preset, character, user)
            scene.credits_spent += frame_price
            scene.save(update_fields=["keyframe", "credits_spent", "updated_at"])
        except Exception as exc:
            logger.exception("сцена %s: кадр не получился", scene_id)
            scene.status = CartoonScene.STATUS_FAILED
            scene.error = f"Кадр не получился: {exc}"[:500]
            scene.save(update_fields=["status", "error", "updated_at"])
            _notify_scene(scene, ok=False)
            return {"status": "keyframe_failed"}

    # --- 2) видео из кадра ---
    scene.status = CartoonScene.STATUS_VIDEO
    scene.save(update_fields=["status", "updated_at"])
    try:
        scene.video = generate_scene_video(preset, scene.keyframe)
        video_price = max(1, round(int(preset.duration or 5)
                                   * float(preset.video_model.markup_coefficient or 1)))
        charge(user, video_price, "cartoon_scene",
               meta={"scene": scene.pk, "project": project.pk})
        scene.credits_spent += video_price
        scene.status = CartoonScene.STATUS_READY
        scene.error = ""
        scene.save(update_fields=["video", "credits_spent", "status", "error", "updated_at"])
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
        scene.status = CartoonScene.STATUS_FAILED
        # Кадр остаётся: пересоздать видео можно с ним же, не сдвинув героя.
        scene.error = f"Видео не получилось: {exc}"[:500]
        scene.save(update_fields=["status", "error", "updated_at"])
        _notify_scene(scene, ok=False)
        return {"status": "video_failed"}


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
