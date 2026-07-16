"""Идемпотентный сид моделей для раздела «Создание мультфильмов» (студия).

Запускать: python manage.py seed_cartoon

Что делает:
  1. Создаёт/обновляет ВИДЕО-модели (category="video", cartoon_stage="video").
     markup_coefficient = КРЕДИТОВ ЗА СЕКУНДУ (как в существующей video-ветке
     core/ai/handlers.py).
  2. Создаёт/обновляет FLUX ИЗОБРАЖЕНИЯ (category="image", cartoon_stage="image").
     markup_coefficient = КРЕДИТОВ ЗА КАРТИНКУ (плоское списание, images-API).
  3. Тегирует cartoon_stage у УЖЕ существующих моделей, НЕ трогая прочие поля:
       - Nano Banana (google/*image)  -> cartoon_stage="image"
       - флагманы-скрипты (openai/gpt*, anthropic/claude*, google/gemini*,
         кроме image/video) -> cartoon_stage="script"

Всё создаваемое: max_tokens=4096, is_active=True. Повторный запуск безопасен
(update_or_create по openrouter_id).
"""
from decimal import Decimal

from django.core.management.base import BaseCommand

from ai.models import GPTModels


DEFAULT_MAX_TOKENS = 4096


# --- Видео-модели: (openrouter_id, name, coeff=кредитов/сек, desc, recommended)
#
# ⚠️ ТАРИФЫ ПЕРЕСЧИТАНЫ 2026-07-12 (инцидент: юзер купил «Премиум» 1300кр/990сом,
# 2 генерации Veo 3.1 (4с) реально стоили $3.20 (проверено по биллингу OpenRouter/
# Vertex) — маржа оказалась ~6%, а не ≥40% как требует клиент. Причина: тариф
# считали без учёта того, что БОЛЬШИЕ пакеты дают более дешёвый кредит (Максимум
# 2800кр/1990сом = 0.711 сом/кредит против Старт 150кр/190сом = 1.267 сом/кредит).
# Коэффициенты ниже пересчитаны так, чтобы маржа была ≥40% ДАЖЕ на самом дешёвом
# по кредиту пакете (Максимум) — формула: coeff = ceil(($/сек × 87.45 сом) / 0.6 /
# 0.7107 сом-за-кредит-Максимум). $/сек взяты с живого OpenRouter
# /api/v1/videos/models (SKU «со звуком», т.к. generate_audio по умолчанию True) —
# Seedance 2.0 не даёт прямой $/сек (тариф в video_tokens) — ИЗМЕРЕН живой
# генерацией: $0.756 за 5-сек ролик = $0.1512/сек.
VIDEO_MODELS = [
    ("google/veo-3.1",          "Veo 3.1",     "83", "Максимальное качество", True),
    ("openai/sora-2-pro",       "Sora 2 Pro",  "62", "Максимальное качество", False),
    ("kwaivgi/kling-v3.0-std",  "Kling 3.0",   "26", "Реалистичное видео",    False),
    ("minimax/hailuo-2.3",      "Hailuo 2.3",  "17", "Для соцсетей",          False),
    ("bytedance/seedance-2.0",  "Seedance 2.0","32", "Лучший баланс",         False),
    ("alibaba/wan-2.7",         "Wan 2.7",     "21", "Быстрая генерация",     False),
]

# --- Видео-модели ВНЕ студии мультфильмов (заведены раньше 2026-07-03, тоже
#     активны в общем каталоге) — тарифы пересчитаны тем же методом 2026-07-12.
LEGACY_VIDEO_MODELS = [
    ("x-ai/grok-imagine-video", "Grok Video",   "15", "Быстрая генерация"),
    ("google/veo-3.1-lite",     "Veo 3.1 Lite", "17", "Лучший баланс"),
]

# --- FLUX изображения: (openrouter_id, name, coeff=кредитов/картинку, desc)
FLUX_MODELS = [
    ("black-forest-labs/flux.2-klein-4b", "FLUX Klein", "2",  "Быстрая генерация"),
    ("black-forest-labs/flux.2-pro",      "FLUX Pro",   "4",  "Универсальная модель"),
    # Flex — РЕДАКТИРОВАНИЕ (замена фона/объектов/текста, до 8 референсов). Правка
    # дороже (~$0.10) → coeff 12, чтобы не в убыток.
    ("black-forest-labs/flux.2-flex",     "FLUX Flex",  "12", "Редактирование изображений"),
    ("black-forest-labs/flux.2-max",      "FLUX Max",   "10", "Максимальное качество"),
]


