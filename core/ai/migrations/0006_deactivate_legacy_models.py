from django.db import migrations

# Канонические 7 моделей ESAI на старте (см. 0005_seed_openrouter_models).
# Всё остальное (старый каталог OpenAI из прежней синхронизации Vokalo) деактивируем,
# чтобы в выбор моделей пользователю попадали только эти. Управление — из админки.
CANONICAL = {
    "openai/gpt-4o",
    "deepseek/deepseek-chat",
    "google/gemini-2.0-flash-001",
    "anthropic/claude-3.5-sonnet",
    "x-ai/grok-2-1212",
    "mistralai/mistral-large",
    "perplexity/llama-3.1-sonar-large-128k-online",
}


def deactivate_legacy(apps, schema_editor):
    GPTModels = apps.get_model("ai", "GPTModels")
    GPTModels.objects.exclude(openrouter_id__in=CANONICAL).update(is_active=False)


def noop(apps, schema_editor):
    # Необратимо по дизайну: не реактивируем легаси-модели.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("ai", "0005_seed_openrouter_models"),
    ]
    operations = [
        migrations.RunPython(deactivate_legacy, noop),
    ]
