"""Реестр 15 инструментов Creative Studio (SPEC_B §2).

Единственное место, где живут адреса моделей поставщика. Всё остальное в
приложении знает инструмент только по id карточки сайта
(next/src/lib/creative/tools.ts) и по нашим именам полей формы.

Что здесь есть на каждый инструмент:
- поля формы (наши имена), их типы, значения по умолчанию и пределы;
- validate() — проверка ДО отправки: поставщик принимает даже неполное тело
  и запускает платную генерацию с настройками по умолчанию (B0), поэтому всё,
  что уйдёт, проверяем сами;
- build_body() — ровно то JSON-тело, которое уйдёт поставщику: пустые и
  неизвестные поля не шлём, «авто» = поле не отправлять;
- cost_usd() — себестоимость по формулам §2 (константы ниже можно подкрутить);
- что получает человек (картинки, видео или персонажа) и требования к входам.
"""
from __future__ import annotations

import math
import re
import uuid
from dataclasses import dataclass, field
from decimal import ROUND_CEILING, Decimal
from types import SimpleNamespace
from typing import Any, Callable

D = Decimal

# ---------------------------------------------------------------- цены (SPEC §2, B0)

# Genjutsu Motion Transfer / Object Swap: $ за секунду исходника, округление вверх.
GENJUTSU_RATE = {"480p": D("0.1540"), "720p": D("0.3446"), "1080p": D("0.8346")}
# Genjutsu Restyle (по документации).
RESTYLE_RATE = {"480p": D("0.318"), "720p": D("0.681"), "1080p": D("1.632")}
# Genjutsu Light: $ за секунду результата.
LIGHT_RATE = {"480p": D("0.0739"), "720p": D("0.1471"), "1080p": D("0.2936")}
# Длиннее 30 с поставщик обрезает сам — дороже 30 с не бывает.
VIDEO_MAX_S = 30
# Light: каталог 14.11 писал «первые 15 секунд», но длина результата не
# подтверждена. Пока считаем по всей длине (до 30 с) — с запасом в нашу пользу.
LIGHT_MAX_S = 30
# Soul 2 и Soul Standard: {разрешение: {партия: $}} — оценки B0.
SOUL2_PRICE = {"720p": {1: D("0.004"), 4: D("0.013")}, "1080p": {1: D("0.006"), 4: D("0.023")}}
SOUL1_PRICE = {"720p": {1: D("0.094"), 4: D("0.125")}, "1080p": {1: D("0.188"), 4: D("0.313")}}
# Marketing Studio 2.0: {качество: {разрешение: $}} — оценки B0.
MS20_PRICE = {
    "low": {"1k": D("0.017"), "2k": D("0.023")},
    "medium": {"1k": D("0.063"), "2k": D("0.118")},
    "high": {"1k": D("0.221"), "2k": D("0.439")},
}
# Токенные модели (Flare, Sunburst, Ads): цена картинки — заглушка до сверки по
# /models/usage, плюс запас TOKEN_SAFETY (SPEC §3).
PER_IMAGE_FLARE = {
    "low": {"1k": D("0.03"), "2k": D("0.045")},
    "medium": {"1k": D("0.08"), "2k": D("0.15")},
    "high": {"1k": D("0.25"), "2k": D("0.5")},
}
PER_IMAGE_SUNBURST = {
    "low": {"1k": D("0.03"), "2k": D("0.045")},
    "medium": {"1k": D("0.08"), "2k": D("0.15")},
    "high": {"1k": D("0.25"), "2k": D("0.5")},
}
PER_IMAGE_ADS = D("0.12")
TOKEN_SAFETY = D("1.25")
# Входная картинка у Marketing Studio: B0 правка medium 1k = $0.077 против $0.063
# без картинки (×1.22). Для «Рестайла фото» (7) SPEC §2: таблица × 1.25 — картинка там ровно одна.
IMAGE_INPUT_SHARE = D("0.25")
# Для 12–14 (фото товара 0–8) SPEC §2 даёт только таблицу. Но вход оплачивается
# поставщиком по токенам картинки — это примерно фиксированная сумма, а не доля
# базы: B0 +$0.014 за картинку (medium 1k). Берём её за каждое фото товара
# (× TOKEN_SAFETY у токенных 13/14), иначе low 1k с 8 фото продавался бы в убыток,
# а high 2k с 8 фото втрое дороже таблицы. Отклонение от SPEC записано в SPEC_B §2.
IMAGE_INPUT_USD = D("0.014")
INFLUENCER_PRICE = D("0.050")
CHARACTER_PRICE = D("2.50")
# Cinema Studio 4.0: токены = ceil(сек × W × H × 24 / 1024), $0.0214 за 1000.
CINEMA_PER_1K_TOKENS = D("0.0214")
CINEMA_FPS = 24
# Кадр результата по соотношению сторон. Поставщик пикселей не обещает, поэтому
# берём не меньше площади 16:9 этого разрешения (21:9 — шире, она больше).
CINEMA_FRAMES = {
    "480p": {"16:9": (854, 480), "9:16": (480, 854), "4:3": (640, 480), "3:4": (480, 640),
             "1:1": (480, 480), "21:9": (1120, 480)},
    "720p": {"16:9": (1280, 720), "9:16": (720, 1280), "4:3": (960, 720), "3:4": (720, 960),
             "1:1": (720, 720), "21:9": (1680, 720)},
}

