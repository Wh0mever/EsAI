"""Сборка сцены мультфильма: персонаж → кадр → видео, и склейка в ролик.

Порядок шагов — не прихоть, а способ удержать одного и того же героя во всех
сценах (главное требование клиента). Замер 25.08.2026:

  * если просто дать видео-модели текстовый промпт, она рисует персонажа
    заново в каждой сцене — получается нарезка из разных мультиков;
  * если сначала сделать КАДР сцены моделью с референсом (Nano Banana), герой
    переносится почти без изменений — та же морда, тот же костюм. Этот кадр и
    уходит в видео как first_frame, поэтому ролик стартует с нужного героя.

Отсюда два шага на сцену: кадр (секунды) и видео (минуты). Оба идут в Celery,
чтобы не держать веб-запрос.

Списание — строго по факту. Кадр и видео оплачиваются каждый в свой момент
успеха; если видео не получилось, деньги за кадр не возвращаются (он сделан и
остаётся у пользователя), а за видео не берутся вовсе.
"""
from __future__ import annotations

import base64
import logging
import uuid

import requests
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

from ai.handlers import _openrouter_config, _video_model_params
from plans.wallet import charge_tokens

logger = logging.getLogger(__name__)

# Кадр рисуется секунды, видео — минуты. Потолки с запасом, но не бесконечные:
# зависший запрос не должен занимать воркер навсегда.
IMAGE_TIMEOUT = (10, 180)
VIDEO_SUBMIT_TIMEOUT = (10, 60)
VIDEO_POLL_TIMEOUT = (10, 30)
VIDEO_POLL_LIMIT = 120  # попыток по 5 с ≈ 10 минут


def _site_url(path: str) -> str:
    """Абсолютная ссылка на наш медиафайл — моделям нужен публичный URL."""
    from django.conf import settings

    base = (getattr(settings, "SITE_BASE_URL", "") or "https://esai.kg").rstrip("/")
    return path if path.startswith("http") else base + path


def _save_bytes(raw: bytes, folder: str, ext: str) -> str:
    return default_storage.save(f"{folder}/{uuid.uuid4().hex}.{ext}", ContentFile(raw))


def build_scene_prompt(preset, character) -> str:
    """Склеить промпт сцены: описание героя + что происходит + стиль.

    Слово «character» в промпте пресета заменяется описанием конкретного
    персонажа — так один пресет работает с любым героем.
    """
    who = (getattr(character, "description", "") or "the main character").strip()
    scene = (preset.scene_prompt or "").strip()
    if "character" in scene.lower():
        # Заменяем аккуратно, сохраняя остальной текст пресета.
        import re

        scene = re.sub(r"\bthe character\b|\bcharacter\b", who, scene, flags=re.IGNORECASE)
    else:
        scene = f"{who}. {scene}"
    parts = [scene, (preset.style_prompt or "").strip(),
             "Keep the character identical to the reference image."]
    return " ".join(p for p in parts if p)


def generate_keyframe(preset, character) -> str:
    """Кадр сцены с нужным персонажем. Возвращает путь в хранилище.

    Референсом идёт изображение персонажа — именно оно удерживает героя
    одинаковым от сцены к сцене.
    """
    cfg = _openrouter_config()
    body = {
        "model": preset.image_model.openrouter_id,
        "prompt": build_scene_prompt(preset, character),
        "aspect_ratio": preset.aspect_ratio or "16:9",
    }
    ref = getattr(character, "image", None)
    if ref:
        body["input_references"] = [
            {"type": "image_url", "image_url": {"url": _site_url(ref.url)}}
        ]

    r = requests.post(
        f"{cfg['base_url'].rstrip('/')}/images",
        json=body,
        headers={"Authorization": f"Bearer {cfg['api_key']}", "Content-Type": "application/json"},
        timeout=IMAGE_TIMEOUT,
    )
    if not (200 <= r.status_code < 300):
        raise RuntimeError(f"keyframe http {r.status_code}: {r.text[:200]}")
    item = ((r.json() or {}).get("data") or [{}])[0]
    b64 = item.get("b64_json") or ""
    if not b64:
        raise RuntimeError("keyframe: в ответе нет изображения")
    ext = "png" if "png" in (item.get("media_type") or "") else "jpg"
    return _save_bytes(base64.b64decode(b64), "cartoon/keyframes", ext)


