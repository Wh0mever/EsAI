from django.db import migrations, models


def set_topmedia_kind(apps, schema_editor):
    TopMediaModels = apps.get_model('ai', 'TopMediaModels')
    for obj in TopMediaModels.objects.all().only('id', 'name'):
        name = (obj.name or '').strip()
        kind = 'voice_clone' if name in {'Gen', 'HD'} else 'music'
        TopMediaModels.objects.filter(pk=obj.pk).update(kind=kind)


class Migration(migrations.Migration):

    dependencies = [
        ('ai', '0003_topmediamodels'),
    ]

    operations = [
        migrations.AddField(
            model_name='topmediamodels',
            name='kind',
            field=models.CharField(
                choices=[('music', 'Music Generator'), ('voice_clone', 'Voice Cloning')],
                default='music',
                max_length=20,
            ),
        ),
        migrations.RunPython(set_topmedia_kind, migrations.RunPython.noop),
    ]
