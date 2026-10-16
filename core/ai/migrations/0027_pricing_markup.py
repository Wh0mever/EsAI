# Цены по себестоимости (BUILD_A): своя наценка модели и себестоимость картинки.
# Схема — новые необязательные поля; данные — себестоимость известных картинок
# по прайсу вендора (PLAN §3.3), только там, где поле ещё пусто. Откат схемы —
# migrate назад; откат данных не нужен: в режиме legacy поля не читаются.

import django.core.validators
from decimal import Decimal

from django.db import migrations, models

# openrouter_id → (за картинку, за входное фото). Цифры — прайс вендора на
# 14.10.2026; FLUX Klein сверен с журналом генераций. Nano Banana 2 — прайс Google
# за картинку 1K ($60 за 1M токенов картинки × 1120). Владелец правит их в «Моделях».
IMAGE_COSTS = {
    "black-forest-labs/flux.2-klein-4b": ("0.015", None),
    "black-forest-labs/flux.2-pro": ("0.03", None),
    "black-forest-labs/flux.2-flex": ("0.06", "0.06"),
    "black-forest-labs/flux.2-max": ("0.07", None),
    "google/gemini-2.5-flash-image": ("0.039", None),
    "google/gemini-2.5-flash-image-preview": ("0.039", None),
    "google/gemini-3.1-flash-image": ("0.067", None),
    "google/gemini-3.1-flash-image-preview": ("0.067", None),
    "google/gemini-3-pro-image": ("0.134", None),
    "google/gemini-3-pro-image-preview": ("0.134", None),
}


def prefill_image_costs(apps, schema_editor):
    GPTModels = apps.get_model("ai", "GPTModels")
    for orid, (unit, ref) in IMAGE_COSTS.items():
        GPTModels.objects.filter(openrouter_id=orid, unit_cost_usd__isnull=True).update(
            unit_cost_usd=Decimal(unit))
        if ref is not None:
            GPTModels.objects.filter(openrouter_id=orid, ref_cost_usd__isnull=True).update(
                ref_cost_usd=Decimal(ref))


class Migration(migrations.Migration):

    dependencies = [
        ('ai', '0026_vstudio'),
    ]

    operations = [
        migrations.AddField(
            model_name='gptmodels',
            name='markup_pct',
            field=models.DecimalField(blank=True, decimal_places=2, help_text='Своя наценка к себестоимости OpenRouter. Пусто — общая из настроек цен.', max_digits=6, null=True, validators=[django.core.validators.MinValueValidator(0), django.core.validators.MaxValueValidator(1000)], verbose_name='Наценка, %'),
        ),
        migrations.AddField(
            model_name='gptmodels',
            name='ref_cost_usd',
            field=models.DecimalField(blank=True, decimal_places=6, help_text='Доплата OpenRouter за каждое входное фото (FLUX Flex). Пусто — бесплатно.', max_digits=10, null=True, validators=[django.core.validators.MinValueValidator(0)], verbose_name='Себестоимость входного фото, $'),
        ),
        migrations.AddField(
            model_name='gptmodels',
            name='unit_cost_usd',
            field=models.DecimalField(blank=True, decimal_places=6, help_text='Сколько OpenRouter берёт за одну картинку. Пусто — в режиме «наценка» остаётся прежняя плоская цена.', max_digits=10, null=True, validators=[django.core.validators.MinValueValidator(0)], verbose_name='Себестоимость картинки, $'),
        ),
        migrations.AlterField(
            model_name='gptmodels',
            name='markup_coefficient',
            field=models.DecimalField(decimal_places=3, default=1.0, help_text='ТАРИФ: текст — кредитов за 1000 токенов (списание = total_tokens × тариф ÷ 1000); FLUX — кредитов за картинку; другие картинки (Nano Banana) — в чате кредитов за 1000 токенов, в студиях кредитов за картинку; видео — кредитов за секунду 720p. В режиме цен «наценка» видео и картинки с себестоимостью считаются без тарифа — кроме картинок Nano Banana в чате: там тариф действует всегда.', max_digits=6),
        ),
        migrations.RunPython(prefill_image_costs, migrations.RunPython.noop),
    ]
