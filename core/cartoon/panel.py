"""Библиотека сцен мультстудии в панели (admin-new «Сцены мультстудии»).

Клиент (12.10.2026): владелец сам добавляет и публикует сцены библиотеки, а
пользователи выбирают их для своих мультфильмов. Раньше это делалось кодом
(cartoon/library.py + seed_presets) и командами по SSH.

Правила панели живут здесь, а не во вьюхах (как у витрины видеостудии):
проверка полей с текстами по-русски, запись в журнал действий
(audit.AdminActionLog) в одной транзакции с правкой, сборка превью.

Превью. Владелец загружает mp4, а лёгкую копию для ленты, обложку и миниатюру
собирает задача в общей очереди (tasks.build_preset_preview): ffmpeg работает
секунды и не должен держать запрос панели. Пока копии нет, лента играет сам
ролик — сцена видна в библиотеке сразу после публикации. Ход сборки панель
видит по отметке в кэше (preview_json): отдельного поля в базе ради этого не
заводили — после сборки всё видно по самим файлам.

Опубликовать как новую сцену можно и «свою сцену» пользователя из «Работ»
(publish_from_scene) — только если в её кадр не могло попасть ничего личного.
"""
from __future__ import annotations

import logging
import re
import uuid
from functools import partial

from django.core.cache import cache
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import IntegrityError, transaction
from django.db.models import Count, F, Q
from django.db.models.deletion import ProtectedError
from django.utils.text import slugify
from rest_framework import status as http
from rest_framework.exceptions import APIException

from audit.services import log_admin_action

from .library import ADULT_STYLE, STYLE
from .models import CartoonCategory, CartoonCharacter, CartoonPreset, CartoonScene
from .services import CUSTOM_PRESET_SLUG
from .thumbs import POSTER_BOX, make_thumb
from .views import STUDIO_ASPECTS

logger = logging.getLogger(__name__)

# Своего кода у библиотеки в журнале нет: список кодов закрытый
# (audit.models.ADMIN_ACTIONS). Как и витрина видеостудии, правки пишутся
# кодом settings.edit, а что меняли — видно по типу объекта и ключу.
LOG_ACTION = "settings.edit"
PRESET_KEY = "cartoon_preset"
SECTION_KEY = "cartoon_section"

TITLE_MAX = CartoonPreset._meta.get_field("title").max_length
SUBTITLE_MAX = CartoonPreset._meta.get_field("subtitle").max_length
SLUG_MAX = CartoonPreset._meta.get_field("slug").max_length
SECTION_TITLE_MAX = CartoonCategory._meta.get_field("title").max_length
SECTION_SLUG_MAX = CartoonCategory._meta.get_field("slug").max_length
EMOJI_MAX = CartoonCategory._meta.get_field("emoji").max_length
# Промпт библиотечной сцены — одна-две фразы; длиннее модель начинает
# терять героя, а у своей сцены потолок и того меньше (services.form_custom_scene).
PROMPT_MAX = 2000
MOTION_MAX = 1000
SORT_MAX = 100_000
SORT_STEP = 10
DURATION_MIN = 2
DURATION_MAX = 15
DURATION_DEFAULT = 5
AUDIENCES = (("kids", "Для детей"), ("adults", "Для взрослых"))
AUDIENCE_KEYS = tuple(key for key, _label in AUDIENCES)
# Стиль кадра следует за аудиторией, как у сцен из кода (library.style_for_preset).
STYLE_BY_AUDIENCE = {"kids": STYLE, "adults": ADULT_STYLE}

# nginx пропускает в /api/ до 25 МБ вместе с обёрткой формы.
PREVIEW_MAX_BYTES = 24 * 1024 * 1024
PREVIEW_MIN_SECONDS = 1
PREVIEW_MAX_SECONDS = 20
# Лёгкую копию ffmpeg делает из байтов в памяти — больше не читаем (тот же
# потолок, что у витрины видеостудии).
CLIP_SOURCE_MAX_BYTES = 64 * 1024 * 1024

BUILD_KEY = "cartoon:preset_preview:{}"
# Сколько считать сборку идущей: лимит задачи 6 минут плюс очередь. Отметка
# пропала, а копий нет — значит сборка не дошла, и панель предложит повторить.
BUILD_TTL = 15 * 60
NOTES_TTL = 24 * 60 * 60

_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_TRANSLIT = str.maketrans({
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "ts",
    "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu",
    "я": "ya", "ң": "ng", "ө": "o", "ү": "u",
})

PRESET_TEXTS = (
    ("title", "Название", TITLE_MAX), ("title_en", "Название (EN)", TITLE_MAX),
    ("title_kg", "Название (KG)", TITLE_MAX), ("subtitle", "Подпись", SUBTITLE_MAX),
    ("subtitle_en", "Подпись (EN)", SUBTITLE_MAX), ("subtitle_kg", "Подпись (KG)", SUBTITLE_MAX),
)
SECTION_TEXTS = (
    ("title", "Название раздела", SECTION_TITLE_MAX),
    ("title_en", "Название раздела (EN)", SECTION_TITLE_MAX),
    ("title_kg", "Название раздела (KG)", SECTION_TITLE_MAX),
)
PRESET_LOG_FIELDS = (
    "slug", "title", "title_en", "title_kg", "subtitle", "subtitle_en", "subtitle_kg",
    "category_id", "audience", "is_pick", "sort_order", "is_active", "aspect_ratio",
    "duration", "scene_prompt", "motion_prompt", "style_prompt", "preview_video",
)
SECTION_LOG_FIELDS = ("slug", "title", "title_en", "title_kg", "emoji", "sort_order", "is_active")