COST_QUANT = D("0.0001")

# ---------------------------------------------------------------- входы

IMAGE_MIMES = ("image/jpeg", "image/png", "image/webp")
VIDEO_MIN_S = 4.0
VIDEO_MAX_INPUT_S = 30.0
VIDEO_DURATION_TOLERANCE_S = 0.5
# Object Swap: в кадре не меньше 409 600 пикселей (854×480 проходит, 640×480 — нет).
SWAP_MIN_PIXELS = 409_600

KIND_IMAGE = "image"
KIND_VIDEO = "video"
KIND_CHARACTER = "character"

REASON_BY_KIND = {KIND_IMAGE: "creative_image", KIND_VIDEO: "creative_video",
                  KIND_CHARACTER: "creative_character"}

_UID_RE = re.compile(r"^[0-9a-f]{32}$")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _is_uuid(value) -> bool:
    try:
        uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return False
    return True


# ---------------------------------------------------------------- описание полей

@dataclass(frozen=True)
class Field:
    """Поле формы инструмента (наше имя).

    type: text | enum | int | bool | image | images | video | catalog | character | options.
    image/images/video — uid своих загрузок; catalog — id из каталога catalog;
    character — uid своего готового персонажа; options — {категория: [ключи]}.
    """

    name: str
    type: str
    required: bool = False
    default: Any = None
    choices: tuple = ()
    max_len: int = 0
    min: int | None = None
    max: int | None = None
    catalog: str = ""


@dataclass(frozen=True)
class Tool:
    id: str
    n: int
    name: str
    kind: str                    # image | video | character — что получает человек
    model: str                   # адрес модели у поставщика (только сервер)
    fields: tuple
    build: Callable
    cost: Callable
    eta_s: int
    face_consent: bool = False   # галочка «права на лицо» (фото человека)
    frame_min_pixels: int = 0    # предел кадра входного видео
    hint: dict = field(default_factory=dict)   # параметры для «цена от …» и примеров админки

    @property
    def reason(self) -> str:
        return REASON_BY_KIND[self.kind]

    def field(self, name: str) -> Field | None:
        for f in self.fields:
            if f.name == name:
                return f
        return None

    def expected_outputs(self, params: dict) -> int:
        """Сколько файлов обещано: партия картинок; у остальных — один."""
        for name in ("count",):
            if name in params:
                try:
                    return max(1, int(params[name]))
                except (TypeError, ValueError):
                    return 1
        return 1


@dataclass
class BuildCtx:
    """Что нужно build_body кроме параметров: ссылки на файлы у поставщика и персонаж."""

    urls: dict                              # uid загрузки → ссылка, которую примет поставщик
    character_provider_id: str = ""         # id своего персонажа у поставщика
    neutral_name: str = ""                  # имя персонажа у поставщика (не имя человека)

    def url(self, uid: str) -> str:
        value = self.urls.get(uid)
        if not value:
            raise KeyError(f"нет ссылки на загрузку {uid}")
        return value


# ---------------------------------------------------------------- поля по группам

RES_GENJUTSU = ("480p", "720p", "1080p")
CONSENT = Field("consent", "bool", required=True)


def _genjutsu_fields(*, prompt_required: bool) -> tuple:
    return (
        Field("video", "video", required=True),
        Field("image", "image", required=True),
        Field("prompt", "text", required=prompt_required, max_len=1000),
        Field("resolution", "enum", default="480p", choices=RES_GENJUTSU),
        CONSENT,
    )


MS_ASPECTS = ("auto", "1:1", "3:2", "2:3", "4:3", "3:4", "16:9", "9:16")


def _ms_fields(*, qualities: tuple) -> tuple:
    return (
        Field("prompt", "text", required=True, max_len=2000),
        Field("product_images", "images", min=0, max=8),
        Field("preset", "catalog", catalog="ms-presets"),
        Field("quality", "enum", default="medium", choices=qualities),
        Field("resolution", "enum", default="1k", choices=("1k", "2k")),
        Field("aspect", "enum", default="auto", choices=MS_ASPECTS),
    )


