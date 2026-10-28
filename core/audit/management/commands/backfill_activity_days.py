"""python manage.py backfill_activity_days [--since YYYY-MM-DD]

Восстановить дни активности (отчёт «Возвраты») по уже существующим таблицам:
регистрации, входы и продления сессии, траты и покупки кредитов, оплаты,
созданные чаты/проекты/герои. Разовый запуск при выкладке; повторный запуск
безопасен — уже записанные дни не дублируются и не переписываются.
"""
from __future__ import annotations

from datetime import date

from django.core.management.base import BaseCommand, CommandError

from audit.activity import sync_sources_detailed


class Command(BaseCommand):
    help = "Восстановить дни активности пользователей из истории (идемпотентно)."

    def add_arguments(self, parser):
        parser.add_argument("--since", default=None,
                            help="С какого местного дня брать (YYYY-MM-DD). По умолчанию — вся история.")

    def handle(self, *args, **options):
        since = None
        if options.get("since"):
            try:
                since = date.fromisoformat(options["since"])
            except ValueError:
                raise CommandError("--since: нужна дата в виде YYYY-MM-DD") from None

        results = sync_sources_detailed(since)
        total = 0
        for r in results:
            if r["error"]:
                # Пропущенный источник видно в выводе: иначе «добавлено 0»
                # не отличить от «источник сломан».
                self.stdout.write(f"{r['source']}: ПРОПУЩЕН ({r['error']})")
                continue
            total += r["added"]
            self.stdout.write(f"{r['source']}: найдено {r['found']}, добавлено {r['added']}")
        self.stdout.write(f"Итого добавлено: {total}")