class PanelError(APIException):
    """Отказ панели: текст человеку и код ответа.

    DRF отдаёт его телом {"detail": "<текст>"}, как остальная панель, и
    откатывает транзакцию запроса.
    """

    def __init__(self, detail: str, *, status: int = http.HTTP_400_BAD_REQUEST):
        super().__init__(detail=detail)
        self.status_code = status


# ---------------------------------------------------------------- что видит панель

def _url(field) -> str:
    try:
        return field.url if field else ""
    except Exception:
        return ""


def _iso(value) -> str | None:
    return value.isoformat() if value else None


def preset_state(p: CartoonPreset) -> str:
    """Видна ли сцена в библиотеке, а если нет — почему. Тот же фильтр, что у views.PresetsView."""
    if not p.is_active:
        return "unpublished"
    if not p.preview_video:
        return "no_preview"
    if p.category_id and not p.category.is_active:
        return "section_hidden"
    return "live"


def _build_infos(pks) -> dict:
    keys = {BUILD_KEY.format(pk): pk for pk in pks}
    try:
        found = cache.get_many(list(keys))
    except Exception:
        # Кэш лёг — панель работает, только без хода сборки.
        logger.warning("сцены панели: отметки сборки превью не прочитались", exc_info=True)
        return {}
    return {keys[key]: value for key, value in found.items() if isinstance(value, dict)}


def _set_build(pk, value: dict, ttl: int) -> None:
    try:
        cache.set(BUILD_KEY.format(pk), value, ttl)
    except Exception:
        logger.warning("сцены панели: отметка сборки превью сцены %s не записалась", pk,
                       exc_info=True)


def preview_json(p: CartoonPreset, info: dict | None = None) -> dict:
    """Превью сцены и ход его сборки.

    state: none — ролика нет; building — собираются лёгкие копии; ready — всё
    на месте; partial — ролик есть, но лёгкой копии или обложки нет (сборка не
    удалась или не дошла): лента играет сам ролик, можно пересобрать.
    """
    source = p.preview_video.name if p.preview_video else ""
    info = info or {}
    mine = info.get("source") == source
    if mine and info.get("state") == "building":
        state = "building"
    elif not source:
        state = "none"
    elif p.preview_clip and p.preview_poster and p.preview_thumb:
        state = "ready"
    else:
        state = "partial"
    return {
        "state": state,
        "notes": list(info.get("notes") or []) if mine and state != "building" else [],
        "video": _url(p.preview_video),
        "clip": _url(p.preview_clip),
        "poster": _url(p.preview_poster),
        "thumb": _url(p.preview_thumb),
    }


def _credits(p: CartoonPreset) -> int | None:
    try:
        return p.estimated_credits()
    except Exception:
        logger.warning("сцены панели: цена сцены %s не посчиталась", p.pk, exc_info=True)
        return None


def scene_row(p: CartoonPreset, *, used: int | None = None, info: dict | None = None) -> dict:
    """Сцена глазами панели: всё, что правится, и почему её не видно на сайте.

    info — отметка сборки превью; None — прочитать её здесь, {} — отметки нет.
    """
    if used is None:
        used = getattr(p, "used", None)
    if used is None:
        used = CartoonScene.objects.filter(preset=p).count()
    if info is None:
        info = _build_infos([p.pk]).get(p.pk)
    return {
        "id": p.pk,
        "slug": p.slug,
        "title": p.title,
        "title_en": p.title_en,
        "title_kg": p.title_kg,
        "subtitle": p.subtitle,
        "subtitle_en": p.subtitle_en,
        "subtitle_kg": p.subtitle_kg,
        "section_id": p.category_id,
        "audience": p.audience,
        "is_pick": p.is_pick,
        "sort_order": p.sort_order,
        "is_active": p.is_active,
        "aspect_ratio": p.aspect_ratio,
        "duration": p.duration,
        "scene_prompt": p.scene_prompt,
        "motion_prompt": p.motion_prompt,
        "state": preset_state(p),
        "preview": preview_json(p, info),
        "credits": _credits(p),
        "used_in": used,
        # Сцену, взятую хоть в один мультфильм, не удаляем — только снимаем с публикации.
        "can_delete": used == 0,
        "created_at": _iso(p.created_at),
    }


def section_row(c: CartoonCategory, counts: dict | None = None) -> dict:
    total, published = (counts or {}).get(c.pk, (0, 0))
    return {
        "id": c.pk,
        "slug": c.slug,
        "title": c.title,
        "title_en": c.title_en,
        "title_kg": c.title_kg,
        "emoji": c.emoji,
        "sort_order": c.sort_order,
        "is_active": c.is_active,
        "scenes": total,
        "published": published,
    }


def _presets():
    # Служебная сцена «Своя сцена» (services.custom_base_preset) — не часть
    # библиотеки: её правка сломала бы своих сцен всех пользователей.
    return CartoonPreset.objects.exclude(slug=CUSTOM_PRESET_SLUG)


def sections_rows() -> list[dict]:
    rows = (_presets().exclude(category__isnull=True).order_by().values("category_id")
            .annotate(total=Count("id"),
                      published=Count("id", filter=Q(is_active=True) & ~Q(preview_video=""))))
    counts = {r["category_id"]: (r["total"], r["published"]) for r in rows}
    return [section_row(c, counts) for c in CartoonCategory.objects.order_by("sort_order", "id")]


def scenes_qs():
    return (_presets().select_related("category", "image_model", "video_model")
            .annotate(used=Count("scenes"))
            .order_by(F("category__sort_order").asc(nulls_last=True), "sort_order", "id"))


def _flag(raw, name: str):
    value = str(raw or "").strip().lower()
    if value == "":
        return None
    if value in ("1", "true"):
        return True
    if value in ("0", "false"):
        return False
    raise PanelError(f"{name}: 1 или 0")


