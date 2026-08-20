"""Заполнить описания видео- и image-моделей в каталоге /models.

Зачем команда, а не миграция данных: тексты — это контент, клиент правит их в
админке, и «откатить миграцию» тут ничего не значит. Команда идемпотентна и
по умолчанию НЕ трогает описания, которые уже написаны руками.

Что делает:
  1. переносит короткую метку («Максимальное качество») из description в
     short_label — раньше она занимала место описания, и в каталоге у видео
     вместо текста стояли два слова;
  2. проставляет описание каждой модели.

Тексты опираются на реальные возможности из каталога OpenRouter
(supported_durations / supported_resolutions / generate_audio), а не на
маркетинг: длительность, разрешение и наличие звука проверены по /videos/models
на 20.08.2026.

Запуск:  python manage.py fill_model_descriptions [--force]
"""
from django.core.management.base import BaseCommand

from ai.models import GPTModels

# openrouter_id -> (короткая метка, описание для каталога)
DATA: dict[str, tuple[str, str]] = {
    # --- Видео -------------------------------------------------------------
    "google/veo-3.1": (
        "Максимальное качество",
        "Флагман Google: видео до 4K со звуком, 4–8 секунд, задаётся первый и последний кадр",
    ),
    "google/veo-3.1-lite": (
        "Лучший баланс",
        "Экономичный Veo: 1080p со звуком, 4–8 секунд — когда роликов нужно много",
    ),
    "openai/sora-2-pro": (
        "Максимальное качество",
        "Флагман OpenAI: до 20 секунд со звуком, достоверная физика движения и смена планов",
    ),
    "kwaivgi/kling-v3.0-std": (
        "Реалистичное видео",
        "Kling от Kuaishou: до 15 секунд со звуком, 720p, контроль первого и последнего кадра",
    ),
    "minimax/hailuo-2.3": (
        "Для соцсетей",
        "MiniMax Hailuo: 1080p, ролик на 6 или 10 секунд, без звука — самая дешёвая секунда",
    ),
    "bytedance/seedance-2.0": (
        "Лучший баланс",
        "Seedance от ByteDance: до 15 секунд, вплоть до 4K, семь пропорций кадра и звук",
    ),
    "bytedance/seedance-2.5": (
        "Лучший баланс",
        "Новый Seedance: до 30 секунд со звуком, продление роликов и склейка сцен подряд",
    ),
    "alibaba/wan-2.7": (
        "Быстрая генерация",
        "Wan от Alibaba: 1080p со звуком, от 2 до 10 секунд, пять пропорций кадра",
    ),
    "x-ai/grok-imagine-video": (
        "Быстрая генерация",
        "Grok от xAI: короткие ролики 1–15 секунд, семь пропорций, быстро и без звука",
    ),
    # --- Изображения -------------------------------------------------------
    "black-forest-labs/flux.2-klein-4b": (
        "Быстрая генерация",
        "Самый быстрый и дешёвый FLUX: черновики и десяток вариантов подряд",
    ),
    "black-forest-labs/flux.2-pro": (
        "Универсальная модель",
        "Основной FLUX: реалистичные изображения и аккуратный текст прямо на картинке",
    ),
    "black-forest-labs/flux.2-max": (
        "Максимальное качество",
        "Старший FLUX: максимум детализации для сложных сцен и печати",
    ),
    "black-forest-labs/flux.2-flex": (
        "Редактирование",
        "FLUX для правок: меняет готовое изображение по описанию, не рисуя заново",
    ),
}


class Command(BaseCommand):
    help = "Заполнить short_label и description у видео- и image-моделей"

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Перезаписать описания, даже если они уже длиннее метки",
        )

    def handle(self, *args, **opts):
        force = bool(opts.get("force"))
        touched = skipped = missing = 0

        for openrouter_id, (label, description) in DATA.items():
            model = GPTModels.objects.filter(openrouter_id=openrouter_id).first()
            if not model:
                missing += 1
                self.stdout.write(f"  нет в базе: {openrouter_id}")
                continue

            fields = []
            if not (model.short_label or "").strip():
                model.short_label = label
                fields.append("short_label")

            current = (model.description or "").strip()
            # Своим считаем описание длиннее 40 символов, не совпадающее с меткой:
            # короткие «Максимальное качество» — как раз то, что мы заменяем.
            written_by_hand = len(current) > 40 and current != label
            if force or not written_by_hand:
                if current != description:
                    model.description = description
                    fields.append("description")

            if fields:
                model.save(update_fields=fields)
                touched += 1
                self.stdout.write(f"  обновлено: {model.name} ({', '.join(fields)})")
            else:
                skipped += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Готово. Обновлено: {touched}, пропущено: {skipped}, нет в базе: {missing}"
            )
        )
