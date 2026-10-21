"""Фоновые задачи склейки.

render_merge идёт в очередь media (compose: celery_media): ffmpeg на минуты не
должен держать общую очередь с письмами и бонусами. Уборка и стирание
истёкших — в общей очереди по расписанию beat.
"""
from __future__ import annotations

from celery import shared_task

from . import services


@shared_task(bind=True, max_retries=0, ignore_result=True,
             soft_time_limit=services.RENDER_SOFT_LIMIT, time_limit=services.RENDER_HARD_LIMIT)
def render_merge(self, project_id: int) -> dict:
    """Склеить фрагменты. Безопасно поставить дважды: работу забирает условный UPDATE."""
    return services.run_render(project_id)


@shared_task(ignore_result=True)
def fail_stale_renders() -> dict:
    """Склейки, чья задача потерялась (деплой, убитый воркер), — закрыть и снять резерв."""
    return services.fail_stale()


@shared_task(ignore_result=True, soft_time_limit=300, time_limit=330)
def purge_expired() -> dict:
    """Раз в сутки: стереть ролики, срок хранения которых вышел (30 дней), и
    истёкшие свои видео людей, если их не склеивают прямо сейчас."""
    from . import uploads

    return {"merges": services.purge_expired(), "uploads": uploads.purge()}