SOUL_ASPECTS = ("9:16", "16:9", "4:3", "3:4", "1:1", "2:3", "3:2")

CINEMA_GENRES = ("epic", "drama", "noir", "comedy", "horror", "action")
CINEMA_ERAS = ("1960s", "1980s", "1990s", "2000s", "2020s")
CINEMA_LIGHTS = ("silhouette", "practicals", "window", "overhead-fall", "contre-jour", "soft-cross")
CINEMA_PACING = ("chaotic", "dynamic", "calm", "single-shot")
CINEMA_CAMERA = (
    "snorricam", "robot-arm", "tilt-up", "rack-focus", "tilt-down", "pov", "pan-left", "crane-up",
    "pan-right", "crane-down", "side-tracking", "pedestal-up", "pedestal-down", "handheld",
    "tracking", "drone-orbit", "dolly-zoom", "aerial-pullback", "static-shot", "bullet-time",
    "whip-pan", "slow-zoom-in", "arc-left", "slow-zoom-out", "arc-right", "truck-right",
    "dolly-in", "truck-left", "dolly-out", "slider-right", "crush-zoom", "slider-left",
    "helicopter-shot",
)
# Поля Cinema, где «авто» — значит не отправлять (выберет «режиссёр» модели).
CINEMA_AUTO_FIELDS = (("genre", "genre"), ("era", "era"), ("light", "light"),
                      ("pacing", "pacing"), ("camera_movement", "camera_movement"))


# ---------------------------------------------------------------- тела запросов

def _put(body: dict, key: str, value) -> None:
    """Положить в тело только непустое: пустые строки, None и [] не шлём."""
    if value is None or value == "" or value == [] or value == {}:
        return
    body[key] = value


def _b_genjutsu(p: dict, ctx: BuildCtx) -> dict:
    body = {"video_url": ctx.url(p["video"]), "image_urls": [ctx.url(p["image"])],
            "resolution": p["resolution"]}
    _put(body, "prompt", p.get("prompt"))
    return body


def _b_restyle(p: dict, ctx: BuildCtx) -> dict:
    body = {"video_url": ctx.url(p["video"]), "preset_id": p["style"], "resolution": p["resolution"]}
    _put(body, "image_urls", [ctx.url(u) for u in p.get("images") or []])
    _put(body, "prompt", p.get("prompt"))
    return body


def _b_ads(p: dict, ctx: BuildCtx) -> dict:
    body = {"prompt": p["prompt"], "batch_size": int(p["count"]), "aspect_ratio": p["aspect"],
            "language": p["language"]}
    _put(body, "niche", p.get("niche"))
    _put(body, "target_audience", p.get("audience"))
    _put(body, "image_urls", [ctx.url(u) for u in p.get("product_images") or []])
    return body


def _b_photo_restyle(p: dict, ctx: BuildCtx) -> dict:
    # Режим правки Marketing Studio: фото + enhance_prompt=false (B0: Soul 2 картинку игнорирует).
    body = {"prompt": p["prompt"], "image_urls": [ctx.url(p["image"])], "enhance_prompt": False,
            "quality": p["quality"], "resolution": p["resolution"]}
    if p.get("aspect") and p["aspect"] != "auto":
        body["aspect_ratio"] = p["aspect"]
    return body


def _ms_builder(*, preset_forces_high: bool):
    def build(p: dict, ctx: BuildCtx) -> dict:
        quality = p["quality"]
        body = {"prompt": p["prompt"], "resolution": p["resolution"]}
        if p.get("preset"):
            body["preset_id"] = p["preset"]
            body["enhance_prompt"] = True
            if preset_forces_high:
                quality = "high"
        body["quality"] = quality
        if p.get("aspect") and p["aspect"] != "auto":
            body["aspect_ratio"] = p["aspect"]
        _put(body, "image_urls", [ctx.url(u) for u in p.get("product_images") or []])
        return body
    return build


def _b_soul2(p: dict, ctx: BuildCtx) -> dict:
    body = {"prompt": p["prompt"], "aspect_ratio": p["aspect"], "resolution": p["resolution"],
            "batch_size": int(p["count"])}
    _put(body, "style_id", p.get("style"))
    if p.get("character"):
        if not ctx.character_provider_id:
            raise KeyError("нет id персонажа у поставщика")
        body["custom_reference_id"] = ctx.character_provider_id
    return body


def _b_soul1(p: dict, ctx: BuildCtx) -> dict:
    body = {"prompt": p["prompt"], "aspect_ratio": p["aspect"], "resolution": p["resolution"],
            "batch_size": int(p["count"])}
    _put(body, "style_id", p.get("style"))
    return body


