from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
            CREATE TABLE IF NOT EXISTS users_usercardbind (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL REFERENCES users_user(id) DEFERRABLE INITIALLY DEFERRED,
                card_id VARCHAR(64) NOT NULL,
                card_token VARCHAR(128) NOT NULL,
                card_hash VARCHAR(32) NOT NULL,
                card_month VARCHAR(2) NOT NULL,
                card_year VARCHAR(2) NOT NULL,
                card_bank VARCHAR(64) NOT NULL,
                card_country VARCHAR(2) NOT NULL,
                card_3ds BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS users_usercardbind_user_id_idx ON users_usercardbind(user_id);
            """,
            reverse_sql="""
            DROP TABLE IF EXISTS users_usercardbind;
            """,
        ),
    ]

