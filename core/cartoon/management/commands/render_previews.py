"""Снять видео-превью для пресетов студии и завести стартовую библиотеку героев.

Превью — это то, ради чего пресет вообще существует: человек не читает промпт,
он смотрит ролик и понимает, что получит. Пока превью нет, карточка сцены
пустая и выбирать не из чего.

Снимаем ОДНИМ и тем же героем нарочно. Во-первых, десять сцен с одним котом
сразу показывают главное свойство студии — персонаж не меняется от сцены к
сцене. Во-вторых, так видно именно разницу сцен, а не разницу героев.

Расход настоящий, деньгами с баланса OpenRouter: около $0.5 за сцену (5 секунд
Wan 2.7 плюс кадр). Кредиты пользователя НЕ трогаются — это наш контент, а не
чей-то заказ, поэтому идём мимо биллинга.

Запуск:
    python manage.py render_previews              # только те, у кого превью нет
    python manage.py render_previews --force      # переснять всё
    python manage.py render_previews --only slug  # одну сцену
"""
import base64
import time
import uuid

import requests
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand

from cartoon.models import CartoonCharacter, CartoonPreset
from cartoon.services import generate_keyframe, generate_scene_video

from cartoon.library import CHARACTER_TRANSLATIONS, CHARACTERS, audience_of
from cartoon.models import CartoonCategory

# Как рисуем самого героя. Без слов «character sheet»: модель понимала их
# буквально и печатала подпись в самой картинке. Надписи запрещаем прямо.
_FRAMING = ("Full body view, standing, clean plain white background, "
            "NO text, NO captions, NO labels, NO watermark anywhere in the image. front view.")
STYLE_SUFFIX = f"{_FRAMING} 3D cartoon animation style, soft lighting, vibrant colors."
# Взрослого героя нельзя рисовать той же милой подачей: в детективе и драме
# он должен выглядеть человеком, а не игрушкой.
ADULT_STYLE_SUFFIX = (f"{_FRAMING} stylized 3D animated film style, semi-realistic adult "
                      "proportions, cinematic lighting, muted filmic colors, NOT childish.")


class Command(BaseCommand):
    help = "Снять видео-превью пресетов и создать стартовых персонажей"

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", help="Переснять уже готовые превью")
        parser.add_argument("--only", type=str, default="", help="Только этот пресет (slug)")
        parser.add_argument("--skip-characters", action="store_true",
                            help="Не создавать библиотеку героев")

    # ------------------------------------------------------------------ герои
    def ensure_library(self):
        from ai.handlers import _openrouter_config

        cfg = _openrouter_config()
        for name, description, look, cat_slug in CHARACTERS:
            if CartoonCharacter.objects.filter(name=name, user__isnull=True).exists():
                continue
            suffix = (ADULT_STYLE_SUFFIX if audience_of(cat_slug) == "adults" else STYLE_SUFFIX)
            self.stdout.write(f"  рисую героя: {name}")
            try:
                r = requests.post(
                    f"{cfg['base_url'].rstrip('/')}/images",
                    json={"model": "google/gemini-2.5-flash-image",
                          "prompt": f"{look}. {suffix}", "aspect_ratio": "1:1"},
                    headers={"Authorization": f"Bearer {cfg['api_key']}",
                             "Content-Type": "application/json"},
                    timeout=(10, 180),
                )
                b64 = (((r.json() or {}).get("data") or [{}])[0]).get("b64_json") or ""
                if not b64:
                    raise RuntimeError(f"http {r.status_code}: {str(r.text)[:150]}")
            except Exception as exc:
                self.stderr.write(self.style.WARNING(f"    не вышло: {exc}"))
                continue
            tr = CHARACTER_TRANSLATIONS.get(name, ("", ""))
            char = CartoonCharacter(
                user=None, name=name, name_en=tr[0], name_kg=tr[1],
                description=description,
                category=CartoonCategory.objects.filter(slug=cat_slug).first(),
                source=CartoonCharacter.SOURCE_LIBRARY, is_public=True,
            )
            char.image.save(f"{uuid.uuid4().hex}.jpg", ContentFile(base64.b64decode(b64)), save=True)
            self.stdout.write(self.style.SUCCESS(f"    готов: {char.image.url}"))

    # ---------------------------------------------------------------- превью
    def handle(self, *args, **opts):
        if not opts.get("skip_characters"):
            self.stdout.write(self.style.MIGRATE_HEADING("Библиотека героев"))
            self.ensure_library()

        library = list(CartoonCharacter.objects.filter(user__isnull=True).select_related("category"))
        if not library:
            self.stderr.write(self.style.ERROR("Нет ни одного библиотечного героя — превью снимать некем"))
            return

        def hero_for(preset):
            """Кем снимать превью этой сцены.

            Раньше все превью снимались котом-супергероем. Для «Пробуждения»
            это мило, а для допроса и офисной презентации — пародия, поэтому
            герой берётся из того же раздела, а если его там нет — любой
            подходящий по аудитории.
            """
            cat = preset.category.slug if preset.category_id else ""
            same = [c for c in library if c.category_id and c.category.slug == cat]
            if same:
                return same[0]
            want = audience_of(cat)
            fit = [c for c in library
                   if c.category_id and audience_of(c.category.slug) == want]
            return fit[0] if fit else library[0]

        qs = CartoonPreset.objects.filter(is_active=True).select_related(
            "image_model", "video_model", "category")
        if opts.get("only"):
            qs = qs.filter(slug=opts["only"])
        elif not opts.get("force"):
            qs = qs.filter(preview_video="")

        total = qs.count()
        self.stdout.write(self.style.MIGRATE_HEADING(f"Превью: {total} сцен"))
        done = failed = 0

        for i, preset in enumerate(qs, start=1):
            hero = hero_for(preset)
            self.stdout.write(f"[{i}/{total}] {preset.title} — {hero.name}")
            started = time.time()
            try:
                keyframe = generate_keyframe(preset, hero)
                video_path = generate_scene_video(preset, keyframe)
            except Exception as exc:
                failed += 1
                self.stderr.write(self.style.WARNING(f"    не вышло: {exc}"))
                continue

            from django.core.files.storage import default_storage

            with default_storage.open(video_path, "rb") as fh:
                preset.preview_video.save(f"{preset.slug}.mp4", ContentFile(fh.read()), save=False)
            # Обложкой берём тот же кадр, с которого начинается ролик: пока
            # видео не подгрузилось, карточка показывает ровно его первый кадр.
            with default_storage.open(keyframe, "rb") as fh:
                preset.preview_poster.save(f"{preset.slug}.png", ContentFile(fh.read()), save=False)
            preset.save(update_fields=["preview_video", "preview_poster"])
            done += 1
            self.stdout.write(self.style.SUCCESS(
                f"    готово за {int(time.time() - started)} с: {preset.preview_video.url}"))

        self.stdout.write(self.style.SUCCESS(f"Итог: снято {done}, не вышло {failed}"))
