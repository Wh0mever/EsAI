"""Нормализация биллинга (тариф владельца продукта): расцепляем «бесплатность» модели от
коэффициента и переводим markup_coefficient в ТАРИФ (кредитов за 1000 токенов).

1) Добавляем поле free_tier (явный флаг доступности на бесплатном тарифе).
2) Выставляем тарифы владельца продукта и free-флаги для активных моделей по openrouter_id:

   DeepSeek V3   deepseek/deepseek-chat       тариф 1   FREE
   Gemini Flash  google/gemini-2.5-flash      тариф 11  FREE
   DeepSeek R1   deepseek/deepseek-r1         тариф 7   премиум
   ChatGPT       openai/gpt-4o                тариф 17  премиум
   Claude Sonnet anthropic/claude-sonnet-4.5  тариф 17  премиум
   Grok          x-ai/grok-4.3                тариф 4   премиум
   Perplexity    perplexity/sonar             тариф 17  премиум

Списание считается как total_tokens × тариф ÷ 1000 (settings.TOKEN_CREDIT_DIVISOR).
"""
from decimal import Decimal

from django.db import migrations, models


# (openrouter_id) -> (тариф кредитов за 1000 токенов, free_tier)
OWNER_RATES = {
    "deepseek/deepseek-chat":      ("1",  True),
    "google/gemini-2.5-flash":     ("11", True),
    "deepseek/deepseek-r1":        ("7",  False),
    "openai/gpt-4o":               ("17", False),
    "anthropic/claude-sonnet-4.5": ("17", False),
    "x-ai/grok-4.3":               ("4",  False),
    "perplexity/sonar":            ("17", False),
}

# Прежние коэффициенты (для обратной миграции) + старое правило free = коэф. ≤ 1.
LEGACY_RATES = {
    "deepseek/deepseek-chat":      ("1",  True),
    "google/gemini-2.5-flash":     ("1",  True),
    "deepseek/deepseek-r1":        ("6",  False),
    "openai/gpt-4o":               ("15", False),
    "anthropic/claude-sonnet-4.5": ("15", False),
    "x-ai/grok-4.3":               ("15", False),
    "perplexity/sonar":            ("20", False),
}


def _apply(model, table):
    for orid, (coeff, free) in table.items():
        model.objects.filter(openrouter_id=orid).update(
            markup_coefficient=Decimal(coeff), free_tier=free
        )


def forwards(apps, schema_editor):
    _apply(apps.get_model("ai", "GPTModels"), OWNER_RATES)


def backwards(apps, schema_editor):
    _apply(apps.get_model("ai", "GPTModels"), LEGACY_RATES)


class Migration(migrations.Migration):

    dependencies = [
        ("ai", "0012_gptmodels_supports_vision"),
    ]

    operations = [
        migrations.AddField(
            model_name="gptmodels",
            name="free_tier",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Доступна гостям и бесплатным пользователям. НЕ зависит от "
                    "тарифа: бесплатная модель тоже списывает кредиты, просто не "
                    "заблокирована пэйволом."
                ),
            ),
        ),
        migrations.RunPython(forwards, backwards),
    ]
