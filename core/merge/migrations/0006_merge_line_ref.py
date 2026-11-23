# «Голос сцены»: ролик фрагмента (тип:id) у дорожки — ролик убрали и вернули в склейку,
# голос находит его новую карточку (services.adopt_orphan_keys). Существующие строки —
# пустая метка (без возврата, как раньше).

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('merge', '0005_merge_scene_lines'),
    ]

    operations = [
        migrations.AddField(
            model_name='mergeaudio',
            name='fragment_ref',
            field=models.CharField(blank=True, default='', max_length=80, verbose_name='Ролик голоса сцены'),
        ),
    ]