class Command(BaseCommand):
    help = "Идемпотентный сид моделей студии мультфильмов (видео + FLUX + теги script/image)."

    def handle(self, *args, **options):
        created = []
        updated = []

        # 1) Видео-модели -----------------------------------------------------
        for sort_i, (orid, name, coeff, desc, recommended) in enumerate(VIDEO_MODELS):
            obj, was_created = GPTModels.objects.update_or_create(
                openrouter_id=orid,
                defaults={
                    "name": name,
                    "description": desc,
                    "category": "video",
                    "cartoon_stage": "video",
                    "markup_coefficient": Decimal(coeff),
                    "recommended": recommended,
                    "max_tokens": DEFAULT_MAX_TOKENS,
                    "is_active": True,
                    "sort_order": 200 + sort_i,
                },
            )
            (created if was_created else updated).append(
                f"[video] {name} ({orid}) coeff={coeff}/сек"
            )

        # 1b) Legacy видео-модели (НЕ в студии — cartoon_stage не трогаем у уже
        #     существующих, только тариф/описание/is_active/max_tokens).
        for orid, name, coeff, desc in LEGACY_VIDEO_MODELS:
            obj, was_created = GPTModels.objects.update_or_create(
                openrouter_id=orid,
                defaults={
                    "name": name,
                    "description": desc,
                    "category": "video",
                    "markup_coefficient": Decimal(coeff),
                    "max_tokens": DEFAULT_MAX_TOKENS,
                    "is_active": True,
                },
            )
            (created if was_created else updated).append(
                f"[video-legacy] {name} ({orid}) coeff={coeff}/сек"
            )

        # 2) FLUX изображения -------------------------------------------------
        for sort_i, (orid, name, coeff, desc) in enumerate(FLUX_MODELS):
            obj, was_created = GPTModels.objects.update_or_create(
                openrouter_id=orid,
                defaults={
                    "name": name,
                    "description": desc,
                    "category": "image",
                    "cartoon_stage": "image",
                    "markup_coefficient": Decimal(coeff),
                    "max_tokens": DEFAULT_MAX_TOKENS,
                    "is_active": True,
                    "sort_order": 220 + sort_i,
                },
            )
            (created if was_created else updated).append(
                f"[image] {name} ({orid}) coeff={coeff}/картинку"
            )

        # 3) Тегирование существующих моделей (НЕ меняем прочие поля) ---------
        tagged = []

        # 3a) Nano Banana image-модели: google/*image -> cartoon_stage="image"
        for m in GPTModels.objects.filter(
            openrouter_id__startswith="google/",
            openrouter_id__icontains="image",
        ):
            if m.cartoon_stage != "image":
                m.cartoon_stage = "image"
                m.save(update_fields=["cartoon_stage", "updated_at"])
                tagged.append(f"[tag→image] {m.name} ({m.openrouter_id})")

        # 3b) Флагманы-скрипты: openai/gpt*, anthropic/claude*, google/gemini*
        #     Исключаем image/video, только активные, по 1-2 на вендора.
        SCRIPT_VENDORS = ["openai/gpt", "anthropic/claude", "google/gemini"]
        for prefix in SCRIPT_VENDORS:
            qs = (
                GPTModels.objects.filter(
                    openrouter_id__startswith=prefix, is_active=True
                )
                .exclude(category__in=["image", "video"])
                .exclude(openrouter_id__icontains="image")
                .exclude(openrouter_id__icontains="video")
                .order_by("sort_order", "id")
            )
            for m in qs[:2]:
                if m.cartoon_stage != "script":
                    m.cartoon_stage = "script"
                    m.save(update_fields=["cartoon_stage", "updated_at"])
                    tagged.append(f"[tag→script] {m.name} ({m.openrouter_id})")

        # --- Отчёт ----------------------------------------------------------
        self.stdout.write(self.style.MIGRATE_HEADING("=== seed_cartoon ==="))
        self.stdout.write(self.style.SUCCESS(f"Создано ({len(created)}):"))
        for line in created:
            self.stdout.write(f"  + {line}")
        self.stdout.write(self.style.WARNING(f"Обновлено ({len(updated)}):"))
        for line in updated:
            self.stdout.write(f"  ~ {line}")
        self.stdout.write(self.style.HTTP_INFO(f"Протегировано существующих ({len(tagged)}):"))
        for line in tagged:
            self.stdout.write(f"  * {line}")
        if not tagged:
            self.stdout.write("  (существующих под теги не найдено)")
