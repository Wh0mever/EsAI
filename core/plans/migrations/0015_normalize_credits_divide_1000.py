"""Нормализация биллинга ÷1000 (тариф владельца продукта): приводим ВЕСЬ ledger к новому
масштабу, где списание = total_tokens × тариф ÷ 1000.

Одноразово делим на 1000:
  * TokenPackage.tokens и bonus_tokens (Старт 150000→150, Про 450000→450, Бизнес
    1200000→1200) — деньги/цена не меняются, меняется только число кредитов;
  * User.token_balance всех пользователей — чтобы существующие балансы сохранили
    реальную ценность (иначе после ÷1000 списания баланс «жил» бы в 1000× дольше).

Welcome/daily-бонусы заданы в settings/.env (3 и 1) и здесь не трогаются.
Историю TokenTransaction НЕ переписываем — это честный аудит старого масштаба;
нормализация — разовое событие. На свежей БД (пакеты сеются 0013 в старом
масштабе, балансы ~0) миграция корректно приводит пакеты к новому масштабу.
"""
from django.db import migrations


def _rescale(value, factor):
    try:
        v = int(value or 0)
    except Exception:
        return 0
    return int(round(v / factor)) if factor else v


def forwards(apps, schema_editor):
    TokenPackage = apps.get_model("plans", "TokenPackage")
    User = apps.get_model("users", "User")

    for p in TokenPackage.objects.all():
        p.tokens = _rescale(p.tokens, 1000)
        p.bonus_tokens = _rescale(p.bonus_tokens, 1000)
        p.save(update_fields=["tokens", "bonus_tokens"])

    for u in User.objects.exclude(token_balance=0).iterator():
        new_bal = _rescale(u.token_balance, 1000)
        if new_bal != u.token_balance:
            u.token_balance = new_bal
            u.save(update_fields=["token_balance"])


def backwards(apps, schema_editor):
    TokenPackage = apps.get_model("plans", "TokenPackage")
    User = apps.get_model("users", "User")

    for p in TokenPackage.objects.all():
        p.tokens = int(p.tokens or 0) * 1000
        p.bonus_tokens = int(p.bonus_tokens or 0) * 1000
        p.save(update_fields=["tokens", "bonus_tokens"])

    for u in User.objects.exclude(token_balance=0).iterator():
        u.token_balance = int(u.token_balance or 0) * 1000
        u.save(update_fields=["token_balance"])


class Migration(migrations.Migration):

    dependencies = [
        ("plans", "0014_alter_tokentransaction_reason"),
        ("users", "0009_user_avatar_url"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