def generate_scene_video(preset, keyframe_path: str) -> str:
    """Оживить кадр. Возвращает путь к mp4 в хранилище.

    Кадр уходит как first_frame — ролик начинается ровно с того, что человек
    уже увидел, поэтому персонаж и композиция не «прыгают».
    """
    cfg = _openrouter_config()
    model_id = preset.video_model.openrouter_id
    params = _video_model_params(model_id, cfg, int(preset.duration or 5),
                                 preset.resolution or "720p")

    body = {
        "model": model_id,
        "prompt": (preset.motion_prompt or preset.scene_prompt or "").strip(),
        "duration": params["duration"],
        "resolution": params["resolution"],
        "frame_images": [{
            "type": "image_url",
            "image_url": {"url": _site_url(default_storage.url(keyframe_path))},
            "frame_type": "first_frame",
        }],
    }
    if preset.aspect_ratio:
        body["aspect_ratio"] = preset.aspect_ratio

    headers = {"Authorization": f"Bearer {cfg['api_key']}"}
    r = requests.post(f"{cfg['base_url'].rstrip('/')}/videos", json=body,
                      headers=headers, timeout=VIDEO_SUBMIT_TIMEOUT)
    if not (200 <= r.status_code < 300):
        raise RuntimeError(f"video submit http {r.status_code}: {r.text[:200]}")
    polling_url = ((r.json() or {}).get("polling_url") or "").strip()
    if not polling_url:
        raise RuntimeError("video submit: не пришёл polling_url")

    import time

    poll: dict = {}
    for _ in range(VIDEO_POLL_LIMIT):
        time.sleep(5)
        try:
            p = requests.get(polling_url, headers=headers, timeout=VIDEO_POLL_TIMEOUT)
            data = p.json() or {}
            if isinstance(data, dict):
                poll = data
        except Exception:
            # Разрыв на одной итерации — не повод бросать всё, ждём следующую.
            continue
        st = str(poll.get("status") or "").lower()
        if st == "completed":
            break
        if st in ("failed", "error", "canceled"):
            raise RuntimeError(f"провайдер вернул {st}")
    else:
        raise RuntimeError("не дождались готовности видео")

    # Ссылка лежит в unsigned_urls и требует Bearer — без заголовка отдаёт 401.
    urls = poll.get("unsigned_urls") or []
    if not urls:
        raise RuntimeError("видео готово, но ссылки на файл нет")
    blob = requests.get(str(urls[0]), headers=headers, timeout=(10, 300))
    if not (200 <= blob.status_code < 300):
        raise RuntimeError(f"скачивание видео: http {blob.status_code}")
    return _save_bytes(blob.content, "cartoon/scenes", "mp4")


def assemble_project(project) -> str:
    """Склеить сцены проекта по порядку в один ролик. Путь в хранилище.

    Используем тот же concat_videos, что и «Продлить» в чате: он
    перекодирует, поэтому сцены с разными параметрами потока склеиваются без
    битого результата.
    """
    from ai.video_edit import concat_videos

    parts = []
    for scene in project.scenes.filter(status="ready").exclude(video="").order_by("order"):
        try:
            with default_storage.open(scene.video, "rb") as fh:
                parts.append(fh.read())
        except Exception:
            logger.warning("склейка: сцена %s не читается, пропускаю", scene.pk)
    if not parts:
        raise RuntimeError("нет готовых сцен для склейки")
    joined = parts[0] if len(parts) == 1 else concat_videos(parts)
    if not joined:
        raise RuntimeError("склейка не удалась")

    # Заставка EsAI в конце. Скачанный mp4 расходится дальше уже без нашей
    # страницы, и то, что впечатано в кадр, — единственное, что переживает
    # перезалив в соцсети. Осечка заставки не должна стоить оплаченного ролика,
    # поэтому append_outro при любой ошибке отдаёт исходник.
    from .outro import append_outro

    return _save_bytes(append_outro(joined), "cartoon/movies", "mp4")


def charge(user, amount: int, reason: str, meta: dict | None = None) -> None:
    """Списать кредиты. Ноль и меньше — молча ничего не делаем."""
    if amount and amount > 0:
        charge_tokens(user, int(amount), reason, meta=meta or {})


