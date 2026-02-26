from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("ai", "0003_repair_aigeneratedmusic_schema"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
            ALTER TABLE ai_aigeneratedmusic
                ALTER COLUMN response_text SET DEFAULT '',
                ALTER COLUMN audio_url SET DEFAULT '';

            UPDATE ai_aigeneratedmusic
               SET response_text = COALESCE(response_text, ''),
                   audio_url = COALESCE(audio_url, '');
            """,
            reverse_sql="""
            ALTER TABLE ai_aigeneratedmusic
                ALTER COLUMN response_text DROP DEFAULT,
                ALTER COLUMN audio_url DROP DEFAULT;
            """,
        ),
    ]

