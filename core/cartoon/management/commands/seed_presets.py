"""Первые пресеты сцен для студии мультфильмов.

Клиент просил начать с десятка ДЕЙСТВИТЕЛЬНО качественных сцен, а не с
полусотни посредственных. Здесь именно они — сюжетные кирпичики, из которых
складывается короткий мультфильм: появление, путь, трудность, победа,
возвращение.

Модели одинаковые у всех пресетов не случайно: кадр рисует Nano Banana (только
она удерживает персонажа по референсу и укладывается в секунды), а видео —
Wan 2.7. Wan выбран как разумный минимум: 1080p со звуком, умеет ролики от
2 секунд, и секунда у него дешевле, чем у Kling или Seedance. Клиент может
поменять модель у любого пресета в админке — цена пересчитается сама.

Стиль у всех один и тот же. Это и делает сцены ОДНИМ мультфильмом, а не
нарезкой: одинаковая подача света, цвета и подача кадра.

Запуск:  python manage.py seed_presets [--force]
"""
from django.core.management.base import BaseCommand

from ai.models import GPTModels
from cartoon.models import CartoonPreset

STYLE = ("3D cartoon animation style, Pixar-like rendering, soft cinematic lighting, "
         "vibrant saturated colors, shallow depth of field, family-friendly")

# (код, название, подпись, что в кадре, что движется, секунд)
PRESETS = [
    ("hero-appears", "Герой появляется", "Выход на крышу на рассвете",
     "the character stands heroically on a rooftop at sunrise, city skyline behind, wind in the air",
     "slow cinematic push-in on the character, cape and hair flutter, sun flares softly", 5),
    ("takes-off", "Взлёт", "Отрывается от земли и уходит вверх",
     "the character crouches and then leaps upward from a city street, dust swirling below",
     "the character launches upward, camera tilts up following the flight, motion blur streaks", 5),
    ("flying", "Полёт над городом", "Летит сквозь облака",
     "the character flying high above the clouds, city far below, warm sunlight",
     "smooth flight forward, clouds rush past the camera, cape streams behind", 5),
    ("magic-world", "Волшебный мир", "Попадает в светящийся лес",
     "the character walking into a glowing magical forest, floating lights, giant mushrooms",
     "the character walks forward, glowing particles drift around, camera follows gently", 5),
    ("space", "Космос", "Парит среди звёзд",
     "the character floating in outer space near a colorful nebula, planets in the distance",
     "slow weightless rotation of the character, stars drift by, nebula glows and shifts", 5),
    ("dino-meets", "Встреча с динозавром", "Знакомится с добрым динозавром",
     "the character meeting a friendly giant dinosaur in a sunny prehistoric valley",
     "the dinosaur lowers its head toward the character, both react warmly, camera circles slowly", 5),
    ("funny-fall", "Смешная сцена", "Забавно спотыкается и встаёт",
     "the character comically slips on a banana peel in a bright city park, exaggerated cartoon pose",
     "the character slips, tumbles and springs back up with a grin, bouncy cartoon timing", 4),
    ("chase", "Погоня", "Мчится по улицам",
     "the character running fast through a colorful city street, motion energy, onlookers blurred",
     "fast tracking shot alongside the running character, speed lines, camera shake", 5),
    ("battle", "Схватка", "Противостоит большому роботу",
     "the character facing a huge friendly-looking robot in a city square, determined pose",
     "the character raises fists, the robot leans in, camera pushes past them dramatically", 5),
    ("goes-home", "Возвращение домой", "Уходит на закате",
     "the character walking home along a quiet street at sunset, long shadows, warm light",
     "the character walks away from camera, sun sets behind, gentle slow pull-back", 5),
]


class Command(BaseCommand):
    help = "Завести первые пресеты сцен студии мультфильмов"

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

        created = updated = skipped = 0
        for order, (slug, title, subtitle, scene, motion, duration) in enumerate(PRESETS, start=1):
            preset = CartoonPreset.objects.filter(slug=slug).first()
            if preset and not force:
                skipped += 1
                continue
            values = dict(
                title=title, subtitle=subtitle,
                scene_prompt=scene, motion_prompt=motion, style_prompt=STYLE,
                image_model=image_model, video_model=video_model,
                duration=duration, aspect_ratio="16:9", resolution="720p",
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

        total = CartoonPreset.objects.count()
        self.stdout.write(self.style.SUCCESS(
            f"Пресеты: создано {created}, обновлено {updated}, пропущено {skipped}. Всего: {total}"))
        self.stdout.write(
            "Видео-превью заливаются в админке — без них сцена работает, "
            "но пользователь не видит, что получит.")