# --- своя сцена --------------------------------------------------------------

CUSTOM_PRESET_SLUG = "custom-text-scene"
CUSTOM_TEXT_MIN = 3
CUSTOM_TEXT_MAX = 300


class CustomSceneRejected(Exception):
    """Описание не годится для сцены (недопустимое содержание). Текст — для человека."""


def custom_base_preset():
    """Служебный пресет своих сцен: модели, стиль и цена — как у библиотеки.

    Заводится сам при первой своей сцене по образцу первой готовой сцены
    библиотеки. В витрину не попадает: у него нет превью, а витрина показывает
    только сцены с превью. Модели и стиль потом правятся в админке, как у
    любого пресета.
    """
    from .models import CartoonPreset

    base = CartoonPreset.objects.filter(slug=CUSTOM_PRESET_SLUG).select_related(
        "image_model", "video_model").first()
    if base:
        return base
    donor = (CartoonPreset.objects.filter(is_active=True).exclude(preview_video="")
             .select_related("image_model", "video_model").order_by("id").first())
    if not donor:
        raise RuntimeError("В библиотеке нет ни одной готовой сцены — своей не на что опереться")
    base, _ = CartoonPreset.objects.get_or_create(slug=CUSTOM_PRESET_SLUG, defaults={
        "title": "Своя сцена", "title_en": "Custom scene", "title_kg": "Өз көрүнүшүм",
        "scene_prompt": "the character", "motion_prompt": "", "style_prompt": donor.style_prompt,
        "image_model": donor.image_model, "video_model": donor.video_model,
        "duration": donor.duration, "aspect_ratio": donor.aspect_ratio,
        "resolution": donor.resolution, "audience": donor.audience,
        "is_active": True, "sort_order": 10000,
    })
    return base


_FORM_SYSTEM = (
    "You turn a short user description of a cartoon scene (any language) into prompts "
    "for an image model (first frame) and an image-to-video model (5 seconds). "
    "Refer to the hero ONLY as 'the character' and never describe their appearance: "
    "it comes from a reference image. "
    "Return ONLY a JSON object with keys: "
    "ok (boolean), reason (string, Russian, only when ok is false), "
    "title (string, at most 40 characters, in the user's language), "
    "scene (1-2 English sentences: setting, what the character is doing at the first moment, "
    "composition, lighting), "
    "motion (1 English sentence: what moves during 5 seconds and how the camera moves). "
    "Set ok=false for sexual content or nudity, graphic violence or gore, hate, self-harm, "
    "real public figures, or anything unsafe involving children."
)


