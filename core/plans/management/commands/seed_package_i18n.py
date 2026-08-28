"""Первое заполнение переводов пакетов кредитов.

Перевод пакета — это текст клиента из админки, и придумывать его за клиента
команда не должна. Но пока поля пустые, на английской и кыргызской витрине
среди переведённого интерфейса стоят русские «Старт» и «Выбор большинства»,
поэтому стартовые значения проставляются здесь — по текущему русскому тексту.

Правила намеренно осторожные:
  * пишем только в ПУСТЫЕ поля — уже введённый клиентом перевод не трогаем;
  * узнаём пакет по русскому тексту, а не по id: если клиент переименовал
    пакет, значит, он им занимается, и подставлять свои слова нельзя.

Запуск:  python manage.py seed_package_i18n
"""
from django.core.management.base import BaseCommand

from plans.models import TokenPackage

# русский текст -> (en, kg)
NAMES = {
    "✨Старт": ("✨ Start", "✨ Старт"),
    "Стандарт": ("Standard", "Стандарт"),
    "⭐ Про": ("⭐ Pro", "⭐ Про"),
    "🔥 Премиум": ("🔥 Premium", "🔥 Премиум"),
    "💎 Максимум": ("💎 Maximum", "💎 Максимум"),
}

BADGES = {
    "Для знакомства": ("To get started", "Таанышуу үчүн"),
    "⭐ Популярный": ("⭐ Popular", "⭐ Популярдуу"),
    "Лучший выбор": ("Best choice", "Мыкты тандоо"),
    "Самая выгодная цена": ("Best value", "Эң ыңгайлуу баа"),
}

DESCRIPTIONS = {
    "✨ Попробуйте EsAI": ("✨ Try EsAI", "✨ EsAI'ди сынап көрүңүз"),
    "⭐ Выбор большинства": ("⭐ What most people pick", "⭐ Көпчүлүктүн тандоосу"),
    "🔥 Работайте без ограничений": ("🔥 Work without limits", "🔥 Чектөөсүз иштеңиз"),
    "💎 Лучшая цена за кредит": ("💎 Best price per credit", "💎 Кредиттин эң жакшы баасы"),
}

FIELDS = (("name", NAMES), ("badge", BADGES), ("description", DESCRIPTIONS))


class Command(BaseCommand):
    help = "Проставить переводы названий, бейджей и подписей пакетов там, где они пусты"

    def handle(self, *args, **opts):
        filled = skipped = 0
        for pkg in TokenPackage.objects.all().order_by("sort_order", "id"):
            changed = []
            for field, table in FIELDS:
                source = (getattr(pkg, field, "") or "").strip()
                pair = table.get(source)
                if not pair:
                    continue
                for lang, value in zip(("en", "kg"), pair):
                    attr = f"{field}_{lang}"
                    if (getattr(pkg, attr, "") or "").strip():
                        continue
                    setattr(pkg, attr, value)
                    changed.append(attr)
            if changed:
                pkg.save(update_fields=changed)
                filled += 1
                self.stdout.write(f"  {pkg.name}: {', '.join(changed)}")
            else:
                skipped += 1

        self.stdout.write(self.style.SUCCESS(
            f"Пакетов заполнено: {filled}, без изменений: {skipped}"))
