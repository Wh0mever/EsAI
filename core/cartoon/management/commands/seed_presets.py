"""Разделы библиотеки и пресеты сцен студии мультфильмов.

Сами данные лежат в cartoon/library.py — ими пользуется и эта команда, и
админка при модерации пользовательских работ (раздел выбирается из того же
списка), поэтому держать их в одном месте важнее, чем рядом с командой.

Модели одинаковые у всех пресетов не случайно: кадр рисует Nano Banana (только
она удерживает персонажа по референсу и укладывается в секунды), а видео —
Seedance 2.0. Её выбрали после жалобы клиента на качество (17.09): она играет
реплику голосом персонажа с попаданием в губы, держит героя по референсу,
стыкует сцены по кадрам и умеет ровно пять секунд — у Veo пятисекундных сцен
нет вовсе. Сцена стоит дороже прежней Wan 2.7 (164 против 109 кредитов), и это
сознательный размен: клиент просил качество даже ценой цены.
У любого пресета модель меняется в админке, у всех сразу —
командой studio_video_model. Цена пересчитается сама.

Сцены и разделы, которые правили люди — в панели («Сцены мультстудии») или в
Django-админке, — команда не трогает даже с --force: владелец ведёт библиотеку
сам, и повторный прогон не должен откатывать его правки к тексту из кода.
Разделы, заведённые в панели, она не прячет, а удалённые там сцены не
возвращает.

Запуск:  python manage.py seed_presets [--force]
"""
from django.core.management.base import BaseCommand

from ai.models import GPTModels
from cartoon.library import (CATEGORIES, CATEGORY_TRANSLATIONS, EDITOR_PICKS, PRESETS,
                             PRESET_TRANSLATIONS, audience_of_preset, category_of,
                             style_for_preset)
from cartoon.models import CartoonCategory, CartoonPreset
from cartoon.panel import deleted_preset_slugs, people_edited


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
            openrouter_id="bytedance/seedance-2.0", is_active=True).first()
        if not image_model or not video_model:
            self.stderr.write(self.style.ERROR(
                "Нет нужных моделей: требуются google/gemini-2.5-flash-image "
                "и bytedance/seedance-2.0"))
            return

        edited_cats = people_edited(CartoonCategory)
        edited_presets = people_edited(CartoonPreset)
        deleted = deleted_preset_slugs()

        cats = {}
        kept_cats = 0
        for slug, title, emoji, order in CATEGORIES:
            cat = CartoonCategory.objects.filter(slug=slug).first()
            if cat is not None and cat.pk in edited_cats:
                # Название, порядок и показ такого раздела решает владелец.
                cats[slug] = cat
                kept_cats += 1
                continue
            tr = CATEGORY_TRANSLATIONS.get(slug, ("", ""))
            cat, _ = CartoonCategory.objects.update_or_create(
                slug=slug,
                defaults=dict(title=title, title_en=tr[0], title_kg=tr[1],
                              emoji=emoji, sort_order=order, is_active=True),
            )
            cats[slug] = cat
        # Прежние разделы, которых нет в новом списке, прячем: сцены из них уже
        # переехали, а пустая плитка в библиотеке хуже её отсутствия. Разделы
        # владельца в коде не значатся — их не трогаем.
        gone = (CartoonCategory.objects.exclude(slug__in=cats).exclude(pk__in=edited_cats)
                .update(is_active=False))
        self.stdout.write(self.style.SUCCESS(
            f"Разделов: {len(cats)}, убрано старых: {gone}, правленых в админке не тронуто: "
            f"{kept_cats}"))

        created = updated = skipped = kept = 0
        for order, (slug, title, subtitle, scene, motion, duration, cat_slug) in enumerate(PRESETS, start=1):
            tr = PRESET_TRANSLATIONS.get(slug)
            cat_slug = category_of(cat_slug, slug)
            audience = audience_of_preset(slug)
            preset = CartoonPreset.objects.filter(slug=slug).first()
            if (preset is not None and preset.pk in edited_presets) or (
                    preset is None and slug in deleted):
                # Сцену правили или удалили люди — их решение важнее кода.
                kept += 1
                continue
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
            f"Пресеты: создано {created}, обновлено {updated}, пропущено {skipped}, "
            f"правленых или удалённых в админке не тронуто: {kept}. "
            f"Всего: {CartoonPreset.objects.count()}"))
