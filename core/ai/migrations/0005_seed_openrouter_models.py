from django.db import migrations, models


# Default OpenRouter catalogue (managed/edited later from the admin).
SEED_MODELS = [
    {"name": "ChatGPT",    "openrouter_id": "openai/gpt-4o",                                   "markup_coefficient": "1.0", "sort_order": 10},
    {"name": "DeepSeek",   "openrouter_id": "deepseek/deepseek-chat",                          "markup_coefficient": "0.5", "sort_order": 20},
    {"name": "Gemini",     "openrouter_id": "google/gemini-2.0-flash-001",                     "markup_coefficient": "0.8", "sort_order": 30},
    {"name": "Claude",     "openrouter_id": "anthropic/claude-3.5-sonnet",                     "markup_coefficient": "1.4", "sort_order": 40},
    {"name": "Grok",       "openrouter_id": "x-ai/grok-2-1212",                                "markup_coefficient": "1.2", "sort_order": 50},
    {"name": "Mistral",    "openrouter_id": "mistralai/mistral-large",                         "markup_coefficient": "1.0", "sort_order": 60},
    {"name": "Perplexity", "openrouter_id": "perplexity/llama-3.1-sonar-large-128k-online",    "markup_coefficient": "1.1", "sort_order": 70},
]

DEFAULT_MAX_TOKENS = 4096


def backfill_and_seed(apps, schema_editor):
    GPTModels = apps.get_model("ai", "GPTModels")

    # 1) Backfill any pre-existing rows that have an empty openrouter_id so the
    #    unique constraint (applied below) does not collide on "".
    #    Use the existing (unique) name as the openrouter_id placeholder.
    for obj in GPTModels.objects.filter(openrouter_id=""):
        obj.openrouter_id = obj.name
        obj.save(update_fields=["openrouter_id"])

    # 2) Seed the default OpenRouter models. get_or_create keyed on openrouter_id
    #    so re-running / partial data does not duplicate rows.
    for row in SEED_MODELS:
        GPTModels.objects.get_or_create(
            openrouter_id=row["openrouter_id"],
            defaults={
                "name": row["name"],
                "markup_coefficient": row["markup_coefficient"],
                "sort_order": row["sort_order"],
                "max_tokens": DEFAULT_MAX_TOKENS,
                "is_active": True,
                "description": "",
            },
        )


def unseed(apps, schema_editor):
    GPTModels = apps.get_model("ai", "GPTModels")
    seeded_ids = [row["openrouter_id"] for row in SEED_MODELS]
    GPTModels.objects.filter(openrouter_id__in=seeded_ids).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('ai', '0004_gptmodels_openrouter_fields'),
    ]

    operations = [
        migrations.RunPython(backfill_and_seed, unseed),
        migrations.AlterField(
            model_name='gptmodels',
            name='openrouter_id',
            field=models.CharField(
                default='',
                help_text="Системный ID модели в OpenRouter (напр. 'openai/gpt-4o')",
                max_length=128,
                unique=True,
            ),
        ),
    ]
