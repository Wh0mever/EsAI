"""Файлы склейки уходят вместе со строкой — откуда бы её ни удалили.

API стирает файлы само (services.delete_project), но строку удаляют и мимо
него: админка Django, удаление аккаунта (CASCADE). Без этого ролик и обложка
оставались бы на диске навсегда: уборка истёкших ищет файлы по строкам.
"""
from __future__ import annotations

from django.db import transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import MergeProject
from .storage import delete_files


@receiver(post_delete, sender=MergeProject, dispatch_uid="merge_project_files")
def delete_result_files(sender, instance, **kwargs):
    names = tuple(n for n in (instance.result_video, instance.poster) if n)
    if names:
        # После коммита: откатившееся удаление не должно оставить строку без файлов.
        transaction.on_commit(lambda: delete_files(*names))