def _b_influencer(p: dict, ctx: BuildCtx) -> dict:
    body = {"tier": "normal"}
    selection = {k: list(v) for k, v in (p.get("options") or {}).items() if v}
    _put(body, "selection", selection)
    _put(body, "brief", p.get("brief"))
    return body


def _b_character(p: dict, ctx: BuildCtx) -> dict:
    # Имя у поставщика — нейтральное: имя, которое дал человек, остаётся у нас.
    return {"name": ctx.neutral_name or "esai-character", "model_version": "v2",
            "input_images": [{"type": "image_url", "image_url": ctx.url(u)} for u in p["photos"]]}


def _b_cinema(p: dict, ctx: BuildCtx) -> dict:
    body = {"prompt": p["prompt"], "duration": int(p["duration"]), "resolution": p["resolution"],
            "aspect_ratio": p["aspect"], "generate_audio": bool(p["audio"])}
    for ours, theirs in CINEMA_AUTO_FIELDS:
        value = p.get(ours)
        if value and value != "auto":
            body[theirs] = value
    _put(body, "image_urls", [ctx.url(u) for u in p.get("images") or []])
    return body


# ---------------------------------------------------------------- себестоимость

def _q(value: Decimal) -> Decimal:
    return value.quantize(COST_QUANT, rounding=ROUND_CEILING)


