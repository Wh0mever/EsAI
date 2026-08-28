"""Разделы библиотеки и пресеты сцен студии мультфильмов.

Сами данные лежат в cartoon/library.py — ими пользуется и эта команда, и
админка при модерации пользовательских работ (раздел выбирается из того же
списка), поэтому держать их в одном месте важнее, чем рядом с командой.

Модели одинаковые у всех пресетов не случайно: кадр рисует Nano Banana (только
она удерживает персонажа по референсу и укладывается в секунды), а видео —
Wan 2.7: 1080p со звуком, ролики от 2 секунд, и секунда дешевле, чем у Kling
или Seedance. У любого пресета модель меняется в админке — цена пересчитается
сама.

Запуск:  python manage.py seed_presets [--force]
"""
from django.core.management.base import BaseCommand

from ai.models import GPTModels
from cartoon.library import (CATEGORIES, CATEGORY_TRANSLATIONS, EDITOR_PICKS, PRESETS,
                             PRESET_TRANSLATIONS, audience_of_preset, category_of,
                             style_for_preset)
from cartoon.models import CartoonCategory, CartoonPreset


class Command(BaseCommand):
    help = "Завести разделы библиотеки и пресеты сцен студии мультфильмов"

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true",
                            help="Перезаписать промпты и настройки существующих пресетов")

    def handle(self, *args, **opts):
        force = bool(opts.get("force"))

        image_model = GPTModels.objects.filter(
            openrouter_id="google/gemini-2.5-flash-image", is_active=True).first()
        video_model = GPTModels.objects.filter(
            openrouter_id="alibaba/wan-2.7", is_active=True).first()
        if not image_model or not video_model:
            self.stderr.write(self.style.ERROR(
                "Нет нужных моделей: требуются google/gemini-2.5-flash-image и alibaba/wan-2.7"))
            return

        cats = {}
        for slug, title, emoji, order in CATEGORIES:
            tr = CATEGORY_TRANSLATIONS.get(slug, ("", ""))
            cat, _ = CartoonCategory.objects.update_or_create(
                slug=slug,
                defaults=dict(title=title, title_en=tr[0], title_kg=tr[1],
                              emoji=emoji, sort_order=order, is_active=True),
            )
            cats[slug] = cat
        # Прежние разделы, которых нет в новом списке, прячем: сцены из них уже
        # переехали, а пустая плитка в библиотеке хуже её отсутствия.
        gone = CartoonCategory.objects.exclude(slug__in=cats).update(is_active=False)
        self.stdout.write(self.style.SUCCESS(f"Разделов: {len(cats)}, убрано старых: {gone}"))

        created = updated = skipped = 0
        for order, (slug, title, subtitle, scene, motion, duration, cat_slug) in enumerate(PRESETS, start=1):
            tr = PRESET_TRANSLATIONS.get(slug)
            cat_slug = category_of(cat_slug, slug)
            audience = audience_of_preset(slug)
            preset = CartoonPreset.objects.filter(slug=slug).first()
            if preset and not force:
                # Раздел и переводы дописываем даже старым пресетам: они
                # появились позже, а промпты и снятые превью не трогаем —
                # пересъёмка каждой сцены стоит денег.
                fields = []
                # Раздел проставляем всегда: разделы перестроены, и старая
                # привязка ведёт в скрытую категорию.
                if cats.get(cat_slug) and preset.category_id != cats[cat_slug].id:
                    preset.category = cats[cat_slug]
                    fields.append("category")
                if preset.audience != audience:
                    preset.audience = audience
                    fields.append("audience")
                pick = slug in EDITOR_PICKS
                if preset.is_pick != pick:
                    preset.is_pick = pick
                    fields.append("is_pick")
                if tr and (preset.title != title or preset.subtitle != subtitle):
                    preset.title, preset.subtitle = title, subtitle
                    fields += ["title", "subtitle"]
                if tr:
                    preset.title_en, preset.subtitle_en = tr[0], tr[1]
                    preset.title_kg, preset.subtitle_kg = tr[2], tr[3]
                    fields += ["title_en", "subtitle_en", "title_kg", "subtitle_kg"]
                if fields:
                    preset.save(update_fields=fields)
                skipped += 1
                continue
            values = dict(
                title=title, subtitle=subtitle,
                title_en=tr[0] if tr else "", subtitle_en=tr[1] if tr else "",
                title_kg=tr[2] if tr else "", subtitle_kg=tr[3] if tr else "",
                scene_prompt=scene, motion_prompt=motion,
                style_prompt=style_for_preset(slug),
                image_model=image_model, video_model=video_model,
                duration=duration, aspect_ratio="16:9", resolution="720p",
                category=cats.get(cat_slug), audience=audience,
                is_pick=slug in EDITOR_PICKS,
                sort_order=order * 10, is_active=True,
            )
            if preset:
                for k, v in values.items():
                    setattr(preset, k, v)
                preset.save()
                updated += 1
            else:
                CartoonPreset.objects.create(slug=slug, **values)
                created += 1

        self.stdout.write(self.style.SUCCESS(
            f"Пресеты: создано {created}, обновлено {updated}, пропущено {skipped}. "
            f"Всего: {CartoonPreset.objects.count()}"))