def filter_scenes(qs, params):
    """Фильтры списка: раздел, аудитория, опубликована, «Выбор EsAI», поиск."""
    section = str(params.get("section") or "").strip()
    if section == "none":
        qs = qs.filter(category__isnull=True)
    elif section:
        if not section.isdigit():
            raise PanelError("Раздел: номер раздела или none")
        qs = qs.filter(category_id=int(section))
    audience = str(params.get("audience") or "").strip()
    if audience:
        if audience not in AUDIENCE_KEYS:
            raise PanelError("Для кого: kids или adults")
        qs = qs.filter(audience=audience)
    published = _flag(params.get("published"), "Опубликована")
    if published is not None:
        qs = qs.filter(is_active=published)
    pick = _flag(params.get("pick"), "«Выбор EsAI»")
    if pick is not None:
        qs = qs.filter(is_pick=pick)
    query = str(params.get("q") or "").strip()[:200]
    if query:
        qs = qs.filter(Q(title__icontains=query) | Q(title_en__icontains=query)
                       | Q(title_kg__icontains=query) | Q(subtitle__icontains=query)
                       | Q(slug__icontains=query) | Q(scene_prompt__icontains=query))
    return qs


def scene_rows(qs) -> list[dict]:
    items = list(qs)
    infos = _build_infos([p.pk for p in items])
    return [scene_row(p, info=infos.get(p.pk) or {}) for p in items]


def get_scene(pk) -> CartoonPreset:
    preset = scenes_qs().filter(pk=pk).first()
    if preset is None:
        raise PanelError("Сцена не найдена", status=http.HTTP_404_NOT_FOUND)
    return preset


def get_section(pk) -> CartoonCategory:
    section = CartoonCategory.objects.filter(pk=pk).first()
    if section is None:
        raise PanelError("Раздел не найден", status=http.HTTP_404_NOT_FOUND)
    return section


def limits() -> dict:
    """Границы полей — форме панели, чтобы она проверяла то же, что сервер."""
    return {
        "title_max": TITLE_MAX, "subtitle_max": SUBTITLE_MAX, "slug_max": SLUG_MAX,
        "section_title_max": SECTION_TITLE_MAX, "emoji_max": EMOJI_MAX,
        "scene_prompt_max": PROMPT_MAX, "motion_prompt_max": MOTION_MAX,
        "sort_max": SORT_MAX, "duration_min": DURATION_MIN, "duration_max": DURATION_MAX,
        "duration_default": DURATION_DEFAULT,
        "preview_max_bytes": PREVIEW_MAX_BYTES, "preview_min_seconds": PREVIEW_MIN_SECONDS,
        "preview_max_seconds": PREVIEW_MAX_SECONDS,
    }


# ---------------------------------------------------------------- проверка полей

def _text(data, name: str, label: str, limit: int, *, collapse: bool = True) -> str:
    value = data[name]
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise PanelError(f"{label} — строка")
    value = re.sub(r"\s+", " ", value).strip() if collapse else value.strip()
    if len(value) > limit:
        raise PanelError(f"{label} длиннее {limit} символов")
    return value


def _bool(data, name: str, label: str) -> bool:
    value = data[name]
    # Только настоящий булев: строка "false" из формы не должна опубликовать сцену.
    if not isinstance(value, bool):
        raise PanelError(f"{label}: true или false")
    return value


def _int(data, name: str, label: str, low: int, high: int, unit: str = "") -> int:
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise PanelError(f"{label} — целое число{unit} от {low} до {high}")
    return value


def _check_slug(model, raw, limit: int) -> str:
    if not isinstance(raw, str) or not _SLUG_RE.match(raw) or len(raw) > limit:
        raise PanelError(f"Код — латиница в нижнем регистре, цифры и дефисы, до {limit} символов")
    if raw == CUSTOM_PRESET_SLUG or model.objects.filter(slug=raw).exists():
        raise PanelError(f"Код «{raw}» уже занят")
    return raw


def _slug_base(text: str) -> str:
    base = slugify(str(text or "").lower().translate(_TRANSLIT)).replace("_", "-")
    return re.sub(r"-{2,}", "-", base)[:60].strip("-")


def _free_slug(model, text: str, prefix: str) -> str:
    """Код по названию латиницей; занят — с номером. Без букв — нейтральный."""
    base = _slug_base(text) or f"{prefix}-{uuid.uuid4().hex[:8]}"
    candidate, n = base, 2
    while candidate == CUSTOM_PRESET_SLUG or model.objects.filter(slug=candidate).exists():
        candidate = f"{base}-{n}"
        n += 1
        if n > 50:
            candidate = f"{base}-{uuid.uuid4().hex[:8]}"
            break
    return candidate


