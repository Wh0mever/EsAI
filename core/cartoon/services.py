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

    base = (getattr(settings, "SITE_URL", "") or "https://esai.kg").rstrip("/")
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
    if len(parts) == 1:
        return _save_bytes(parts[0], "cartoon/movies", "mp4")
    joined = concat_videos(parts)
    if not joined:
        raise RuntimeError("склейка не удалась")
    return _save_bytes(joined, "cartoon/movies", "mp4")


def charge(user, amount: int, reason: str, meta: dict | None = None) -> None:
    """Списать кредиты. Ноль и меньше — молча ничего не делаем."""
    if amount and amount > 0:
        charge_tokens(user, int(amount), reason, meta=meta or {})
