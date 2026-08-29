"""Сделать лёгкие копии картинок библиотеки для витрины.

Оригиналы у нас тяжёлые: кадр от модели — PNG больше мегабайта, портрет
героя — почти мегабайт. Витрина показывает их разом полторы сотни, и на
телефоне картинки просто не доезжают. Команда добивает миниатюры тем
записям, у которых их ещё нет.

Запуск:  python manage.py make_thumbs [--force]
"""
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand

from cartoon.models import CartoonCharacter, CartoonPreset
from cartoon.thumbs import CHARACTER_BOX, POSTER_BOX, make_thumb


class Command(BaseCommand):
    help = "Сделать миниатюры обложек сцен и портретов героев"

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true",
                            help="Пересоздать даже там, где миниатюра уже есть")

    def handle(self, *args, **opts):
        force = bool(opts.get("force"))
        saved = skipped = failed = 0
        before = after = 0

        def shrink(obj, src_field, dst_field, box, name):
            nonlocal saved, skipped, failed, before, after
            src = getattr(obj, src_field)
            dst = getattr(obj, dst_field)
            if not src:
                skipped += 1
                return
            if dst and not force:
                skipped += 1
                return
            try:
                with default_storage.open(src.name, "rb") as fh:
                    blob = fh.read()
            except Exception:
                failed += 1
                self.stderr.write(self.style.WARNING(f"  не читается: {src.name}"))
                return
            thumb = make_thumb(blob, box)
            if not thumb:
                failed += 1
                return
            before += len(blob)
            after += len(thumb)
            dst.save(f"{name}.jpg", ContentFile(thumb), save=False)
            obj.save(update_fields=[dst_field])
            saved += 1

        self.stdout.write(self.style.MIGRATE_HEADING("Обложки сцен"))
        for p in CartoonPreset.objects.exclude(preview_poster=""):
            shrink(p, "preview_poster", "preview_thumb", POSTER_BOX, p.slug)

        self.stdout.write(self.style.MIGRATE_HEADING("Портреты героев"))
        for c in CartoonCharacter.objects.exclude(image=""):
            shrink(c, "image", "image_thumb", CHARACTER_BOX, f"char-{c.pk}")

        if before:
            self.stdout.write(
                f"Вес: было {before / 1048576:.1f} МБ, стало {after / 1048576:.1f} МБ "
                f"({after * 100 // before}%)")
        self.stdout.write(self.style.SUCCESS(
            f"Готово: сделано {saved}, пропущено {skipped}, не вышло {failed}"))