def clean_scene(data, *, creating: bool) -> dict:
    """Поля сцены из тела запроса. Все проверки — до первой записи.

    Ключи ответа — имена полей модели (category_id вместо section_id).
    Незнакомые ключи не мешают: форма может прислать строку целиком.
    """
    out: dict = {}
    for name, label, limit in PRESET_TEXTS:
        if name in data:
            out[name] = _text(data, name, label, limit)
    if creating and not out.get("title"):
        raise PanelError("Название обязательно")
    if "title" in out and not out["title"]:
        raise PanelError("Название не может быть пустым")
    if "scene_prompt" in data:
        out["scene_prompt"] = _text(data, "scene_prompt", "Промпт сцены", PROMPT_MAX, collapse=False)
        if not out["scene_prompt"]:
            raise PanelError("Промпт сцены обязателен: по-английски, что происходит в кадре, "
                             "герой — словом character")
    elif creating:
        raise PanelError("Промпт сцены обязателен: по-английски, что происходит в кадре, "
                         "герой — словом character")
    if "motion_prompt" in data:
        out["motion_prompt"] = _text(data, "motion_prompt", "Промпт движения", MOTION_MAX,
                                     collapse=False)
    if "section_id" in data:
        section = data["section_id"]
        if section is None:
            out["category_id"] = None
        else:
            if isinstance(section, bool) or not isinstance(section, int):
                raise PanelError("Раздел — номер раздела или null")
            if not CartoonCategory.objects.filter(pk=section).exists():
                raise PanelError("Раздел не найден")
            out["category_id"] = section
    if "audience" in data:
        if data["audience"] not in AUDIENCE_KEYS:
            raise PanelError("Для кого: kids или adults")
        out["audience"] = data["audience"]
    if "is_pick" in data:
        out["is_pick"] = _bool(data, "is_pick", "«Выбор EsAI»")
    if "is_active" in data:
        out["is_active"] = _bool(data, "is_active", "Показ в библиотеке")
    if "sort_order" in data:
        out["sort_order"] = _int(data, "sort_order", "Порядок", 0, SORT_MAX)
    if "aspect_ratio" in data:
        if data["aspect_ratio"] not in STUDIO_ASPECTS:
            raise PanelError("Пропорции: " + ", ".join(STUDIO_ASPECTS))
        out["aspect_ratio"] = data["aspect_ratio"]
    if "duration" in data:
        out["duration"] = _int(data, "duration", "Длительность", DURATION_MIN, DURATION_MAX,
                               " секунд")
    return out


def clean_section(data, *, creating: bool) -> dict:
    out: dict = {}
    for name, label, limit in SECTION_TEXTS:
        if name in data:
            out[name] = _text(data, name, label, limit)
    if creating and not out.get("title"):
        raise PanelError("Название раздела обязательно")
    if "title" in out and not out["title"]:
        raise PanelError("Название раздела не может быть пустым")
    if "emoji" in data:
        out["emoji"] = _text(data, "emoji", "Значок", EMOJI_MAX).replace(" ", "")
    if "sort_order" in data:
        out["sort_order"] = _int(data, "sort_order", "Порядок", 0, SORT_MAX)
    if "is_active" in data:
        out["is_active"] = _bool(data, "is_active", "Показ раздела")
    return out


def _snapshot(obj, fields) -> dict:
    out = {}
    for name in fields:
        value = getattr(obj, name)
        out[name] = value.name if hasattr(value, "name") and hasattr(value, "storage") else value
    return out


def _next_sort(qs) -> int:
    """Новая строка встаёт в конец своего раздела, а не в его середину."""
    top = qs.order_by("-sort_order").values_list("sort_order", flat=True).first()
    return min(SORT_MAX, (top or 0) + SORT_STEP)


def _template() -> CartoonPreset:
    """Откуда новой сцене взять модели и качество: у готовой сцены библиотеки.

    Модель видео в форме не выбирается (выбор модели на мультфильм — отдельная
    фаза): берём то, на чём снята библиотека, как и служебная «Своя сцена».
    """
    template = (_presets().filter(is_active=True).exclude(preview_video="")
                .select_related("image_model", "video_model").order_by("id").first())
    if template is None:
        template = CartoonPreset.objects.filter(slug=CUSTOM_PRESET_SLUG).select_related(
            "image_model", "video_model").first()
    if template is None:
        raise PanelError("В библиотеке нет ни одной готовой сцены — новой не у кого взять "
                         "модели. Сначала заведите библиотеку командой seed_presets")
    return template


# ---------------------------------------------------------------- правки сцен

def create_scene(data, *, actor, request=None) -> CartoonPreset:
    fields = clean_scene(data, creating=True)
    slug = (_check_slug(CartoonPreset, data["slug"], SLUG_MAX) if data.get("slug")
            else _free_slug(CartoonPreset, fields["title"], "scene"))
    template = _template()
    audience = fields.get("audience", "adults")
    if "sort_order" not in fields:
        fields["sort_order"] = _next_sort(_presets().filter(category_id=fields.get("category_id")))
    # Новая сцена не видна, пока владелец её не опубликует: превью ещё нет.
    fields.setdefault("is_active", False)
    fields.setdefault("duration", DURATION_DEFAULT)
    try:
        with transaction.atomic():
            preset = CartoonPreset.objects.create(
                slug=slug, image_model=template.image_model, video_model=template.video_model,
                resolution=template.resolution, style_prompt=STYLE_BY_AUDIENCE[audience],
                **fields)
            # В журнал — в той же транзакции: не записалось, откатится и сцена.
            log_admin_action(actor, LOG_ACTION, target=preset, before={PRESET_KEY: None},
                             after={PRESET_KEY: _snapshot(preset, PRESET_LOG_FIELDS)},
                             request=request)
    except IntegrityError:
        # Тот же код успели занять параллельным запросом.
        raise PanelError(f"Код «{slug}» уже занят")
    return preset


def edit_scene(preset: CartoonPreset, data, *, actor, request=None) -> CartoonPreset:
    """Поправить сцену. Те же значения — ни записи в базу, ни строки в журнале."""
    if "slug" in data and data["slug"] != preset.slug:
        # По коду сцену находят «Популярное» и сохранённые ленты гостей.
        raise PanelError("Код сцены после создания не меняется")
    new = clean_scene(data, creating=False)
    if not new:
        raise PanelError("Нечего менять")
    changed = {name: value for name, value in new.items() if getattr(preset, name) != value}
    # Стиль следует за аудиторией, но только библиотечный: свой стиль, заданный
    # в Django-админке, не трогаем.
    if "audience" in changed and preset.style_prompt in ("", *STYLE_BY_AUDIENCE.values()):
        style = STYLE_BY_AUDIENCE[changed["audience"]]
        if style != preset.style_prompt:
            changed["style_prompt"] = style
    if not changed:
        return preset
    before = {name: getattr(preset, name) for name in changed}
    with transaction.atomic():
        for name, value in changed.items():
            setattr(preset, name, value)
        preset.save(update_fields=list(changed))
        log_admin_action(actor, LOG_ACTION, target=preset, before={PRESET_KEY: before},
                         after={PRESET_KEY: changed}, request=request)
    return preset


