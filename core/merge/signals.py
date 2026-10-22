"""Файлы склейки и своих видео уходят вместе со строкой — откуда бы её ни удалили.

API стирает файлы само (services.delete_project), но строку удаляют и мимо
него: админка Django, удаление аккаунта (CASCADE). Без этого ролик и обложка
оставались бы на диске навсегда: уборка истёкших ищет файлы по строкам.
"""
from __future__ import annotations

from django.db import transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import MergeAudio, MergeProject, MergeUpload
from .storage import delete_files


@receiver(post_delete, sender=MergeProject, dispatch_uid="merge_project_files")
def delete_result_files(sender, instance, **kwargs):
    names = tuple(n for n in (instance.result_video, instance.poster) if n)
    if names:
        # После коммита: откатившееся удаление не должно оставить строку без файлов.
        transaction.on_commit(lambda: delete_files(*names))


@receiver(post_delete, sender=MergeUpload, dispatch_uid="merge_upload_files")
def delete_upload_files(sender, instance, **kwargs):
    # Своё видео: удаление в «Моих файлах», уборка, удаление аккаунта.
    names = tuple(n for n in (instance.file, instance.poster) if n)
    if names:
        transaction.on_commit(lambda: delete_files(*names))


@receiver(post_delete, sender=MergeAudio, dispatch_uid="merge_audio_files")
def delete_audio_file(sender, instance, **kwargs):
    # Звук склейки: замена дорожки, «убрать», удаление склейки (CASCADE), уборка.
    if instance.file:
        name = instance.file
        transaction.on_commit(lambda: delete_files(name))
    # Музыка, что ещё стояла в очереди (склейку удалили в админке или вместе с аккаунтом —
    # API такую склейку не удаляет, MA_FIX4): её место на сайте свободно сразу, а не через
    # срок ключа. Начатую отпускает её задача: провайдер ещё занят ею.
    if (instance.kind == MergeAudio.KIND_MUSIC and instance.status == MergeAudio.STATUS_PENDING
            and instance.started_at is None):
        from .audio import drop_music_slot

        token = instance.uid
        transaction.on_commit(lambda: drop_music_slot(token))
