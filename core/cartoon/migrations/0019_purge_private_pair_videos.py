"""Убрать из общего запаса ролики пар, снятые до проверки на личное.

remember_pair_video теперь не кладёт в запас сцену с репликой человека или с
кадром «с оглядкой» на его прошлую сцену (там его комната и его герои, вплоть
до загруженных фото). Но ролики, попавшие туда раньше, так и показывались всем
гостям в витрине и ленте. Оставляем только те, что проходят ту же проверку;
ролик, который проверить нельзя (съёмку удалили), убираем, только если он снят
после появления реплик — пара снова наполнится со следующей чистой съёмки.

Сам ролик — файл сцены человека, его не трогаем. Лёгкую копию
(cartoon/pairs/<сцена>-<герой>.mp4, путь угадывается) удаляем из хранилища.
"""
import logging
from datetime import datetime, timezone as dt_timezone

from django.db import migrations

logger = logging.getLogger(__name__)


# Реплики героя и кадры «с оглядкой» на прошлую сцену появились 21.09.2026
# (коммит 3c8def7). Ролик, снятый раньше, личного содержать не мог — даже если
# его съёмку потом удалили или пересняли. Такие ролики оставляем: иначе
# витрина студии разом потеряла бы почти все готовые превью.
PERSONAL_FEATURES_SINCE = datetime(2026, 9, 20, tzinfo=dt_timezone.utc)


def _shareable(row, keyframes) -> bool:
    scene = row.source_scene
    if row.character.user_id is not None:
        return False
    if scene is not None and ((scene.custom_text or "").strip() or (scene.dialogue or "").strip()):
        return False
    checkable = scene is not None and scene.keyframe and scene.video == row.video
    if not checkable:
        # Проверить нельзя: опасно только то, что снято после появления реплик.
        return bool(row.created_at and row.created_at < PERSONAL_FEATURES_SINCE)
    return keyframes.filter(preset_id=row.preset_id, character_id=row.character_id,
                            image=scene.keyframe).exists()


def purge_private_pair_videos(apps, schema_editor):
    from django.core.files.storage import default_storage

    CartoonPairVideo = apps.get_model("cartoon", "CartoonPairVideo")
    CartoonKeyframe = apps.get_model("cartoon", "CartoonKeyframe")

    removed = 0
    for row in CartoonPairVideo.objects.select_related("source_scene", "character").order_by("id"):
        if _shareable(row, CartoonKeyframe.objects):
            continue
        clip = row.clip or ""
        row.delete()
        removed += 1
        if clip.startswith("cartoon/pairs/") and clip != row.video:
            try:
                default_storage.delete(clip)
            except Exception:
                logger.warning("ролик пары: лёгкая копия %s не удалилась", clip)
    if removed:
        logger.warning("общий запас роликов пар: убрано %s непроверяемых или личных", removed)


class Migration(migrations.Migration):

    dependencies = [
        ('cartoon', '0018_project_assembly_started_at'),
    ]

    operations = [
        migrations.RunPython(purge_private_pair_videos, migrations.RunPython.noop),
    ]