def delete_scene(preset: CartoonPreset, *, actor, request=None) -> None:
    """Удалить сцену, которую ещё никто не взял. Взятую — только снять с публикации."""
    used = CartoonScene.objects.filter(preset=preset).count()
    refusal = (f"Сцену уже взяли в мультфильмы ({used}) — удалить нельзя. Снимите её с "
               "публикации: из библиотеки она пропадёт, а готовые мультфильмы останутся целы")
    if used:
        raise PanelError(refusal, status=http.HTTP_409_CONFLICT)
    pk, slug = preset.pk, preset.slug
    try:
        with transaction.atomic():
            old = _locked_files(pk)
            # Журнал — до удаления: после него у строки уже нет номера. Код
            # в снимке нужен seed_presets, чтобы не вернуть удалённую сцену.
            log_admin_action(actor, LOG_ACTION, target=preset,
                             before={PRESET_KEY: _snapshot(preset, PRESET_LOG_FIELDS)},
                             after={PRESET_KEY: None}, request=request)
            preset.delete()
            if old:
                _drop_later(pk, slug, old, {})
    except ProtectedError:
        # Сцену взяли в мультфильм, пока шёл запрос.
        raise PanelError(refusal, status=http.HTTP_409_CONFLICT)


# ---------------------------------------------------------------- правки разделов

def create_section(data, *, actor, request=None) -> CartoonCategory:
    fields = clean_section(data, creating=True)
    slug = (_check_slug(CartoonCategory, data["slug"], SECTION_SLUG_MAX) if data.get("slug")
            else _free_slug(CartoonCategory, fields["title"], "section"))
    if "sort_order" not in fields:
        fields["sort_order"] = _next_sort(CartoonCategory.objects.all())
    try:
        with transaction.atomic():
            section = CartoonCategory.objects.create(slug=slug, **fields)
            log_admin_action(actor, LOG_ACTION, target=section, before={SECTION_KEY: None},
                             after={SECTION_KEY: _snapshot(section, SECTION_LOG_FIELDS)},
                             request=request)
    except IntegrityError:
        raise PanelError(f"Код «{slug}» уже занят")
    return section


def edit_section(section: CartoonCategory, data, *, actor, request=None) -> CartoonCategory:
    if "slug" in data and data["slug"] != section.slug:
        # По коду раздела сайт открывает вкладку библиотеки.
        raise PanelError("Код раздела после создания не меняется")
    new = clean_section(data, creating=False)
    if not new:
        raise PanelError("Нечего менять")
    changed = {name: value for name, value in new.items() if getattr(section, name) != value}
    if not changed:
        return section
    before = {name: getattr(section, name) for name in changed}
    with transaction.atomic():
        for name, value in changed.items():
            setattr(section, name, value)
        section.save(update_fields=list(changed))
        log_admin_action(actor, LOG_ACTION, target=section, before={SECTION_KEY: before},
                         after={SECTION_KEY: changed}, request=request)
    return section


# ---------------------------------------------------------------- превью

def _stem(preset: CartoonPreset) -> str:
    # Имя всякий раз новое: пересобранную копию CDN не отдаст из кэша под старым адресом.
    return f"{preset.slug[:60]}-{uuid.uuid4().hex[:8]}"


PREVIEW_FIELDS = ("preview_video", "preview_clip", "preview_poster", "preview_thumb")
# Лёгкая копия и миниатюра — производные файлы одной сцены, их пишут только
# сборки. Ролик и обложка бывают чужими: «Сделать превью сцены» ставит файлы
# сцены пользователя, render_previews — оплаченный оригинал <код>.mp4. Их
# стираем, только если имя — то, что дала панель (_stem).
DERIVED_FIELDS = ("preview_clip", "preview_thumb")


def _own_file(slug: str, name: str) -> bool:
    pattern = rf"cartoon/(?:previews|posters)/{re.escape(slug[:60])}-[0-9a-f]{{8}}\.\w+"
    return bool(re.fullmatch(pattern, name))


def _locked_files(pk) -> dict | None:
    """Файлы превью из запертой строки: сборка могла сменить их после чтения сцены."""
    row = CartoonPreset.objects.select_for_update().filter(pk=pk).values(*PREVIEW_FIELDS).first()
    return {name: value or "" for name, value in row.items()} if row is not None else None


def _delete(names) -> None:
    for name in names:
        if not name:
            continue
        try:
            default_storage.delete(name)
        except Exception:
            logger.warning("сцены панели: лишний файл %s не удалился", name, exc_info=True)


def _drop_later(pk, slug: str, old: dict, new: dict) -> None:
    """Стереть файлы, на которые сцена больше не смотрит, — после фиксации.

    Откатится правка — строка всё ещё смотрит на прежние файлы. Файл, на
    который смотрит другая сцена, остаётся.
    """
    names = [value for field, value in old.items()
             if value and value != new.get(field, "")
             and (field in DERIVED_FIELDS or _own_file(slug, value))]
    if not names:
        return
    shared = Q()
    for field in PREVIEW_FIELDS:
        shared |= Q(**{f"{field}__in": names})
    used = set()
    for row in CartoonPreset.objects.exclude(pk=pk).filter(shared).values_list(*PREVIEW_FIELDS):
        used.update(row)
    names = [name for name in names if name not in used]
    if names:
        transaction.on_commit(partial(_delete, names))


