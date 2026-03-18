from __future__ import annotations

from core.celery import app
from django.db import transaction
from django.contrib.auth import get_user_model
from .models import AiProvider, AiChatSession, AiChatMessage, AiGeneratedImage, AiGeneratedMusic
from .handlers import _make_openai_client
from plans.models import UserSubscription
from plans.services import get_chat_access_state, consume_bonus_without_subscription
from django.core.files.base import ContentFile
import base64
import uuid
import requests
import time
import logging
import re
from urllib.parse import urlparse
from celery import current_task
from billiard.exceptions import SoftTimeLimitExceeded


logger = logging.getLogger(__name__)
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
TOPMEDIA_API_BASE = "https://api.topmediai.com"


@app.task(name="ai.generate_image")
def generate_image_task(
    *,
    user_id: int,
    prompt: str,
    size: str = "1024x1024",
    model: str = "gpt-image-1",
    provider_slug: str = "dall-e",
    session_id: str | int | None = None,
    attachments: list | None = None,
) -> dict:
    User = get_user_model()

    # Normalize
    prompt = (prompt or "").strip()
    if not prompt:
        return {"error": "No prompt provided"}
    if size not in {"256x256", "512x512", "1024x1024"}:
        size = "1024x1024"
    model_name = (model or "gpt-image-1").strip()
    provider_slug = (provider_slug or AiProvider.NAME_TO_SLUG[AiProvider.NAME_DALLE]).strip()

    try:
        user = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        return {"error": "User not found"}
    access = get_chat_access_state(user, "ru", kind="image")
    if access.get("blocked"):
        return {"error": access.get("error"), "error_code": access.get("error_code"), "grace_until": access.get("grace_until")}

    try:
        provider = AiProvider.objects.get(slug=provider_slug, is_active=True)
    except AiProvider.DoesNotExist:
        return {"error": f"Provider '{provider_slug}' not found or inactive"}
    if not (provider.token or "").strip():
        return {"error": "Image provider is not configured."}

    client = _make_openai_client(provider)

    # Ensure session and persist user message
    with transaction.atomic():
        if session_id:
            ref = str(session_id).strip()
            qs = AiChatSession.objects.filter(user=user, is_active=True).select_for_update()
            if ref.isdigit():
                session = qs.filter(id=int(ref)).first() or qs.filter(uid=ref).first()
            else:
                session = qs.filter(uid=ref).first()
            if not session:
                return {"error": "Session not found"}
        else:
            title = (prompt[:60] or "Image Chat").strip() or "Image Chat"
            session = AiChatSession.objects.create(
                user=user,
                provider=provider,
                title=title,
                chat_mode='image-chat',
            )

        AiChatMessage.objects.create(
            session=session,
            role="user",
            content=prompt,
            attachments=attachments if isinstance(attachments, list) else None,
        )

    # Usage limits
    subscription = (
        UserSubscription.objects
        .filter(user=user, status="active")
        .select_related("plan")
        .order_by("-start_date")
        .first()
    )
    if subscription and not subscription.can_consume("image"):
        return {"error": "Лимиты на генерацию изображений исчерпаны. Пополните лимит или обновите тариф."}

    # Generate
    try:
        result = client.images.generate(model=model_name, prompt=prompt, size=size, n=1)
    except Exception as e:
        msg = str(e).lower()
        if "timeout" in msg or "timed out" in msg or "read timeout" in msg:
            return {"error": "Image generation timed out. Please try again."}
        if "api key" in msg or "authentication" in msg:
            return {"error": "Image provider authentication failed."}
        return {"error": "Failed to generate image."}

    data0 = result.data[0] if getattr(result, "data", None) else None
    if not data0:
        return {"error": "No image data received"}
    b64 = getattr(data0, "b64_json", None) or getattr(data0, "b64", None)
    if not b64:
        return {"error": "No base64 image in response"}

    try:
        raw = base64.b64decode(b64)
    except Exception:
        return {"error": "Failed to decode image data"}

    gen = AiGeneratedImage(
        user=user,
        session=session,
        provider=provider,
        model_name=model_name,
        prompt=prompt,
        size=size,
    )
    filename = f"{uuid.uuid4().hex}.png"
    gen.image.save(filename, ContentFile(raw), save=True)

    # Assistant message with URL
    try:
        url = gen.image.url
        assistant_msg = AiChatMessage.objects.create(
            session=session,
            role="assistant",
            content=url,
            attachments=[{"type": "image", "url": url}],
            meta={"model": model_name, "size": size},
        )
    except Exception:
        assistant_msg = None
        url = None

    if subscription:
        try:
            subscription.consume("image")
        except Exception:
            pass
    else:
        consume_bonus_without_subscription(user, "image")

    return {
        "session": {"id": session.id, "uid": session.uid, "title": session.title, "provider": provider.slug, "updated_at": str(session.updated_at)},
        "image": {"url": url, "size": size, "id": gen.id, "uniqid": gen.uniqid},
        "message": {"id": getattr(assistant_msg, "id", None)} if assistant_msg else None,
    }


