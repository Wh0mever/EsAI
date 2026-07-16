from django.db import migrations

# Исправление устаревших openrouter_id (старые версии сняты с OpenRouter → 404
# "No endpoints found"). Актуальные id подтверждены live-тестом 2026-06-29.
# (old_openrouter_id, new_openrouter_id, display_name)
RENAMES = [
    ("google/gemini-2.0-flash-001", "google/gemini-2.5-flash", "Gemini Flash"),
    ("anthropic/claude-3.5-sonnet", "anthropic/claude-sonnet-4.5", "Claude Sonnet"),
    ("x-ai/grok-2-1212", "x-ai/grok-4.3", "Grok"),
    ("perplexity/llama-3.1-sonar-large-128k-online", "perplexity/sonar", "Perplexity"),
]


def fix_ids(apps, schema_editor):
    GPTModels = apps.get_model("ai", "GPTModels")
    for old, new, name in RENAMES:
        # Если новый id уже стоит (исправлено вручную на проде) — пропускаем.
        if GPTModels.objects.filter(openrouter_id=new).exists():
            continue
        m = GPTModels.objects.filter(openrouter_id=old).first()
        if m:
            m.openrouter_id = new
            m.name = name
            m.save(update_fields=["openrouter_id", "name"])


class Migration(migrations.Migration):
    dependencies = [("ai", "0009_seed_canonical_model_lineup")]
    operations = [migrations.RunPython(fix_ids, migrations.RunPython.noop)]
