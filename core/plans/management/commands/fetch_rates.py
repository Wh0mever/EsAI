from django.core.management.base import BaseCommand, CommandError
from plans.services import update_currency_rates

class Command(BaseCommand):
    help = "Fetch RUB/KGS rates vs USD and store them."

    def handle(self, *args, **options):
        try:
            rates = update_currency_rates()
        except Exception as e:
            raise CommandError(str(e))
        for code, val in rates.items():
            self.stdout.write(self.style.SUCCESS(f"{code}: {val} USD"))