def _extract_task_id(payload: dict | list | str | None) -> str:
    if isinstance(payload, str):
        v = payload.strip()
        return v
    if isinstance(payload, list):
        for item in payload:
            tid = _extract_task_id(item)
            if tid:
                return tid
        return ""
    if not isinstance(payload, dict):
        return ""
    for key in ("task_id", "taskId", "id", "job_id", "jobId", "song_id", "songId"):
        value = payload.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    for nested in payload.values():
        if isinstance(nested, (dict, list)):
            tid = _extract_task_id(nested)
            if tid:
                return tid
    return ""


def _extract_task_ids(payload: dict | list | str | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()

    def push(v: str):
        s = (v or "").strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)

    def walk(node):
        if isinstance(node, str):
            if node.strip():
                push(node.strip())
            return
        if isinstance(node, list):
            for it in node:
                walk(it)
            return
        if isinstance(node, dict):
            ids = node.get("ids")
            if isinstance(ids, list):
                for x in ids:
                    if isinstance(x, (str, int)):
                        push(str(x))
            for key in ("task_id", "taskId", "id", "job_id", "jobId", "song_id", "songId"):
                value = node.get(key)
                if value is not None and str(value).strip():
                    push(str(value).strip())
            for nested in node.values():
                if isinstance(nested, (dict, list)):
                    walk(nested)

    walk(payload)
    return out