def _duration(p: dict, inputs: dict) -> float:
    upload = inputs.get(p.get("video")) if p.get("video") else None
    try:
        return float(getattr(upload, "duration_s", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def _billed_seconds(seconds: float, cap: int) -> int:
    seconds = min(max(float(seconds or 0), 0.0), float(cap))
    # 4.0000001 с из-за округления ffprobe не должны стать 5 оплаченными секундами.
    return max(1, int(math.ceil(round(seconds, 3))))


def _c_rate(rates: dict, cap: int):
    def cost(p: dict, inputs: dict) -> Decimal:
        return _q(rates[p["resolution"]] * _billed_seconds(_duration(p, inputs), cap))
    return cost


def _images_in(p: dict) -> int:
    n = 0
    for name in ("image",):
        if p.get(name):
            n += 1
    for name in ("product_images", "images"):
        n += len(p.get(name) or [])
    return n


def _c_ads(p: dict, inputs: dict) -> Decimal:
    return _q(PER_IMAGE_ADS * TOKEN_SAFETY * int(p["count"]))


def _c_photo_restyle(p: dict, inputs: dict) -> Decimal:
    base = MS20_PRICE[p["quality"]][p["resolution"]]
    return _q(base * (1 + IMAGE_INPUT_SHARE * _images_in(p)))


def _c_ms(table: dict, *, token: bool, preset_forces_high: bool):
    def cost(p: dict, inputs: dict) -> Decimal:
        quality = "high" if (p.get("preset") and preset_forces_high) else p["quality"]
        total = table[quality][p["resolution"]] + IMAGE_INPUT_USD * _images_in(p)
        if token:
            total = total * TOKEN_SAFETY
        return _q(total)
    return cost


def _c_soul(table: dict):
    def cost(p: dict, inputs: dict) -> Decimal:
        return _q(table[p["resolution"]][int(p["count"])])
    return cost


def _c_flat(price: Decimal):
    def cost(p: dict, inputs: dict) -> Decimal:
        return _q(price)
    return cost


def cinema_tokens(duration: int, resolution: str, aspect: str) -> int:
    frames = CINEMA_FRAMES[resolution]
    w, h = frames.get(aspect) or frames["16:9"]
    base_w, base_h = frames["16:9"]
    pixels = max(w * h, base_w * base_h)
    return int(math.ceil(int(duration) * pixels * CINEMA_FPS / 1024))


def _c_cinema(p: dict, inputs: dict) -> Decimal:
    tokens = cinema_tokens(int(p["duration"]), p["resolution"], p["aspect"])
    return _q(D(tokens) * CINEMA_PER_1K_TOKENS / 1000)


# ---------------------------------------------------------------- реестр

_VIDEO_HINT = {"_duration": 5.0, "_w": 854, "_h": 480}

TOOLS: tuple[Tool, ...] = (
    Tool("motion-transfer", 1, "Перенос движения", KIND_VIDEO,
         "higgsfield/genjutsu/motion-transfer/v1.0", _genjutsu_fields(prompt_required=False),
         _b_genjutsu, _c_rate(GENJUTSU_RATE, VIDEO_MAX_S), eta_s=240, face_consent=True,
         hint={"resolution": "480p", **_VIDEO_HINT}),
    Tool("object-swap", 2, "Замена объекта", KIND_VIDEO,
         "higgsfield/genjutsu/object-swap/v1.0", _genjutsu_fields(prompt_required=True),
         _b_genjutsu, _c_rate(GENJUTSU_RATE, VIDEO_MAX_S), eta_s=300, face_consent=True,
         frame_min_pixels=SWAP_MIN_PIXELS, hint={"resolution": "480p", **_VIDEO_HINT}),
    Tool("restyle", 3, "Изменение стиля", KIND_VIDEO,
         "higgsfield/genjutsu/restyle/v1.0",
         (Field("video", "video", required=True),
          Field("style", "catalog", required=True, catalog="restyle"),
          Field("images", "images", min=0, max=5),
          Field("prompt", "text", max_len=1000),
          Field("resolution", "enum", default="480p", choices=RES_GENJUTSU),
          CONSENT),
         # в видео и на фото персонажей — люди: галочка прав на лицо, как у 1, 2, 4, 5
         _b_restyle, _c_rate(RESTYLE_RATE, VIDEO_MAX_S), eta_s=330, face_consent=True,
         hint={"resolution": "480p", **_VIDEO_HINT}),
    Tool("character-motion", 4, "Движение персонажа", KIND_VIDEO,
         "higgsfield/genjutsu-light/motion-transfer/v1.0", _genjutsu_fields(prompt_required=False),
         _b_genjutsu, _c_rate(LIGHT_RATE, LIGHT_MAX_S), eta_s=150, face_consent=True,
         hint={"resolution": "480p", **_VIDEO_HINT}),
    Tool("item-swap", 5, "Замена предмета", KIND_VIDEO,
         "higgsfield/genjutsu-light/object-swap/v1.0", _genjutsu_fields(prompt_required=True),
         _b_genjutsu, _c_rate(LIGHT_RATE, LIGHT_MAX_S), eta_s=180, face_consent=True,
         frame_min_pixels=SWAP_MIN_PIXELS, hint={"resolution": "480p", **_VIDEO_HINT}),
    Tool("ad-creative", 6, "Рекламный креатив", KIND_IMAGE,
         "higgsfield/ads-studio/v1.0",
         (Field("prompt", "text", required=True, max_len=2000),
          Field("product_images", "images", min=0, max=4),
          Field("niche", "text", max_len=200),
          Field("audience", "text", max_len=300),
          Field("count", "int", default=1, min=1, max=4),
          Field("aspect", "enum", default="1:1", choices=("1:1", "4:5", "9:16", "16:9", "3:4", "4:3")),
          Field("language", "enum", default="ru", choices=("ru", "en", "ky"))),
         _b_ads, _c_ads, eta_s=90, hint={"count": 1}),
    Tool("photo-restyle", 7, "Преобразование фото", KIND_IMAGE,
         "marketing-studio/image",
         (Field("image", "image", required=True),
          Field("prompt", "text", required=True, max_len=2000),
          Field("quality", "enum", default="medium", choices=("low", "medium")),
          Field("resolution", "enum", default="1k", choices=("1k", "2k")),
          Field("aspect", "enum", default="auto", choices=("auto", "1:1", "3:4", "4:3", "9:16", "16:9")),
          CONSENT),
         _b_photo_restyle, _c_photo_restyle, eta_s=35, face_consent=True,
         hint={"quality": "medium", "resolution": "1k", "image": "_hint"}),
    Tool("text-to-image", 8, "Создание по описанию", KIND_IMAGE,
         "higgsfield-ai/soul/v2/standard",
         (Field("prompt", "text", required=True, max_len=1500),
          Field("style", "catalog", catalog="styles-v2"),
          Field("aspect", "enum", default="1:1", choices=SOUL_ASPECTS),
          Field("resolution", "enum", default="720p", choices=("720p", "1080p")),
          Field("count", "int", default=1, choices=(1, 4)),
          Field("character", "character")),
         _b_soul2, _c_soul(SOUL2_PRICE), eta_s=30,
         hint={"resolution": "720p", "count": 1}),
    Tool("virtual-blogger", 9, "Виртуальный блогер", KIND_IMAGE,
         "higgsfield/ai-influencer",
         (Field("options", "options", catalog="influencer"),
          Field("brief", "text", max_len=1000)),
         _b_influencer, _c_flat(INFLUENCER_PRICE), eta_s=60, hint={}),
    Tool("consistent-character", 10, "Постоянный персонаж", KIND_CHARACTER,
         "v1/custom-references",
         (Field("name", "text", required=True, max_len=60),
          Field("photos", "images", required=True, min=3, max=20),
          CONSENT),
         _b_character, _c_flat(CHARACTER_PRICE), eta_s=600, face_consent=True, hint={}),
    Tool("portrait", 11, "Фотореалистичный портрет", KIND_IMAGE,
         "higgsfield-ai/soul/standard",
         (Field("prompt", "text", required=True, max_len=1500),
          Field("style", "catalog", catalog="styles-v1"),
          Field("aspect", "enum", default="3:4", choices=SOUL_ASPECTS),
          Field("resolution", "enum", default="720p", choices=("720p", "1080p")),
          Field("count", "int", default=1, choices=(1, 4))),
         _b_soul1, _c_soul(SOUL1_PRICE), eta_s=30,
         hint={"resolution": "720p", "count": 1}),
    Tool("ad-campaign", 12, "Рекламная кампания", KIND_IMAGE,
         "marketing-studio/image", _ms_fields(qualities=("low", "medium", "high")),
         _ms_builder(preset_forces_high=True),
         _c_ms(MS20_PRICE, token=False, preset_forces_high=True), eta_s=35,
         hint={"quality": "medium", "resolution": "1k"}),
    Tool("ad-poster", 13, "Рекламный постер", KIND_IMAGE,
         "marketing-studio/image/flare", _ms_fields(qualities=("low", "medium", "high")),
         _ms_builder(preset_forces_high=False),
         _c_ms(PER_IMAGE_FLARE, token=True, preset_forces_high=False), eta_s=35,
         hint={"quality": "medium", "resolution": "1k"}),
    Tool("product-ad", 14, "Премиальная предметная реклама", KIND_IMAGE,
         "marketing-studio/image/sunburst", _ms_fields(qualities=("low", "medium", "high")),
         _ms_builder(preset_forces_high=False),
         _c_ms(PER_IMAGE_SUNBURST, token=True, preset_forces_high=False), eta_s=35,
         hint={"quality": "medium", "resolution": "1k"}),
    Tool("script-to-video", 15, "Сценарий в видео", KIND_VIDEO,
         "higgsfield/cinema-studio/4.0",
         (Field("prompt", "text", required=True, max_len=2000),
          Field("duration", "int", default=5, min=4, max=15),
          Field("resolution", "enum", default="720p", choices=("480p", "720p")),
          Field("aspect", "enum", default="16:9", choices=("16:9", "4:3", "1:1", "3:4", "9:16", "21:9")),
          Field("audio", "bool", default=True),
          Field("genre", "enum", choices=("auto",) + CINEMA_GENRES),
          Field("era", "enum", choices=("auto",) + CINEMA_ERAS),
          Field("light", "enum", choices=("auto",) + CINEMA_LIGHTS),
          Field("pacing", "enum", choices=("auto",) + CINEMA_PACING),
          Field("camera_movement", "enum", choices=("auto",) + CINEMA_CAMERA),
          Field("images", "images", min=0, max=4)),
         _b_cinema, _c_cinema, eta_s=240,
         hint={"duration": 5, "resolution": "480p", "aspect": "16:9"}),
)

_BY_ID = {t.id: t for t in TOOLS}
TOOL_IDS = tuple(t.id for t in TOOLS)

# Особые пределы по инструменту (сверх пределов поля).
# Marketing Studio с пресетом: 1–2 фото товара (сначала товар, затем модель).
MS_PRESET_IMAGES = (1, 2)
MS_TOOLS = ("ad-campaign", "ad-poster", "product-ad")


def get(tool_id) -> Tool | None:
    return _BY_ID.get(str(tool_id or ""))


# ---------------------------------------------------------------- проверка

@dataclass
class Validated:
    """Итог проверки: чистые параметры, свои загрузки и персонаж, ошибки по полям."""

    params: dict
    uploads: dict = field(default_factory=dict)     # uid → CreativeUpload
    character: Any = None                           # CreativeCharacter | None
    errors: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _err(name: str, code: str, **extra) -> dict:
    return {"field": name, "code": code, **extra}


def _clean_text(value) -> str:
    text = _CONTROL.sub("", str(value)).strip()
    return text


def _upload_uids(tool: Tool, raw: dict) -> set[str]:
    out: set[str] = set()
    for f in tool.fields:
        value = raw.get(f.name)
        if f.type in ("image", "video") and isinstance(value, str) and _UID_RE.match(value):
            out.add(value)
        elif f.type == "images" and isinstance(value, list):
            out.update(v for v in value if isinstance(v, str) and _UID_RE.match(v))
    return out


def _check_video(tool: Tool, f: Field, upload, errors: list) -> None:
    duration = float(upload.duration_s or 0)
    if duration < VIDEO_MIN_S:
        errors.append(_err(f.name, "too_short", min_s=VIDEO_MIN_S, duration_s=duration))
    elif duration > VIDEO_MAX_INPUT_S + VIDEO_DURATION_TOLERANCE_S:
        errors.append(_err(f.name, "too_long", max_s=VIDEO_MAX_INPUT_S, duration_s=duration))
    if tool.frame_min_pixels and upload.pixels < tool.frame_min_pixels:
        errors.append(_err(f.name, "too_small_frame", min_pixels=tool.frame_min_pixels,
                           w=upload.w, h=upload.h))


def _check_options(f: Field, value, catalog_lookup, errors: list):
    """options виртуального блогера: {категория: [ключи]} по каталогу (уровень normal)."""
    if value in (None, "", {}):
        return {}
    if not isinstance(value, dict):
        errors.append(_err(f.name, "bad_type"))
        return {}
    categories = catalog_lookup("influencer") if catalog_lookup else None
    if not categories:
        errors.append(_err(f.name, "catalog_unavailable"))
        return {}
    by_key = {c["key"]: c for c in categories}
    clean: dict = {}
    for key, picked in value.items():
        cat = by_key.get(key)
        if cat is None:
            errors.append(_err(f.name, "bad_value", category=str(key)[:40]))
            continue
        if isinstance(picked, str):
            picked = [picked]
        if not isinstance(picked, list) or not all(isinstance(v, str) for v in picked):
            errors.append(_err(f.name, "bad_type", category=key))
            continue
        picked = list(dict.fromkeys(picked))
        if not picked:
            continue
        options = {o["key"]: o for o in cat.get("options") or []}
        unknown = [v for v in picked if v not in options]
        if unknown:
            errors.append(_err(f.name, "bad_value", category=key, value=unknown[0][:40]))
            continue
        limit = max(1, int(cat.get("max") or 1))
        if len(picked) > limit:
            errors.append(_err(f.name, "too_many", category=key, max=limit))
            continue
        if len(picked) > 1 and any(options[v].get("exclusive") for v in picked):
            errors.append(_err(f.name, "bad_value", category=key, reason="exclusive"))
            continue
        clean[key] = picked
    return clean


def validate(tool: Tool, raw, *, user=None, catalog_lookup=None) -> Validated:
    """Проверить параметры формы. Ничего не отправляет и не пишет в БД.

    user — владелец загрузок и персонажей (чужой uid неотличим от несуществующего).
    catalog_lookup(kind) → для catalog: множество id (или None — каталог не
    известен, проверяем только вид uuid); для influencer — список категорий.
    """
    from .models import CreativeCharacter, CreativeUpload

    raw = raw if isinstance(raw, dict) else {}
    errors: list = []
    params: dict = {}
    uploads: dict = {}
    if user is not None and getattr(user, "pk", None):
        wanted = _upload_uids(tool, raw)
        if wanted:
            uploads = {u.uid: u for u in CreativeUpload.objects.filter(user=user, uid__in=wanted)}
    character = None

    def upload_for(name: str, uid, kind: str):
        if not isinstance(uid, str) or not _UID_RE.match(uid):
            errors.append(_err(name, "bad_value"))
            return None
        row = uploads.get(uid)
        if row is None:
            errors.append(_err(name, "not_found"))
            return None
        if row.kind != kind:
            errors.append(_err(name, "wrong_kind", expected=kind))
            return None
        return row

    for f in tool.fields:
        value = raw.get(f.name)
        empty = value is None or value == "" or value == []
        if f.type == "bool":
            if empty:
                if f.required:
                    errors.append(_err(f.name, "consent_required" if f.name == "consent" else "required"))
                    continue
                params[f.name] = bool(f.default)
                continue
            if not isinstance(value, bool):
                errors.append(_err(f.name, "bad_type"))
                continue
            if f.required and value is not True:
                errors.append(_err(f.name, "consent_required" if f.name == "consent" else "required"))
                continue
            params[f.name] = value
            continue

        if empty:
            if f.required:
                errors.append(_err(f.name, "required"))
            elif f.default is not None:
                params[f.name] = f.default
            continue

        if f.type == "text":
            if not isinstance(value, str):
                errors.append(_err(f.name, "bad_type"))
                continue
            text = _clean_text(value)
            if not text:
                if f.required:
                    errors.append(_err(f.name, "required"))
                continue
            if f.max_len and len(text) > f.max_len:
                errors.append(_err(f.name, "too_long", max=f.max_len))
                continue
            params[f.name] = text
        elif f.type == "enum":
            if not isinstance(value, str) or value not in f.choices:
                errors.append(_err(f.name, "bad_value", choices=list(f.choices)))
                continue
            if value == "auto" and f.default is None:
                continue          # «авто» без значения по умолчанию = поле не отправлять
            params[f.name] = value
        elif f.type == "int":
            if isinstance(value, bool) or not isinstance(value, (int, str)):
                errors.append(_err(f.name, "bad_type"))
                continue
            try:
                number = int(value)
            except (TypeError, ValueError):
                errors.append(_err(f.name, "bad_type"))
                continue
            if f.choices and number not in f.choices:
                errors.append(_err(f.name, "bad_value", choices=list(f.choices)))
                continue
            if (f.min is not None and number < f.min) or (f.max is not None and number > f.max):
                errors.append(_err(f.name, "out_of_range", min=f.min, max=f.max))
                continue
            params[f.name] = number
        elif f.type in ("image", "video"):
            row = upload_for(f.name, value, f.type)
            if row is None:
                continue
            if f.type == "video":
                _check_video(tool, f, row, errors)
            params[f.name] = row.uid
        elif f.type == "images":
            if isinstance(value, str):
                value = [value]
            if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                errors.append(_err(f.name, "bad_type"))
                continue
            value = list(dict.fromkeys(value))
            lo = f.min or 0
            hi = f.max if f.max is not None else 99
            if len(value) < lo:
                errors.append(_err(f.name, "too_few", min=lo))
                continue
            if len(value) > hi:
                errors.append(_err(f.name, "too_many", max=hi))
                continue
            rows = [upload_for(f.name, uid, "image") for uid in value]
            if any(r is None for r in rows):
                continue
            params[f.name] = [r.uid for r in rows]
        elif f.type == "catalog":
            if not isinstance(value, str) or not _is_uuid(value):
                errors.append(_err(f.name, "bad_value"))
                continue
            known = catalog_lookup(f.catalog) if catalog_lookup else None
            if known is not None and value not in known:
                errors.append(_err(f.name, "bad_value"))
                continue
            params[f.name] = value
        elif f.type == "character":
            if not isinstance(value, str) or not _UID_RE.match(value) or user is None:
                errors.append(_err(f.name, "not_found"))
                continue
            character = (CreativeCharacter.objects
                         .filter(user=user, uid=value, deleted_at__isnull=True).first())
            if character is None:
                errors.append(_err(f.name, "not_found"))
                continue
            if character.status != CreativeCharacter.STATUS_READY or not character.provider_id:
                errors.append(_err(f.name, "character_not_ready"))
                character = None
                continue
            params[f.name] = character.uid
        elif f.type == "options":
            clean = _check_options(f, value, catalog_lookup, errors)
            if clean:
                params[f.name] = clean
        else:  # pragma: no cover — опечатка в реестре
            errors.append(_err(f.name, "bad_value"))

    # Правила между полями.
    if tool.id in MS_TOOLS and params.get("preset"):
        n = len(params.get("product_images") or [])
        lo, hi = MS_PRESET_IMAGES
        if n < lo:
            errors.append(_err("product_images", "too_few", min=lo))
        elif n > hi:
            errors.append(_err("product_images", "too_many", max=hi))
    used = {params.get(n) for n in ("image", "video") if params.get(n)}
    for n in ("images", "product_images", "photos"):
        used.update(params.get(n) or [])
    uploads = {uid: row for uid, row in uploads.items() if uid in used}
    return Validated(params=params, uploads=uploads, character=character, errors=errors)


def build_body(tool: Tool, params: dict, ctx: BuildCtx) -> dict:
    """JSON-тело поставщику. Бросает KeyError, если нет ссылки на загрузку."""
    return tool.build(params, ctx)


def cost_usd(tool: Tool, params: dict, inputs: dict | None = None) -> Decimal:
    """Себестоимость задачи в долларах по формулам §2."""
    return tool.cost(params, inputs or {})


def hint_params(tool: Tool) -> tuple[dict, dict]:
    """(params, inputs) для «цена от …» и примеров админки: значения по умолчанию +
    подсказка инструмента; видео — 5 секунд 854×480."""
    params = {f.name: f.default for f in tool.fields if f.default is not None}
    inputs: dict = {}
    hint = dict(tool.hint)
    duration = hint.pop("_duration", None)
    w = hint.pop("_w", None)
    h = hint.pop("_h", None)
    params.update({k: v for k, v in hint.items() if v != "_hint"})
    for k, v in tool.hint.items():
        if v == "_hint":
            params[k] = "hint"
    if duration is not None:
        params["video"] = "hint"
        inputs["hint"] = SimpleNamespace(duration_s=duration, w=w, h=h, pixels=(w or 0) * (h or 0))
    return params, inputs


def public_tools() -> list[dict]:
    """Описание инструментов для сайта: без адресов моделей."""
    return [{"id": t.id, "n": t.n, "kind": t.kind, "face_consent": t.face_consent} for t in TOOLS]


__all__ = ["TOOLS", "TOOL_IDS", "Tool", "Field", "BuildCtx", "Validated", "get", "validate",
           "build_body", "cost_usd", "hint_params", "cinema_tokens", "public_tools",
           "REASON_BY_KIND", "KIND_IMAGE", "KIND_VIDEO", "KIND_CHARACTER"]