def form_custom_scene(text: str) -> dict:
    """Описание от человека → {title, scene, motion}. Отказ — CustomSceneRejected.

    Дешёвая модель: вызов стоит доли цента и делается один раз на сцену.
    """
    import json as _json
    import re as _re

    from django.conf import settings

    cfg = _openrouter_config()
    body = {
        "model": getattr(settings, "STUDIO_SCENE_MODEL", "google/gemini-2.5-flash"),
        "messages": [{"role": "system", "content": _FORM_SYSTEM},
                     {"role": "user", "content": text.strip()[:CUSTOM_TEXT_MAX]}],
        "temperature": 0.4,
        "max_tokens": 500,
        "response_format": {"type": "json_object"},
    }
    r = requests.post(
        f"{cfg['base_url'].rstrip('/')}/chat/completions", json=body,
        headers={"Authorization": f"Bearer {cfg['api_key']}", "Content-Type": "application/json"},
        timeout=(10, 60))
    if not (200 <= r.status_code < 300):
        raise RuntimeError(f"сцена по описанию: http {r.status_code}: {r.text[:200]}")
    content = (((r.json() or {}).get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    match = _re.search(r"\{.*\}", content, flags=_re.S)
    try:
        data = _json.loads(match.group(0) if match else content)
    except ValueError:
        raise RuntimeError("сцена по описанию: модель ответила не JSON")
    if not data.get("ok", True):
        raise CustomSceneRejected(str(data.get("reason") or "Такую сцену снять нельзя")[:200])
    scene = str(data.get("scene") or "").strip()
    if not scene:
        raise RuntimeError("сцена по описанию: пустой промпт")
    if "character" not in scene.lower():
        scene = f"The character. {scene}"
    return {"title": str(data.get("title") or "").strip()[:80],
            "scene": scene[:1500], "motion": str(data.get("motion") or "").strip()[:800]}


def ensure_custom_prompt(scene) -> None:
    """Сформировать промпт своей сцены, если ещё не сформирован (один раз)."""
    if not scene.custom_text or scene.custom_prompt:
        return
    formed = form_custom_scene(scene.custom_text)
    scene.custom_prompt = formed["scene"]
    scene.custom_motion = formed["motion"]
    if formed["title"]:
        scene.custom_title = formed["title"]
    scene.save(update_fields=["custom_prompt", "custom_motion", "custom_title", "updated_at"])


def preset_for_scene(scene):
    """Пресет, по которому снимается сцена. У своей — служебный с её промптом.

    Копия, а не правка: служебный пресет общий для всех своих сцен.
    """
    import copy

    if not scene.custom_text:
        return scene.preset
    preset = copy.copy(scene.preset)
    preset.scene_prompt = scene.custom_prompt or scene.custom_text
    preset.motion_prompt = scene.custom_motion
    return preset


def draw_custom_keyframe(scene, character, user) -> tuple[str, int]:
    """Кадр своей сцены. Мимо общего запаса: пресет у всех своих сцен один,
    и кадр одного человека показался бы другому."""
    ensure_custom_prompt(scene)
    preset = preset_for_scene(scene)
    path = generate_keyframe(preset, character)
    price = max(1, int(float(preset.image_model.markup_coefficient or 1)))
    charge(user, price, "cartoon_keyframe",
           meta={"scene": scene.pk, "custom": True, "character": character.pk})
    return path, price


def remember_pair_video(scene) -> bool:
    """Положить удачную съёмку в общий запас роликов пар.

    Только библиотечный герой: ролик со своим персонажем пользователя — его
    личное, и другим он не показывается. Лёгкая копия для автозапуска
    делается сразу; если ffmpeg не справился, витрина покажет оригинал.
    Возвращает True, если пара появилась в запасе впервые.
    """
    from django.core.files.base import ContentFile
    from django.core.files.storage import default_storage

    from .clips import make_clip
    from .models import CartoonPairVideo

    character = scene.character or scene.project.character
    if not scene.video or not character or character.user_id is not None:
        return False
    # Своя сцена — не пара «герой + сцена библиотеки»: пресет у всех своих
    # сцен общий, и чужой ролик показался бы под чужим описанием.
    if getattr(scene, "custom_text", ""):
        return False
    if CartoonPairVideo.objects.filter(preset_id=scene.preset_id, character=character).exists():
        return False

    clip_path = ""
    try:
        with default_storage.open(scene.video, "rb") as fh:
            clip = make_clip(fh.read())
        if clip:
            clip_path = default_storage.save(
                f"cartoon/pairs/{scene.preset_id}-{character.pk}.mp4", ContentFile(clip))
    except Exception:
        logger.exception("ролик пары: лёгкая копия не сделалась (сцена %s)", scene.pk)

    _, created = CartoonPairVideo.objects.get_or_create(
        preset_id=scene.preset_id, character=character,
        defaults={"video": scene.video, "clip": clip_path, "source_scene": scene})
    return created


def get_or_create_keyframe(preset, character, user=None):
    """Кадр «герой в сцене»: из общего запаса или нарисовать.

    Возвращает (путь, списано_кредитов). Уже нарисованный кадр отдаётся
    бесплатно — тем же кадром потом снимается и сама сцена, поэтому дважды за
    одно и то же человек не платит.
    """
    from .models import CartoonKeyframe

    existing = CartoonKeyframe.objects.filter(
        preset=preset, character=character).first()
    if existing and existing.image:
        return existing.image, 0

    path = generate_keyframe(preset, character)
    price = max(1, int(float(preset.image_model.markup_coefficient or 1)))
    if user is not None:
        charge(user, price, "cartoon_keyframe",
               meta={"preset": preset.pk, "character": character.pk})
    # get_or_create, а не create: два запроса на одну пару могли прийти разом.
    CartoonKeyframe.objects.get_or_create(
        preset=preset, character=character, defaults={"image": path})
    return path, price
