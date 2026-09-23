"""Перевести сцены студии на другую модель видео (и другую длительность).

Клиент (17.09): «пусть даже генерация будет выходить дороже, если это даст
заметный прирост качества». Модель у пресета меняется в админке по одной штуке,
а их полторы сотни — поэтому команда.

Показывает, как изменится цена, и без --apply ничего не трогает.

  python manage.py studio_video_model --model bytedance/seedance-2.0
  python manage.py studio_video_model --model bytedance/seedance-2.0 --apply
  python manage.py studio_video_model --model google/veo-3.1 --duration 8 --resolution 1080p --apply
"""
from django.core.management.base import BaseCommand

from ai.models import GPTModels
from cartoon.models import CartoonPreset
from cartoon.pricing import effective_duration, frame_credits, video_credits


class Command(BaseCommand):
    help = "Сменить модель видео у сцен студии и показать новую цену"

    def add_arguments(self, parser):
        parser.add_argument("--model", required=True, help="openrouter_id модели видео")
        parser.add_argument("--image-model", default="", help="openrouter_id модели кадра")
        parser.add_argument("--duration", type=int, default=0, help="Длительность сцены, с")
        parser.add_argument("--resolution", default="", help="Качество, например 1080p")
        parser.add_argument("--only-model", default="",
                            help="Менять только у пресетов с этой моделью видео")
        parser.add_argument("--apply", action="store_true", help="Записать изменения")

    def handle(self, *args, **opts):
        video = GPTModels.objects.filter(openrouter_id=opts["model"], is_active=True).first()
        if not video:
            self.stderr.write(self.style.ERROR(
                f"Модель {opts['model']} не найдена или выключена в каталоге"))
            return
        image = None
        if opts["image_model"]:
            image = GPTModels.objects.filter(openrouter_id=opts["image_model"],
                                             is_active=True).first()
            if not image:
                self.stderr.write(self.style.ERROR(f"Модель кадра {opts['image_model']} не найдена"))
                return

        presets = CartoonPreset.objects.select_related("image_model", "video_model")
        if opts["only_model"]:
            presets = presets.filter(video_model__openrouter_id=opts["only_model"])
        presets = list(presets)
        if not presets:
            self.stdout.write("Подходящих сцен нет")
            return

        duration = int(opts["duration"] or 0)
        real = effective_duration(video, duration or presets[0].duration)
        if duration and real != duration:
            self.stdout.write(self.style.WARNING(
                f"Модель снимает {real} с вместо запрошенных {duration} — считаю по {real}"))

        was = sum(p.estimated_credits() for p in presets) / len(presets)
        new_frame = frame_credits(image or presets[0].image_model)
        new_video = video_credits(video, duration or presets[0].duration,
                                  opts.get("resolution") or presets[0].resolution or "720p")
        self.stdout.write(
            f"Сцен: {len(presets)}. Сейчас в среднем {was:.0f} кр. "
            f"Станет {new_frame + new_video} кр (кадр {new_frame} + видео {new_video} за {real} с).")

        if not opts["apply"]:
            self.stdout.write(self.style.WARNING("Пробный прогон: ничего не изменено (--apply)"))
            return

        fields = ["video_model"]
        for preset in presets:
            preset.video_model = video
            if image:
                preset.image_model = image
            if duration:
                preset.duration = duration
            if opts["resolution"]:
                preset.resolution = opts["resolution"]
        if image:
            fields.append("image_model")
        if duration:
            fields.append("duration")
        if opts["resolution"]:
            fields.append("resolution")
        CartoonPreset.objects.bulk_update(presets, fields, batch_size=100)
        self.stdout.write(self.style.SUCCESS(f"Готово: {len(presets)} сцен переведены на {video.name}"))