def _probe(blob: bytes) -> dict:
    from ai.video_edit import probe_video

    try:
        return probe_video(blob) or {}
    except Exception:
        logger.warning("сцены панели: ffprobe не прочитал загруженный ролик", exc_info=True)
        return {}


def check_upload(upload) -> None:
    """Загруженный ролик: mp4, не больше 24 МБ, от 1 до 20 секунд."""
    if upload is None:
        raise PanelError("Приложите ролик: поле file, формат MP4")
    size = int(getattr(upload, "size", 0) or 0)
    if size > PREVIEW_MAX_BYTES:
        raise PanelError(f"Ролик больше {PREVIEW_MAX_BYTES // (1024 * 1024)} МБ — сожмите или "
                         "укоротите его")
    name = str(getattr(upload, "name", "") or "").lower()
    upload.seek(0)
    head = upload.read(12)
    upload.seek(0)
    # Расширение и подпись контейнера: .mp4 с чем угодно внутри раздавался бы
    # с нашего домена как видео.
    if not name.endswith(".mp4") or len(head) < 12 or head[4:8] != b"ftyp":
        raise PanelError("Это не MP4 — загрузите ролик в формате MP4 (H.264)")
    info = _probe(upload.read())
    upload.seek(0)
    if not info.get("width") or not info.get("duration"):
        raise PanelError("Ролик не читается — загрузите MP4 (H.264)")
    seconds = float(info["duration"])
    if not PREVIEW_MIN_SECONDS <= seconds <= PREVIEW_MAX_SECONDS:
        raise PanelError(f"Ролик длится {seconds:g} с — нужно от {PREVIEW_MIN_SECONDS} до "
                         f"{PREVIEW_MAX_SECONDS} секунд")


def upload_preview(preset: CartoonPreset, upload, *, actor, request=None) -> CartoonPreset:
    """Новый ролик превью. Копии прежнего ролика сбрасываются и собираются заново."""
    check_upload(upload)
    name = default_storage.save(f"cartoon/previews/{_stem(preset)}.mp4", upload)
    new = {"preview_video": name, "preview_clip": "", "preview_poster": "", "preview_thumb": ""}
    try:
        with transaction.atomic():
            before = _locked_files(preset.pk)
            if before is None:
                raise PanelError("Сцена не найдена", status=http.HTTP_404_NOT_FOUND)
            CartoonPreset.objects.filter(pk=preset.pk).update(**new)
            log_admin_action(actor, LOG_ACTION, target=preset, before={PRESET_KEY: before},
                             after={PRESET_KEY: {"preview_video": name}}, request=request)
            # Прежний ролик панели и все его копии больше никому не нужны.
            _drop_later(preset.pk, preset.slug, before, new)
    except Exception:
        # Ролик в сцену не встал — загруженный файл ничей.
        _delete([name])
        raise
    request_build(preset.pk, name)
    preset.refresh_from_db()
    return preset


def rebuild_preview(preset: CartoonPreset) -> CartoonPreset:
    """Собрать копии заново — после сбоя сборки или если воркер её не дождался."""
    if not preset.preview_video:
        raise PanelError("Сначала загрузите ролик превью")
    request_build(preset.pk, preset.preview_video.name)
    return preset


def request_build(preset_id, source: str) -> None:
    """Поставить сборку после фиксации: воркер не должен видеть прежний ролик."""
    _set_build(preset_id, {"state": "building", "source": source}, BUILD_TTL)
    transaction.on_commit(partial(enqueue_build, preset_id, source))


def enqueue_build(preset_id, source: str) -> None:
    """Сбой брокера запрос не роняет: ролик уже на месте, а копии соберёт «Пересобрать»."""
    try:
        from . import tasks

        tasks.build_preset_preview.apply_async(args=[preset_id, source])
    except Exception:
        logger.exception("сцены панели: сборка превью сцены %s не поставилась", preset_id)
        _set_build(preset_id, {"state": "done", "source": source,
                               "notes": ["Сборка не запустилась — нажмите «Пересобрать»"]},
                   NOTES_TTL)


def _read(name: str, limit: int | None = None) -> bytes:
    if limit is not None and default_storage.size(name) > limit:
        raise ValueError("too_big")
    with default_storage.open(name, "rb") as fh:
        return fh.read()


def build_preview(preset_id, source: str) -> bool:
    """Лёгкая копия, обложка и миниатюра превью. True — всё собралось.

    Тело задачи build_preset_preview. Любой сбой — заметка панели, а сцена
    остаётся с самим роликом. Пока шла сборка, владелец мог загрузить другой
    ролик — тогда собранное выбрасывается.
    """
    from ai.video_edit import extract_poster

    from .clips import make_clip

    preset = CartoonPreset.objects.filter(pk=preset_id).first()
    if preset is None or not source or preset.preview_video.name != source:
        return False
    stem = _stem(preset)
    notes: list[str] = []
    made: list[str] = []
    update: dict = {}
    try:
        video = _read(source, CLIP_SOURCE_MAX_BYTES)
    except Exception:
        logger.exception("сцены панели: ролик превью сцены %s не читается", preset_id)
        _finish(preset_id, source, ["Ролик превью не читается — загрузите его заново"])
        return False

    def keep(folder: str, ext: str, data: bytes) -> str:
        name = default_storage.save(f"{folder}/{stem}.{ext}", ContentFile(data))
        made.append(name)
        return name

    try:
        clip = make_clip(video)
        if clip:
            update["preview_clip"] = keep("cartoon/previews/clips", "mp4", clip)
        else:
            notes.append("Лёгкая копия не сделалась — в ленте играет сам ролик")
        poster_name = preset.preview_poster.name if preset.preview_poster else ""
        poster = b""
        if poster_name:
            poster = _read(poster_name)
        else:
            poster = extract_poster(video) or b""
            if poster:
                poster_name = update["preview_poster"] = keep("cartoon/posters", "jpg", poster)
            else:
                notes.append("Обложка не сделалась — до загрузки ролика карточка пустая")
        thumb = make_thumb(poster, POSTER_BOX) if poster else None
        if thumb:
            update["preview_thumb"] = keep("cartoon/posters/thumbs", "jpg", thumb)
        elif poster:
            notes.append("Миниатюра обложки не сделалась — в сетке идёт полная обложка")
    except Exception:
        logger.exception("сцены панели: превью сцены %s не собралось", preset_id)
        notes.append("Сборка прервалась — нажмите «Пересобрать»")

    applied = False
    if update:
        with transaction.atomic():
            current = _locked_files(preset_id)
            if current is not None and current["preview_video"] == source:
                CartoonPreset.objects.filter(pk=preset_id).update(**update)
                # Копии прежней сборки того же ролика (второй «Пересобрать») теперь ничьи.
                _drop_later(preset_id, preset.slug, {field: current[field] for field in update},
                            update)
                applied = True
    if update and not applied:
        # Пока собирали, ролик сменили или сцену удалили — собранное ничьё.
        _delete(made)
        return False
    _finish(preset_id, source, notes)
    return not notes


