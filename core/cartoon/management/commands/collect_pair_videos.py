"""Собрать общий запас роликов пар из уже снятых сцен.

Новые съёмки попадают туда сами (tasks.render_scene). Команда нужна один раз
— для сцен, снятых до появления запаса, — и безопасна при повторе.

  python manage.py collect_pair_videos
"""
from django.core.management.base import BaseCommand

from cartoon.models import CartoonScene
from cartoon.services import remember_pair_video


class Command(BaseCommand):
    help = "Положить уже снятые сцены библиотечных героев в общий запас роликов"

    def handle(self, *args, **opts):
        scenes = (CartoonScene.objects.filter(status=CartoonScene.STATUS_READY)
                  .exclude(video="").select_related("character", "project__character")
                  .order_by("id"))
        added = 0
        for scene in scenes:
            try:
                added += bool(remember_pair_video(scene))
            except Exception as exc:
                self.stderr.write(self.style.WARNING(f"  сцена {scene.pk}: {exc}"))
        self.stdout.write(self.style.SUCCESS(f"Снятых сцен: {scenes.count()}, новых роликов в запасе: {added}"))
