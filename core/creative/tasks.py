"""Celery-задачи Creative Studio. Тела — в creative.pipeline и creative.catalog.

Имена по умолчанию (creative.tasks.<имя>): маршруты CELERY_TASK_ROUTES отправляют
их в очередь видеостудии (или CELERY_CREATIVE_QUEUE, если задана), а страховку
sweep_jobs, чистку и каталоги — в общую очередь: страховка обязана работать и
при лежащем воркере студии. Поэтому ни name=, ни queue= здесь не задаются.

Ожидание генерации — countdown следующей poll_job, а не time.sleep. Любую
задачу можно поставить дважды: лишняя копия выходит на условном захвате.
"""
from __future__ import annotations

from celery import shared_task

from . import pipeline


@shared_task(ignore_result=True, soft_time_limit=420, time_limit=450)
def submit_job(job_id):
    """queued→submitting → журнал → файлы к поставщику (до минут на видео) → POST → running."""
    return pipeline.submit(job_id)


@shared_task(ignore_result=True, soft_time_limit=45, time_limit=60)
def poll_job(job_id):
    """Один GET статуса → перезапуск через countdown или saving."""
    return pipeline.poll(job_id)


@shared_task(ignore_result=True, soft_time_limit=330, time_limit=360)
def finalize_job(job_id):
    """Статус ещё раз → скачивание результата → файлы → транзакция done+charged."""
    return pipeline.finalize(job_id)


@shared_task(ignore_result=True, soft_time_limit=30, time_limit=40)
def notify_job(job_id):
    """Пуш и колокольчик по итогу (у pywebpush нет таймаута — отдельной задачей)."""
    from . import notify

    return notify.notify_job_id(job_id)


@shared_task(ignore_result=True, soft_time_limit=50, time_limit=60)
def sweep_jobs():
    """Страховка конвейера (beat раз в 60 с, общая очередь)."""
    return pipeline.sweep()


@shared_task(ignore_result=True, soft_time_limit=300, time_limit=330)
def purge_uploads():
    """Старые загрузки без открытых задач (beat ночью, общая очередь)."""
    return pipeline.purge_uploads()


@shared_task(ignore_result=True, soft_time_limit=900, time_limit=960)
def sync_catalog(kind):
    """Каталог поставщика + копии превью → кэш на 6 часов."""
    from . import catalog

    return catalog.sync(kind)


@shared_task(ignore_result=True, soft_time_limit=60, time_limit=90)
def sync_catalogs():
    """Поставить обновление всех каталогов (beat раз в 6 часов)."""
    from . import catalog

    for kind in catalog.KINDS:
        sync_catalog.delay(kind)
    return len(catalog.KINDS)
