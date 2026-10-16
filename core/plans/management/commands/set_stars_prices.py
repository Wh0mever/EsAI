# -*- coding: utf-8 -*-
"""Проставить пакетам цену в Telegram Stars по формуле «выручка как с сомов».

    manage.py set_stars_prices            # показать подсказки
    manage.py set_stars_prices --apply    # записать тем, у кого цены ещё нет
    manage.py set_stars_prices --apply --overwrite

Цена потом правится в админке; команда нужна для первого запуска.
"""
from django.core.management.base import BaseCommand

from plans.models import TokenPackage
from plans.stars import kgs_to_usd_rate, price_drift, suggest_stars_price


class Command(BaseCommand):
    help = "Цены пакетов в Telegram Stars по курсу"

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--overwrite", action="store_true")

    def handle(self, *args, **options):
        rate = kgs_to_usd_rate()
        self.stdout.write(f"курс сом→$: {rate}")
        for package in TokenPackage.objects.filter(is_active=True).order_by("sort_order", "id"):
            suggested = suggest_stars_price(package)
            drift = price_drift(package)
            line = (f"#{package.id} {package.name}: {package.price} {package.currency} → "
                    f"подсказка {suggested} ⭐, сейчас {package.stars_price or '—'}")
            if drift is not None:
                line += f" (расхождение {drift:+.1f}%)"
            self.stdout.write(line)
            if options["apply"] and suggested and (options["overwrite"] or not package.stars_price):
                package.stars_price = suggested
                package.save(update_fields=["stars_price"])
                self.stdout.write(self.style.SUCCESS(f"  записано {suggested} ⭐"))
        if options["apply"]:
            # Пакет за звёзды тоже может оказаться самым дешёвым кредитом — основой цен.
            from ai.pricing import invalidate_price_caches

            invalidate_price_caches()
