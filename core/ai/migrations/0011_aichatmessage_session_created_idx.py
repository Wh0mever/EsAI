from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ai', '0010_fix_model_openrouter_ids'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='aichatmessage',
            index=models.Index(fields=['session', 'created_at'], name='ai_msg_session_created_idx'),
        ),
    ]
