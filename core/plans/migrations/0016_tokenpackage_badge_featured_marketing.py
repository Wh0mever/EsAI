"""Маркетинговые правки тарифов (запрос владельца продукта):
поля badge/featured + новый состав 4 пакетов.

  Старт    150 кр / 190 сом   бейдж «Для знакомства»
  Про      500 кр / 490 сом   бейдж «⭐ Популярный»        (выделенный)
  Премиум 1300 кр / 990 сом   бейдж «🔥 Лучший выбор»       (переименован из «Бизнес», id сохраняется)
  Максимум 2800 кр / 1990 сом бейдж «💎 Самая выгодная цена» (новый)

Старый пакет «Стандарт» (inactive) не трогаем. Числа — уже в новом масштабе
(после нормализации ÷1000, plans/0015).
"""
from decimal import Decimal

from django.db import migrations, models


def forwards(apps, schema_editor):
    TokenPackage = apps.get_model("plans", "TokenPackage")

    # Бизнес -> Премиум (сохраняем id/историю покупок).
    biz = TokenPackage.objects.filter(name="Бизнес").first()
    if biz:
        biz.name = "Премиум"
        biz.tokens = 1300
        biz.bonus_tokens = 0
        biz.price = Decimal("990")
        biz.currency = "KGS"
        biz.badge = "🔥 Лучший выбор"
        biz.featured = False
        biz.description = "Для команды и тяжёлых файлов"
        biz.sort_order = 30
        biz.is_active = True
        biz.save()

    TokenPackage.objects.filter(name="Старт").update(
        tokens=150, bonus_tokens=0, price=Decimal("190"), currency="KGS",
        badge="Для знакомства", featured=False,
        description="Для знакомства с EsAI", sort_order=10, is_active=True,
    )
    TokenPackage.objects.filter(name="Про").update(
        tokens=500, bonus_tokens=0, price=Decimal("490"), currency="KGS",
        badge="⭐ Популярный", featured=True,
        description="Для копирайтеров, SMM и маркетологов", sort_order=20, is_active=True,
    )
    TokenPackage.objects.update_or_create(
        name="Максимум",
        defaults=dict(
            tokens=2800, bonus_tokens=0, price=Decimal("1990"), currency="KGS",
            badge="💎 Самая выгодная цена", featured=False,
            description="Максимум кредитов по лучшей цене", sort_order=40, is_active=True,
        ),
    )


def backwards(apps, schema_editor):
    TokenPackage = apps.get_model("plans", "TokenPackage")
    TokenPackage.objects.filter(name="Максимум").delete()
    prem = TokenPackage.objects.filter(name="Премиум").first()
    if prem:
        prem.name = "Бизнес"
        prem.tokens = 1200
        prem.price = Decimal("990")
        prem.description = ""
        prem.sort_order = 30
        prem.save()
    TokenPackage.objects.filter(name="Про").update(tokens=450, price=Decimal("490"), description="")
    TokenPackage.objects.filter(name="Старт").update(tokens=150, price=Decimal("190"), description="")


class Migration(migrations.Migration):

    dependencies = [
        ("plans", "0015_normalize_credits_divide_1000"),
    ]

    operations = [
        migrations.AddField(
            model_name="tokenpackage",
            name="badge",
            field=models.CharField(
                blank=True, default="", max_length=60, verbose_name="Бейдж",
                help_text="Маркетинговая плашка над пакетом, напр. «⭐ Популярный», «🔥 Лучший выбор». Пусто — без бейджа.",
            ),
        ),
        migrations.AddField(
            model_name="tokenpackage",
            name="featured",
            field=models.BooleanField(
                default=False, verbose_name="Выделенный",
                help_text="Визуально выделить пакет (рамка/увеличение) как рекомендованный. Включайте только у ОДНОГО пакета.",
            ),
        ),
        migrations.AlterField(
            model_name="tokenpackage",
            name="tokens",
            field=models.BigIntegerField(verbose_name="Кредитов"),
        ),
        migrations.AlterField(
            model_name="tokenpackage",
            name="bonus_tokens",
            field=models.BigIntegerField(default=0, verbose_name="Бонусных кредитов"),
        ),
        migrations.AlterField(
            model_name="tokenpackage",
            name="description",
            field=models.TextField(blank=True, verbose_name="Описание (подпись под пакетом)"),
        ),
        migrations.RunPython(forwards, backwards),
    ]
