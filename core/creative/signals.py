"""Файлы Creative Studio уходят вместе со строкой — откуда бы её ни удалили
(чистка, админка Django, удаление аккаунта CASCADE)."""
from __future__ import annotations

from django.db import transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import CreativeJob, CreativeUpload
from .storage import delete_files


@receiver(post_delete, sender=CreativeUpload, dispatch_uid="creative_upload_files")
def delete_upload_files(sender, instance, **kwargs):
    names = tuple(n for n in (instance.path, instance.thumb_path) if n)
    if names:
        # После коммита: откатившееся удаление не должно оставить строку без файлов.
        transaction.on_commit(lambda: delete_files(*names))


@receiver(post_delete, sender=CreativeJob, dispatch_uid="creative_job_files")
def delete_result_files(sender, instance, **kwargs):
    names = []
    for item in instance.result_files or []:
        if isinstance(item, dict):
            names += [n for n in (item.get("path"), item.get("poster")) if n]
    if names:
        transaction.on_commit(lambda: delete_files(*names))
