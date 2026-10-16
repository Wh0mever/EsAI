"""Ролик пары «герой в сцене» — ещё и по формату.

Раньше ключ был (сцена, герой), и вертикальный ролик показывался в
горизонтальном мультфильме. Теперь формат — часть ключа, как у кадров
(CartoonKeyframe). Готовые ролики остаются: формат берём у мультфильма, из
которого ролик снят; съёмку удалили — формат пресета (почти всегда 16:9).
"""
from django.db import migrations, models


def fill_aspect(apps, schema_editor):
    CartoonPairVideo = apps.get_model("cartoon", "CartoonPairVideo")
    for row in CartoonPairVideo.objects.select_related("source_scene__project", "preset").order_by("id"):
        scene = row.source_scene
        aspect = ((scene.project.aspect_ratio if scene is not None and scene.project_id else "")
                  or (row.preset.aspect_ratio if row.preset_id else "") or "16:9")
        if aspect != row.aspect_ratio:
            row.aspect_ratio = aspect
            row.save(update_fields=["aspect_ratio"])


class Migration(migrations.Migration):

    dependencies = [
        ('cartoon', '0020_dock_settings'),
    ]

    operations = [
        migrations.AddField(
            model_name='cartoonpairvideo',
            name='aspect_ratio',
            field=models.CharField(default='16:9', max_length=8, verbose_name='Формат'),
        ),
        migrations.RunPython(fill_aspect, migrations.RunPython.noop),
        migrations.AlterUniqueTogether(
            name='cartoonpairvideo',
            unique_together={('preset', 'character', 'aspect_ratio')},
        ),
    ]
