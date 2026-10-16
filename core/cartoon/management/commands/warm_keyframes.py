"""Заранее нарисовать кадры «герой в сцене» для библиотеки.

Зачем. Готовая пара «сцена + герой» отдаётся бесплатно и мгновенно: витрина
подставляет её сама, и человек видит выбранного героя в примерах, ничего не
нажимая и не платя. Пока пара не нарисована, её приходится заказывать кнопкой
за кредиты.

Прогрев заполняет запас заранее — по самым вероятным сочетаниям, а не по всем
подряд: библиотека это 152 сцены на 26 героев, то есть почти четыре тысячи
кадров, и рисовать их все бессмысленно.

Запуск:
  python manage.py warm_keyframes --picks --characters "Капибара,Детектив"
  python manage.py warm_keyframes --limit 20 --dry-run
"""
from django.core.management.base import BaseCommand

from cartoon.models import CartoonCharacter, CartoonKeyframe, CartoonPreset
from cartoon.pricing import frame_credits
from cartoon.services import get_or_create_keyframe


class Command(BaseCommand):
    help = "Заранее нарисовать кадры «герой в сцене», чтобы примерка была бесплатной"

    def add_arguments(self, parser):
        parser.add_argument("--characters", type=str, default="",
                            help="Имена героев через запятую. Пусто — все библиотечные.")
        parser.add_argument("--picks", action="store_true",
                            help="Только сцены из подборки «Выбор EsAI»")
        parser.add_argument("--limit", type=int, default=0,
                            help="Не рисовать больше этого числа кадров")
        parser.add_argument("--dry-run", action="store_true",
                            help="Только посчитать, ничего не рисовать")

    def handle(self, *args, **opts):
        scenes = CartoonPreset.objects.filter(is_active=True).exclude(preview_video="")
        if opts.get("picks"):
            scenes = scenes.filter(is_pick=True)
        scenes = list(scenes.select_related("image_model"))

        heroes = CartoonCharacter.objects.filter(user__isnull=True, is_public=True)
        names = [n.strip() for n in (opts.get("characters") or "").split(",") if n.strip()]
        if names:
            heroes = heroes.filter(name__in=names)
        heroes = list(heroes)

        if not scenes or not heroes:
            self.stderr.write(self.style.ERROR("Нечего рисовать: пустой список сцен или героев"))
            return

        have = {
            (k.preset_id, k.character_id)
            for k in CartoonKeyframe.objects.filter(
                preset__in=scenes, character__in=heroes).only("preset_id", "character_id")
        }
        todo = [(s, h) for h in heroes for s in scenes if (s.pk, h.pk) not in have]
        limit = int(opts.get("limit") or 0)
        if limit:
            todo = todo[:limit]

        price = sum(frame_credits(s.image_model) for s, _ in todo)
        self.stdout.write(
            f"Сцен {len(scenes)}, героев {len(heroes)}, уже готово {len(have)}. "
            f"Нарисовать: {len(todo)} кадров ≈ {price} кредитов.")
        if opts.get("dry_run") or not todo:
            return

        done = failed = 0
        for i, (scene, hero) in enumerate(todo, start=1):
            try:
                get_or_create_keyframe(scene, hero, user=None)
                done += 1
            except Exception as exc:
                failed += 1
                self.stderr.write(self.style.WARNING(f"  {hero.name} / {scene.slug}: {exc}"))
            if i % 10 == 0 or i == len(todo):
                self.stdout.write(f"  {i}/{len(todo)}")

        self.stdout.write(self.style.SUCCESS(f"Готово: {done}, не вышло {failed}"))