def _collect_audio_urls(payload: dict | list | str | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()

    def push(url: str, hint_key: str | None = None):
        v = (url or "").strip()
        if not v:
            return
        low_path = (urlparse(v).path or "").lower()
        key = (hint_key or "").lower()
        looks_like_audio_endpoint = (
            "/api/audio/" in low_path
            or "audio" in key
            or "music_url" in key
            or "source_url" in key
            or "download_url" in key
            or "song_url" in key
        )
        looks_like_audio_file = any(low_path.endswith(ext) for ext in (".mp3", ".wav", ".ogg", ".m4a", ".aac", ".flac"))
        if (looks_like_audio_endpoint or looks_like_audio_file) and v not in seen:
            seen.add(v)
            out.append(v)

    def walk(node):
        if isinstance(node, str):
            push(node)
            return
        if isinstance(node, list):
            for it in node:
                walk(it)
            return
        if isinstance(node, dict):
            for k, v in node.items():
                if isinstance(v, str):
                    push(v, hint_key=str(k))
                else:
                    walk(v)

    walk(payload)
    return out


def _download_audio_if_ready(audio_url: str, timeout: tuple[int, int] = (10, 45)) -> tuple[bytes | None, str | None]:
    try:
        resp = requests.get(audio_url, timeout=timeout)
    except requests.RequestException as exc:
        return None, f"download request failed: {exc}"

    if resp.status_code in {202, 404, 425, 429}:
        return None, None
    if resp.status_code >= 400:
        return None, f"download failed ({resp.status_code}): {(resp.text or '')[:200]}"

    ctype = (resp.headers.get("Content-Type") or "").lower()
    if "audio" not in ctype:
        body = (resp.text or "")[:200].lower()
        if "running" in body or "processing" in body or "pending" in body:
            return None, None
        if "application/json" in ctype and ("status" in body or "message" in body):
            return None, None
        if not resp.content:
            return None, None
    if not resp.content:
        return None, None
    return resp.content, None


def _extract_status(payload: dict | list | str | None) -> str:
    if isinstance(payload, str):
        return payload.strip().lower()
    if isinstance(payload, list):
        for item in payload:
            s = _extract_status(item)
            if s:
                return s
        return ""
    if not isinstance(payload, dict):
        return ""
    # Prefer nested payload status over envelope status=200.
    nested_data = payload.get("data")
    if isinstance(nested_data, (dict, list)):
        s = _extract_status(nested_data)
        if s:
            return s
    if payload.get("fail_code") or payload.get("fail_reason"):
        return "failed"
    for key in ("status", "state", "task_status"):
        value = payload.get(key)
        if value is None:
            continue
        raw = str(value).strip().lower()
        if not raw:
            continue
        # Ignore envelope HTTP-like status.
        if key == "status" and raw in {"200"}:
            continue
        # Normalize common numeric task states.
        if raw == "1":
            return "success"
        if raw in {"0", "2", "3", "4"}:
            return "processing"
        return raw
    for nested in payload.values():
        s = _extract_status(nested)
        if s:
            return s
    return ""


def _extract_music_fields(payload: dict | list | str | None) -> dict:
    if isinstance(payload, list):
        if payload and isinstance(payload[0], dict):
            return _extract_music_fields(payload[0])
        return {"audio_url": "", "cover_url": "", "format": "", "duration": None, "song_id": "", "title": "", "model_version": ""}
    if isinstance(payload, dict):
        src = payload
        data = payload.get("data")
        if isinstance(data, list) and data and isinstance(data[0], dict):
            src = data[0]
        audio_candidate = (
            src.get("audio_url")
            or src.get("audio")
            or src.get("music_url")
            or src.get("source_url")
            or src.get("download_url")
            or src.get("url")
            or ""
        )
        return {
            "audio_url": audio_candidate.strip() if isinstance(audio_candidate, str) else "",
            "cover_url": (
                src.get("cover_url")
                or src.get("image")
                or src.get("cover")
                or ""
            ).strip() if isinstance(
                src.get("cover_url")
                or src.get("image")
                or src.get("cover")
                or "",
                str
            ) else "",
            "format": (src.get("format") or "").strip() if isinstance(src.get("format"), str) else "",
            "duration": src.get("duration") if isinstance(src.get("duration"), (int, float)) else None,
            "song_id": (src.get("song_id") or src.get("songId") or "").strip() if isinstance(src.get("song_id") or src.get("songId") or "", str) else "",
            "title": (src.get("title") or "").strip() if isinstance(src.get("title"), str) else "",
            "model_version": (src.get("model_version") or src.get("mv") or "").strip() if isinstance(src.get("model_version") or src.get("mv") or "", str) else "",
        }
    return {"audio_url": "", "cover_url": "", "format": "", "duration": None, "song_id": "", "title": "", "model_version": ""}


def _fetch_task_payload(base_url: str, task_id: str | list[str], api_key: str) -> dict | list | None:
    base = _normalize_topmedia_base_url(base_url)
    headers = {"x-api-key": api_key}
    ids_list = task_id if isinstance(task_id, list) else [task_id]
    ids_list = [str(x).strip() for x in ids_list if str(x).strip()]
    candidates = [
        ("GET", f"{base}/v3/music/tasks", {"ids": ids_list}),
        ("GET", f"{base}/v3/music/tasks", {"ids": ",".join(ids_list)}),
        ("GET", f"{base}/v3/music/tasks", {"task_id": ids_list[0] if ids_list else ""}),
        ("GET", f"{base}/v3/music/tasks", {"id": ids_list[0] if ids_list else ""}),
        ("GET", f"{base}/v3/music/tasks", {"song_id": ids_list[0] if ids_list else ""}),
        ("GET", f"{base}/v3/task/{ids_list[0] if ids_list else ''}", None),
        ("GET", f"{base}/v3/task", {"task_id": ids_list[0] if ids_list else ""}),
        ("GET", f"{base}/v3/task", {"id": ids_list[0] if ids_list else ""}),
        ("GET", f"{base}/v3/tasks/{ids_list[0] if ids_list else ''}", None),
        ("GET", f"{base}/v3/music/{ids_list[0] if ids_list else ''}", None),
        ("GET", f"{base}/v2/task/{ids_list[0] if ids_list else ''}", None),
        ("GET", f"{base}/v2/task", {"task_id": ids_list[0] if ids_list else ""}),
        ("GET", f"{base}/v2/task", {"id": ids_list[0] if ids_list else ""}),
        ("GET", f"{base}/v2/tasks/{ids_list[0] if ids_list else ''}", None),
        ("GET", f"{base}/v2/music/{ids_list[0] if ids_list else ''}", None),
    ]
    for method, url, params in candidates:
        try:
            resp = requests.request(method, url, headers=headers, params=params, timeout=30)
        except requests.RequestException:
            continue
        if resp.status_code == 404:
            continue
        if resp.status_code >= 400:
            continue
        try:
            data = resp.json()
        except Exception:
            continue
        if isinstance(data, (dict, list)):
            return data
    return None


def _normalize_topmedia_base_url(raw_url: str | None = None) -> str:
    # Runtime base URL is fixed in code; DB base_url is ignored by design.
    base = TOPMEDIA_API_BASE.strip().rstrip("/")
    if base.lower().endswith("/v1") or base.lower().endswith("/v2") or base.lower().endswith("/v3"):
        base = base[:-3].rstrip("/")
    return base or TOPMEDIA_API_BASE


def _submit_topmedia(base_url: str, headers: dict, payload: dict) -> tuple[dict | None, str, str | None]:
    base = _normalize_topmedia_base_url(base_url)
    attempts = [
        ("v3_music_generate", f"{base}/v3/music/generate"),
        ("v2_submit", f"{base}/v2/submit"),
        ("v1_music", f"{base}/v1/music"),
    ]
    last_error: str | None = None
    for label, url in attempts:
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=(10, 120))
        except requests.RequestException as exc:
            # Network/read timeout on primary endpoint should be surfaced directly.
            # Falling back to another path in this case only doubles wait time.
            return None, label, f"{label} request failed: {exc}"
        if resp.status_code in {404, 405}:
            last_error = f"{label} returned {resp.status_code}"
            continue
        if resp.status_code >= 400:
            return None, label, f"{label} failed ({resp.status_code}): {resp.text[:300]}"
        try:
            data = resp.json()
            return data, label, None
        except Exception:
            return None, label, f"{label} returned non-JSON response"
    return None, "", last_error or "all submit endpoints failed"


