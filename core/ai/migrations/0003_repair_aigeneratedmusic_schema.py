from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("ai", "0002_initial"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
            ALTER TABLE ai_aigeneratedmusic
                ADD COLUMN IF NOT EXISTS lyrics text NOT NULL DEFAULT '',
                ADD COLUMN IF NOT EXISTS title varchar(255) NOT NULL DEFAULT '',
                ADD COLUMN IF NOT EXISTS instrumental boolean NOT NULL DEFAULT true,
                ADD COLUMN IF NOT EXISTS topmedia_task_id varchar(128) NOT NULL DEFAULT '',
                ADD COLUMN IF NOT EXISTS source_url varchar(200),
                ADD COLUMN IF NOT EXISTS audio varchar(100),
                ADD COLUMN IF NOT EXISTS meta jsonb;

            CREATE INDEX IF NOT EXISTS ai_aigeneratedmusic_topmedia_task_id_77df4a2e
                ON ai_aigeneratedmusic (topmedia_task_id);
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