def _finish(preset_id, source: str, notes: list[str]) -> None:
    # Отметку новой загрузки не затираем: её ход важнее итога прежней.
    current = _build_infos([preset_id]).get(preset_id) or {}
    if current.get("source") not in (None, source):
        return
    _set_build(preset_id, {"state": "done", "source": source, "notes": notes}, NOTES_TTL)


# ---------------------------------------------------------------- из «Работ»

def _library_hero(hero) -> bool:
    return bool(hero is not None and hero.user_id is None and hero.is_public)


def frame_sources(scenes) -> dict:
    """Чем рисовались кадры своих сцен: {сцена: [meta списаний за кадр]}.

    Сама сцена не хранит, с чем рисовался её кадр. Это видно только по
    списанию за кадр (render_scene, SceneFrameView): там записано, был ли
    кадр «с оглядкой» на прошлую сцену (linked) и каким героем он нарисован.
    Списание и кадр сохраняются вместе, поэтому каждая версия кадра там есть.
    """
    custom = [s for s in scenes if s.custom_text]
    if not custom:
        return {}
    from plans.models import TokenTransaction

    rows = (TokenTransaction.objects
            .filter(user_id__in={s.project.user_id for s in custom}, reason="cartoon_keyframe",
                    meta__scene__in=[s.pk for s in custom])
            .values_list("meta", flat=True))
    out: dict = {}
    for meta in rows:
        if isinstance(meta, dict) and isinstance(meta.get("scene"), int):
            out.setdefault(meta["scene"], []).append(meta)
    return out


def publish_block(scene: CartoonScene, frames: list | None) -> str:
    """Почему свою сцену нельзя сделать сценой библиотеки. Пусто — можно.

    Превью видят все посетители, поэтому пускаем только то, во что не могло
    попасть ничего личного: кадр нарисован моделью по тексту с героем
    библиотеки, без опоры на прошлую сцену человека (там могут быть его герои,
    вплоть до загруженных фото), и в ролике не звучат его слова.
    """
    if not scene.custom_text:
        return "Это сцена из библиотеки — она там уже есть"
    hero = scene.character or scene.project.character
    if not _library_hero(hero):
        return "Снята своим персонажем пользователя — на кадре может быть его фото"
    if (scene.dialogue or "").strip():
        return "В ролике звучит реплика пользователя — его слова попали бы в библиотеку"
    # Промпт съёмки у готовой сцены стирает только правка реплики (SceneDetailView):
    # пустое поле реплики ещё не значит, что ролик снят без слов.
    if not (scene.video_prompt or "").strip():
        return ("Реплику сцены меняли после съёмки — в ролике может звучать прежняя; "
                "публиковать можно только переснятую сцену")
    if not scene.keyframe or not scene.video:
        return "У сцены нет кадра или ролика"
    if not (scene.custom_prompt or "").strip():
        return "Описание сцены ещё не превратилось в промпт"
    if not frames:
        return "Не видно, из чего нарисован кадр сцены, — публиковать нельзя"
    if any(meta.get("linked") for meta in frames):
        return ("Кадр нарисован с опорой на прошлую сцену пользователя — в нём может "
                "оказаться его герой или фото")
    if not all(meta.get("custom") for meta in frames):
        return "Не видно, из чего нарисован кадр сцены, — публиковать нельзя"
    heroes = {meta.get("character") for meta in frames}
    library = set(CartoonCharacter.objects.filter(
        pk__in=[pk for pk in heroes if isinstance(pk, int)], user__isnull=True, is_public=True)
        .values_list("pk", flat=True))
    if heroes - library:
        return "Кадр рисовался со своим персонажем пользователя — на нём может быть его фото"
    return ""


def library_copies(scene_ids) -> dict:
    """{своя сцена: сцена библиотеки, сделанная из неё и ещё не удалённая}.

    Ищем по журналу (from_scene), а не по промптам: владелец правит промпты
    новой сцены, и повторный клик иначе сделал бы вторую копию.
    """
    from audit.models import AdminActionLog

    ids = [pk for pk in scene_ids if isinstance(pk, int)]
    if not ids:
        return {}
    rows = (AdminActionLog.objects
            .filter(target_type="cartoon.cartoonpreset",
                    **{f"after__{PRESET_KEY}__from_scene__in": ids})
            .order_by("-id").values_list("after", "target_id"))
    pairs = []
    for after, target in rows:
        source = after.get(PRESET_KEY) if isinstance(after, dict) else None
        scene = source.get("from_scene") if isinstance(source, dict) else None
        if isinstance(scene, int) and str(target).isdigit():
            pairs.append((scene, int(target)))
    alive = set(_presets().filter(pk__in={pk for _scene, pk in pairs}).values_list("pk", flat=True))
    out: dict = {}
    for scene, pk in pairs:
        # Свежие записи первыми: копию удалили и сделали заново — берём новую.
        if pk in alive:
            out.setdefault(scene, pk)
    return out


