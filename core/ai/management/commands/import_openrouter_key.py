"""Перенести действующий ключ OpenRouter в аккаунты панели.

Ключ жил строкой в настройках, а теперь у него есть карточка с балансом и
переключателем. Команда заводит из текущего ключа первый аккаунт, чтобы
панель не открывалась пустой, а сайт продолжал работать на том же ключе.

Запуск:  python manage.py import_openrouter_key
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from adminapi.openrouter import check_key
from ai.models import OpenRouterAccount


class Command(BaseCommand):
    help = "Завести аккаунт OpenRouter из ключа, который используется сейчас"

    def handle(self, *args, **opts):
        from ai.handlers import _openrouter_config

        key = (_openrouter_config().get("api_key") or "").strip()
        if not key:
            self.stderr.write(self.style.ERROR("Действующего ключа нет — переносить нечего"))
            return
        if OpenRouterAccount.objects.filter(api_key=key).exists():
            self.stdout.write("Этот ключ уже заведён")
            return

        res = check_key(key)
        account = OpenRouterAccount.objects.create(
            title="Основной",
            api_key=key,
            note="Перенесён из настроек при переходе на аккаунты.",
            balance_usd=res.get("balance"), spent_usd=res.get("spent"),
            limit_usd=res.get("limit"), checked_at=timezone.now(),
            last_error="" if res["ok"] else (res.get("error") or ""),
            is_active=not OpenRouterAccount.objects.filter(is_active=True).exists(),
        )
        self.stdout.write(self.style.SUCCESS(
            f"Заведён «{account.title}» ({account.masked_key()}), "
            f"баланс ${account.balance_usd}"))