@app.task(name="ai.generate_music", soft_time_limit=60 * 13, time_limit=60 * 14)
def generate_music_task(
    *,
    user_id: int,
    prompt: str,
    lyrics: str = "",
    title: str = "",
    language: str = "",
    genre: str = "",
    gender: str = "",
    is_auto: int = 1,
    model_version: str = "v4.5",
    instrumental: int = 1,
    continue_at: int = 0,
    continue_song_id: str = "",
    provider_slug: str = "topmedia",
    session_id: str | int | None = None,
) -> dict:
    User = get_user_model()
    celery_task_id = getattr(getattr(current_task, "request", None), "id", None)

    def _fail(message: str, **extra) -> dict:
        payload = {"error": message}
        payload.update(extra)
        logger.error(
            "generate_music failed task_id=%s user_id=%s provider=%s details=%s",
            celery_task_id,
            user_id,
            provider_slug,
            payload,
        )
        return payload

    prompt = (prompt or "").strip()
    if not prompt:
        return _fail("No prompt provided")

    try:
        user = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        return _fail("User not found")
    access = get_chat_access_state(user, language or "ru", kind="music")
    if access.get("blocked"):
        return _fail(access.get("error") or "Chat is unavailable", error_code=access.get("error_code"), grace_until=access.get("grace_until"))

    try:
        provider = AiProvider.objects.get(slug=(provider_slug or "topmedia").strip(), is_active=True)
    except AiProvider.DoesNotExist:
        return _fail("TopMedia provider not found or inactive")
    if not (provider.token or "").strip():
        return _fail("TopMedia provider token is empty")

    # Ensure session and persist user message
    with transaction.atomic():
        if session_id:
            ref = str(session_id).strip()
            qs = AiChatSession.objects.filter(user=user, is_active=True).select_for_update()
            if ref.isdigit():
                session = qs.filter(id=int(ref)).first() or qs.filter(uid=ref).first()
            else:
                session = qs.filter(uid=ref).first()
            if not session:
                return _fail("Session not found")
        else:
            session = AiChatSession.objects.create(
                user=user,
                provider=provider,
                # Chat title should reflect user's request text, while track title is stored separately.
                title=(prompt[:60] or "Music Chat").strip() or "Music Chat",
                chat_mode="music-chat",
            )

        request_meta = {
            "topmedia": {
                "mode": "submit-v3-generate",
                "is_auto": int(is_auto or 1),
                "model_version": (model_version or "v4.5").strip(),
                "prompt": prompt,
                "lyrics": (lyrics or "").strip(),
                "title": (title or "").strip(),
                "language": (language or "").strip(),
                "genre": (genre or "").strip(),
                "gender": (gender or "").strip(),
                "instrumental": int(instrumental or 0),
                "continue_at": int(continue_at or 0),
                "continue_song_id": (continue_song_id or "").strip(),
            }
        }
        AiChatMessage.objects.create(
            session=session,
            role="user",
            content=prompt,
            attachments=None,
            meta=request_meta,
        )

    subscription = (
        UserSubscription.objects
        .filter(user=user, status="active")
        .select_related("plan")
        .order_by("-start_date")
        .first()
    )
    if subscription and not subscription.can_consume("music"):
        return _fail("Лимиты на генерацию музыки исчерпаны. Пополните лимит или обновите тариф.")

    base_url = _normalize_topmedia_base_url()
    headers = {"x-api-key": provider.token, "Content-Type": "application/json"}
    lang_code = (language or "").strip().lower()
    lang_map = {"ru": "Russian", "en": "English", "kg": "Kyrgyz", "ky": "Kyrgyz"}
    lang_name = lang_map.get(lang_code, "")
    style_parts = [prompt.strip()]
    if (genre or "").strip():
        style_parts.append(f"Genre: {(genre or '').strip()}")
    if lang_name and not bool(int(instrumental or 0)):
        style_parts.append(
            f"CRITICAL: Write the lyrics only in {lang_name}. "
            f"Do not use any other language, do not mix languages, and do not transliterate."
        )
        style_parts.append(f"Lyrics language: {lang_name}")
    style = ". ".join([p for p in style_parts if p]).strip()
    payload = {
        "action": "auto",
        "style": style or prompt,
        "mv": (model_version or "v4.5").strip(),
        "instrumental": int(instrumental or 0),
    }
    if (gender or "").strip() in {"male", "female"} and not bool(int(instrumental or 0)):
        payload["gender"] = (gender or "").strip()

    try:
        submit_data, submit_endpoint, submit_error = _submit_topmedia(base_url, headers, payload)
    except SoftTimeLimitExceeded:
        return _fail("TopMedia task exceeded celery soft time limit", stage="submit")
    if submit_error:
        return _fail(f"TopMedia submit failed: {submit_error}")
    if not submit_data:
        return _fail("TopMedia submit failed: empty response")

    logger.info(
        "generate_music submit_ok task_id=%s user_id=%s endpoint=%s",
        celery_task_id,
        user_id,
        submit_endpoint,
    )
    submit_fields = _extract_music_fields(submit_data)

    task_ids = _extract_task_ids(submit_data)
    task_id = task_ids[0] if task_ids else _extract_task_id(submit_data)
    candidate_audio_urls = _collect_audio_urls(submit_data)
    if not task_id:
        if not candidate_audio_urls:
            return _fail("TopMedia submit did not return task_id", submit_endpoint=submit_endpoint)
        audio_source = candidate_audio_urls[0]
        task_payload = submit_data
    else:
        task_payload = None
        audio_source = ""
        deadline = time.time() + 60 * 10
        try:
            while time.time() < deadline:
                polled = _fetch_task_payload(base_url, task_ids or task_id, provider.token)
                if polled is None:
                    # Even if task-status endpoint is unknown, TopMedia may expose final audio
                    # at submit-time URLs; keep probing them until ready.
                    for probe_url in candidate_audio_urls:
                        audio_bytes, download_err = _download_audio_if_ready(probe_url)
                        if audio_bytes:
                            audio_source = probe_url
                            break
                    if audio_source:
                        break
                    time.sleep(2)
                    continue
                task_payload = polled
                urls = _collect_audio_urls(polled)
                if urls:
                    for u in urls:
                        if u not in candidate_audio_urls:
                            candidate_audio_urls.append(u)
                if urls:
                    for probe_url in candidate_audio_urls:
                        audio_bytes, download_err = _download_audio_if_ready(probe_url)
                        if audio_bytes:
                            audio_source = probe_url
                            break
                    if audio_source:
                        break

                state = _extract_status(polled)
                if state in {"failed", "error", "cancelled", "failure"}:
                    return _fail(f"TopMedia task failed (task_id={task_id})", task_id=task_id, task_payload=polled)
                time.sleep(2)
        except SoftTimeLimitExceeded:
            return _fail("TopMedia task exceeded celery soft time limit", stage="poll", task_id=task_id)

        if not audio_source:
            return _fail(f"TopMedia task timeout (task_id={task_id})", task_id=task_id, submit_endpoint=submit_endpoint)

    # Download generated audio and persist in media
    try:
        deadline = time.time() + 60 * 10
        audio_bytes = None
        download_error = None
        while time.time() < deadline:
            audio_bytes, download_error = _download_audio_if_ready(audio_source, timeout=(10, 60))
            if audio_bytes:
                break
            time.sleep(2)
        if not audio_bytes:
            return _fail("Failed to download generated audio in time", task_id=task_id, audio_source=audio_source, details=download_error)
    except SoftTimeLimitExceeded:
        return _fail("TopMedia task exceeded celery soft time limit", stage="download", task_id=task_id)

    parsed_path = urlparse(audio_source).path or ""
    name = parsed_path.rsplit("/", 1)[-1] or f"{uuid.uuid4().hex}.mp3"
    if "." not in name:
        name = f"{name}.mp3"

    gen = AiGeneratedMusic(
        user=user,
        session=session,
        provider=provider,
        model_name=(submit_fields.get("model_version") or model_version or "v4.5").strip(),
        prompt=prompt,
        lyrics=(lyrics or "").strip(),
        title=(title or submit_fields.get("title") or "Track").strip(),
        instrumental=bool(int(instrumental or 0)),
        topmedia_task_id=(task_id or submit_fields.get("song_id") or "").strip(),
        source_url=audio_source,
        meta={
            "language": lang_code,
            "language_name": lang_name,
            "style_prompt": style,
            "submit_endpoint": submit_endpoint,
            "submit": submit_data,
            "task": task_payload,
            "topmedia": submit_fields,
        },
    )
    try:
        gen.audio.save(name, ContentFile(audio_bytes), save=True)
    except Exception as exc:
        logger.exception(
            "generate_music save_failed task_id=%s user_id=%s topmedia_task_id=%s name=%s",
            celery_task_id,
            user_id,
            task_id,
            name,
        )
        return _fail(f"Failed to save generated audio: {exc}", task_id=task_id)

    final_url = gen.audio.url if gen.audio else gen.source_url
    assistant_msg = AiChatMessage.objects.create(
        session=session,
        role="assistant",
        content=final_url or "",
        attachments=[{"type": "audio", "url": final_url}] if final_url else None,
        meta={
            "provider": "topmedia",
            "model": model_version,
            "task_id": task_id,
            "music": {
                "id": gen.id,
                "uniqid": gen.uniqid,
                "url": final_url,
                "source_url": gen.source_url,
                "task_id": task_id,
                "model_version": gen.model_name,
                "title": gen.title,
                "instrumental": gen.instrumental,
                "language": lang_code,
            },
            "instrumental": bool(int(instrumental or 0)),
        },
    )
    logger.info(
        "generate_music completed task_id=%s user_id=%s topmedia_task_id=%s music_id=%s",
        celery_task_id,
        user_id,
        task_id,
        gen.id,
    )

    if subscription:
        try:
            subscription.consume("music")
        except Exception:
            pass
    else:
        consume_bonus_without_subscription(user, "music")

    return {
        "session": {"id": session.id, "uid": session.uid, "title": session.title, "provider": provider.slug, "updated_at": str(session.updated_at)},
        "music": {
            "id": gen.id,
            "uniqid": gen.uniqid,
            "url": final_url,
            "source_url": gen.source_url,
            "task_id": task_id,
            "model_version": gen.model_name,
            "title": gen.title,
            "instrumental": gen.instrumental,
            "format": submit_fields.get("format") or "mp3",
            "duration": submit_fields.get("duration"),
            "song_id": submit_fields.get("song_id") or task_id,
        },
        "message": {"id": getattr(assistant_msg, "id", None), "content": assistant_msg.content},
    }
