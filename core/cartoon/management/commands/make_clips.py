"""Сделать лёгкие копии превью для автопроигрывания в ленте.

Снятый ролик весит около 3.5 МБ, и шесть таких на экране — это двадцать
мегабайт мобильного трафика. Команда добивает облегчённые копии тем сценам,
у которых их ещё нет.

Запуск:  python manage.py make_clips [--force]
"""
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand

from cartoon.clips import make_clip
from cartoon.models import CartoonPreset


class Command(BaseCommand):
    help = "Сделать лёгкие копии превью сцен для ленты"

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true",
                            help="Пересоздать даже там, где копия уже есть")

    def handle(self, *args, **opts):
        force = bool(opts.get("force"))
        qs = CartoonPreset.objects.exclude(preview_video="")
        if not force:
            qs = qs.filter(preview_clip="")
        total = qs.count()
        self.stdout.write(self.style.MIGRATE_HEADING(f"Лёгкие копии: {total} сцен"))

        done = failed = 0
        before = after = 0
        for i, p in enumerate(qs, start=1):
            try:
                with default_storage.open(p.preview_video.name, "rb") as fh:
                    blob = fh.read()
            except Exception:
                failed += 1
                self.stderr.write(self.style.WARNING(f"  не читается: {p.slug}"))
                continue
            clip = make_clip(blob)
            if not clip:
                failed += 1
                self.stderr.write(self.style.WARNING(f"  не вышло: {p.slug}"))
                continue
            before += len(blob)
            after += len(clip)
            p.preview_clip.save(f"{p.slug}.mp4", ContentFile(clip), save=False)
            p.save(update_fields=["preview_clip"])
            done += 1
            if i % 10 == 0 or i == total:
                self.stdout.write(f"  {i}/{total}")

        if before:
            self.stdout.write(
                f"Вес: было {before / 1048576:.0f} МБ, стало {after / 1048576:.0f} МБ "
                f"({after * 100 // before}%)")
        self.stdout.write(self.style.SUCCESS(f"Готово: {done}, не вышло {failed}"))
