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

from .models import CartoonProject, CartoonScene
from .services import assemble_project, charge, generate_keyframe, generate_scene_video

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=0)
def render_scene(self, scene_id: int) -> dict:
    """Кадр → видео для одной сцены. Ошибки не роняют задачу, а пишутся в сцену."""
    scene = CartoonScene.objects.filter(pk=scene_id).select_related(
        "project", "project__character", "preset", "preset__image_model", "preset__video_model"
    ).first()
    if not scene:
        return {"status": "no_scene"}

    project = scene.project
    character = project.character
    preset = scene.preset
    user = project.user

    if not character:
        scene.status = CartoonScene.STATUS_FAILED
        scene.error = "У мультфильма не выбран персонаж"
        scene.save(update_fields=["status", "error", "updated_at"])
        return {"status": "no_character"}

    # --- 1) кадр сцены ---
    if not scene.keyframe:
        scene.status = CartoonScene.STATUS_KEYFRAME
        scene.save(update_fields=["status", "updated_at"])
        try:
            scene.keyframe = generate_keyframe(preset, character)
            frame_price = max(1, int(float(preset.image_model.markup_coefficient or 1)))
            charge(user, frame_price, "cartoon_keyframe",
                   meta={"scene": scene.pk, "project": project.pk})
            scene.credits_spent += frame_price
            scene.save(update_fields=["keyframe", "credits_spent", "updated_at"])
        except Exception as exc:
            logger.exception("сцена %s: кадр не получился", scene_id)
            scene.status = CartoonScene.STATUS_FAILED
            scene.error = f"Кадр не получился: {exc}"[:500]
            scene.save(update_fields=["status", "error", "updated_at"])
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
        return {"status": "ready", "scene": scene.pk}
    except Exception as exc:
        logger.exception("сцена %s: видео не получилось", scene_id)
        scene.status = CartoonScene.STATUS_FAILED
        # Кадр остаётся: пересоздать видео можно с ним же, не сдвинув героя.
        scene.error = f"Видео не получилось: {exc}"[:500]
        scene.save(update_fields=["status", "error", "updated_at"])
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
        return {"status": "ready", "video": project.result_video}
    except Exception as exc:
        logger.exception("проект %s: склейка не удалась", project_id)
        project.status = CartoonProject.STATUS_FAILED
        project.error = str(exc)[:500]
        project.save(update_fields=["status", "error", "updated_at"])
        return {"status": "failed"}