def _copy(name: str, folder: str, stem: str) -> str:
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else "bin"
    with default_storage.open(name, "rb") as fh:
        return default_storage.save(f"{folder}/{stem}.{ext}", ContentFile(fh.read()))


def publish_from_scene(scene_id, *, actor, request=None) -> tuple[CartoonPreset, bool]:
    """Своя сцена пользователя → новая сцена библиотеки, снятая с публикации.

    Промпты уже английские (services.form_custom_scene), модели и стиль — те,
    на которых сцена снята. Ролик и кадр копируются к превью библиотеки: файлы
    сцены остаются её автору и уйдут вместе с его мультфильмом. Повторный клик
    отдаёт уже созданную сцену.
    """
    scene = (CartoonScene.objects
             .select_related("project__user", "project__character", "character", "preset")
             .filter(pk=scene_id, status=CartoonScene.STATUS_READY).exclude(video="").first())
    if scene is None:
        raise PanelError("Сцена не найдена", status=http.HTTP_404_NOT_FOUND)
    block = publish_block(scene, frame_sources([scene]).get(scene.pk))
    if block:
        raise PanelError(block)
    hero = scene.character or scene.project.character
    base = scene.preset
    with transaction.atomic():
        # Двойной клик: второй запрос ждёт первого и находит его сцену.
        CartoonScene.objects.select_for_update().filter(pk=scene.pk).values_list("pk").first()
        copy = library_copies([scene.pk]).get(scene.pk)
        existing = scenes_qs().filter(pk=copy).first() if copy else None
        if existing is None:
            # Сцена с теми же промптами уже есть — вторая такая библиотеке ни к чему.
            existing = scenes_qs().filter(scene_prompt=scene.custom_prompt,
                                          motion_prompt=scene.custom_motion).first()
        if existing is not None:
            return existing, False
        # Код и имена файлов нейтральные: название своей сцены пишет человек, и
        # в нём может оказаться имя ребёнка.
        slug = _free_slug(CartoonPreset, "", "scene")
        stem = f"{slug}-{uuid.uuid4().hex[:8]}"
        made: list[str] = []
        try:
            made.append(_copy(scene.video, "cartoon/previews", stem))
            made.append(_copy(scene.keyframe, "cartoon/posters", stem))
        except Exception:
            logger.exception("сцены панели: файлы сцены %s не скопировались", scene.pk)
            _delete(made)
            raise PanelError("Файлы сцены не читаются — опубликовать не получилось")
        video, poster = made
        title = re.sub(r"\s+", " ", scene.custom_title or "").strip()[:TITLE_MAX] or "Новая сцена"
        try:
            preset = CartoonPreset.objects.create(
                slug=slug, title=title, scene_prompt=scene.custom_prompt,
                motion_prompt=scene.custom_motion, style_prompt=base.style_prompt,
                image_model=base.image_model, video_model=base.video_model,
                duration=base.duration or DURATION_DEFAULT,
                aspect_ratio=scene.project.aspect_ratio or "16:9", resolution=base.resolution,
                audience=hero.audience if hero.audience in AUDIENCE_KEYS else "adults",
                sort_order=_next_sort(_presets().filter(category__isnull=True)),
                is_active=False, preview_video=video, preview_poster=poster)
            # from_scene — по нему повторный клик находит эту сцену (library_copies).
            log_admin_action(actor, LOG_ACTION, target=preset, before={PRESET_KEY: None},
                             after={PRESET_KEY: {**_snapshot(preset, PRESET_LOG_FIELDS),
                                                 "from_scene": scene.pk}},
                             request=request)
        except Exception:
            # Строки нет — копии ничьи.
            _delete(made)
            raise
        request_build(preset.pk, video)
    return scenes_qs().get(pk=preset.pk), True


# ---------------------------------------------------------------- seed_presets

def people_edited(model) -> set:
    """pk строк, которые правил человек: в панели (журнал действий) или в Django-админке.

    seed_presets их не трогает: иначе повторный прогон команды откатил бы
    правки владельца к тексту из кода и спрятал бы его разделы.
    """
    from django.contrib.admin.models import LogEntry
    from django.contrib.contenttypes.models import ContentType

    from audit.models import AdminActionLog

    label = f"{model._meta.app_label}.{model._meta.model_name}"
    raw = set(AdminActionLog.objects.filter(target_type=label).values_list("target_id", flat=True))
    raw |= set(LogEntry.objects.filter(content_type=ContentType.objects.get_for_model(model))
               .values_list("object_id", flat=True))
    return {int(value) for value in raw if str(value).isdigit()}


def deleted_preset_slugs() -> set:
    """Коды сцен, удалённых в панели: seed_presets не должен их вернуть."""
    from audit.models import AdminActionLog

    out = set()
    rows = AdminActionLog.objects.filter(target_type="cartoon.cartoonpreset").values_list(
        "before", "after")
    for before, after in rows:
        if not (isinstance(after, dict) and PRESET_KEY in after and after[PRESET_KEY] is None):
            continue
        snapshot = before.get(PRESET_KEY) if isinstance(before, dict) else None
        if isinstance(snapshot, dict) and snapshot.get("slug"):
            out.add(str(snapshot["slug"]))
    return out
