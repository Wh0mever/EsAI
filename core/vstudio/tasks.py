"""Celery-задачи видеостудии (§6.2). Тела — в vstudio.pipeline.

Имена задач — по умолчанию (vstudio.tasks.<имя>): маршруты CELERY_TASK_ROUTES
отправляют их в очередь студии, а sweep_takes и purge_assets — в общую, чтобы
страховка работала и при лежащем воркере студии. Туда же идёт
build_showcase_clip: ffmpeg не должен занимать слот, в котором ждёт
оплаченная генерация. Поэтому ни name=, ни queue= здесь не задаются.

Задачи короткие: один сетевой вызов и условные UPDATE. Ожидание генерации —
это countdown следующей poll_take, а не time.sleep в слоте воркера. Любую
задачу можно поставить дважды: лишняя копия выходит на условном захвате.
Результаты не храним (ignore_result): итог живёт в строке Take.
"""
from __future__ import annotations

from celery import shared_task

from . import pipeline


@shared_task(ignore_result=True, soft_time_limit=200, time_limit=230)
def submit_take(take_id):
    """queued→submitting → журнал → POST /videos (до 150 с) → running | failed | lost."""
    return pipeline.submit(take_id)


@shared_task(ignore_result=True, soft_time_limit=45, time_limit=60)
def poll_take(take_id):
    """Один GET по адресу опроса → перезапуск через countdown или saving."""
    return pipeline.poll(take_id)


@shared_task(ignore_result=True, soft_time_limit=280, time_limit=300)
def finalize_take(take_id, redeliver=False):
    """Повторный опрос → скачивание (≤180 с, ≤300 МБ) → файлы → транзакция done+charged.

    redeliver=True ставит только админка («Довезти»): lost→done без списания.
    """
    return pipeline.finalize(take_id, redeliver=bool(redeliver))


@shared_task(ignore_result=True, soft_time_limit=220, time_limit=250)
def run_image_take(take_id):
    """queued→running → журнал → POST /images (до 180 с) → сохранение → done+charged."""
    return pipeline.run_image(take_id)


@shared_task(ignore_result=True, soft_time_limit=30, time_limit=40)
def notify_take(take_id):
    """Пуш и колокольчик по итогу дубля (§6.6). Отдельно от конвейера: у pywebpush
    нет таймаута, зависший push-сервис не должен держать sweep или выдачу."""
    from . import notify

    return notify.notify_take_id(take_id)


@shared_task(ignore_result=True, soft_time_limit=50, time_limit=60)
def sweep_takes():
    """Страховка конвейера (beat раз в 60 с, общая очередь)."""
    return pipeline.sweep()


@shared_task(ignore_result=True, soft_time_limit=300, time_limit=330)
def purge_assets():
    """Удалённые материалы старше VSTUDIO_PURGE_DAYS без ссылок (beat в 04:30, общая очередь)."""
    return pipeline.purge_assets()


@shared_task(ignore_result=True, soft_time_limit=330, time_limit=360)
def build_showcase_clip(item_id):
    """Лёгкая копия ролика для витрины первого экрана (общая очередь).

    Лимит — с запасом над потолком самого ffmpeg (300 с в cartoon.clips): тот
    успеет сдаться сам, и работа останется в витрине с исходником.
    """
    from . import showcase

    return showcase.build_clip(item_id)
