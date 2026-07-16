from django.db import migrations


# Канонический набор из 7 активных моделей ESAI (ТЗ 1.2, Этап 3).
#
# ВАЖНО про openrouter_id: для УЖЕ существующих моделей переиспользуем их рабочие
# id из прежних сид-миграций (0005_seed_openrouter_models) — чат на проде живой,
# ломать id нельзя. Обновляем только markup_coefficient, name и sort_order.
#
# Бесплатные (коэф. ≤ 1) идут первыми (sort_order 10, 20); далее R1 (×6) = 30,
# затем премиум ×15/×20 — 40+. DeepSeek R1 — ЗАМЕНА Mistral: создаём отдельной
# строкой по openrouter_id 'deepseek/deepseek-r1', а Mistral деактивируем.
#
# update_or_create по openrouter_id → идемпотентно (повторный прогон безопасен).
LINEUP = [
    # name,                openrouter_id,                                    coeff, sort_order
    ("DeepSeek V3",        "deepseek/deepseek-chat",                         "1",   10),
    ("Gemini 1.5 Flash",   "google/gemini-2.0-flash-001",                    "1",   20),
    ("DeepSeek R1",        "deepseek/deepseek-r1",                           "6",   30),
    ("ChatGPT",            "openai/gpt-4o",                                  "15",  40),
    ("Claude 3.5 Sonnet",  "anthropic/claude-3.5-sonnet",                    "15",  50),
    ("Grok",               "x-ai/grok-2-1212",                               "15",  60),
    ("Perplexity",         "perplexity/llama-3.1-sonar-large-128k-online",   "20",  70),
]

# Дефолт max_tokens для НОВЫХ строк (как в 0005). Существующим не трогаем —
# update_or_create в defaults перезапишет, поэтому для существующих НЕ кладём
# max_tokens в defaults, чтобы сохранить их текущее значение из админки.
DEFAULT_MAX_TOKENS = 4096

CANONICAL_IDS = {row[1] for row in LINEUP}


def seed_lineup(apps, schema_editor):
    GPTModels = apps.get_model("ai", "GPTModels")

    for name, openrouter_id, coeff, sort_order in LINEUP:
        existing = GPTModels.objects.filter(openrouter_id=openrouter_id).first()
        if existing:
            # Существующая модель: обновляем только коэф./имя/порядок/активность.
            # max_tokens и параметры генерации (system_prompt/temperature/top_p),
            # настроенные в админке, НЕ трогаем.
            existing.name = name
            existing.markup_coefficient = coeff
            existing.sort_order = sort_order
            existing.is_active = True
            existing.save(update_fields=[
                "name", "markup_coefficient", "sort_order", "is_active", "updated_at",
            ])
        else:
            # Новая модель (напр. DeepSeek R1) — создаём с дефолтным max_tokens.
            GPTModels.objects.create(
                name=name,
                openrouter_id=openrouter_id,
                markup_coefficient=coeff,
                sort_order=sort_order,
                is_active=True,
                max_tokens=DEFAULT_MAX_TOKENS,
                description="",
            )

    # Всё вне канонического набора (в т.ч. старый Mistral 'mistralai/mistral-large'
    # и любой легаси-каталог) — деактивируем, чтобы в выбор попадали только 7.
    GPTModels.objects.exclude(openrouter_id__in=CANONICAL_IDS).update(is_active=False)


class Migration(migrations.Migration):

    dependencies = [
        ("ai", "0008_aimessagefeedback"),
    ]

    operations = [
        migrations.RunPython(seed_lineup, migrations.RunPython.noop),
    ]
