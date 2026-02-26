from __future__ import annotations

from core.celery import app
from django.db import transaction
from django.contrib.auth import get_user_model
from .models import AiProvider, AiChatSession, AiChatMessage, AiGeneratedImage, AiGeneratedMusic
from .handlers import _make_openai_client
from plans.models import UserSubscription
from django.core.files.base import ContentFile
import base64
import uuid
import requests
import time
from urllib.parse import urlparse


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

    return {
        "session": {"id": session.id, "uid": session.uid, "title": session.title, "provider": provider.slug, "updated_at": str(session.updated_at)},
        "image": {"url": url, "size": size, "id": gen.id, "uniqid": gen.uniqid},
        "message": {"id": getattr(assistant_msg, "id", None)} if assistant_msg else None,
    }


def _extract_task_id(payload: dict | list | str | None) -> str:
    if isinstance(payload, str):
        return payload.strip() if payload.strip() else ""
    if isinstance(payload, list):
        for item in payload:
            tid = _extract_task_id(item)
            if tid:
                return tid
        return ""
    if not isinstance(payload, dict):
        return ""
    for key in ("task_id", "taskId", "id", "job_id", "jobId"):
        value = payload.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    for nested in payload.values():
        tid = _extract_task_id(nested)
        if tid:
            return tid
    return ""


def _collect_audio_urls(payload: dict | list | str | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()

    def push(url: str):
        v = (url or "").strip()
        if not v:
            return
        low_path = (urlparse(v).path or "").lower()
        if any(low_path.endswith(ext) for ext in (".mp3", ".wav", ".ogg", ".m4a", ".aac", ".flac")):
            if v not in seen:
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
            for v in node.values():
                walk(v)

    walk(payload)
    return out


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
    for key in ("status", "state", "task_status"):
        value = payload.get(key)
        if value is not None and str(value).strip():
            return str(value).strip().lower()
    for nested in payload.values():
        s = _extract_status(nested)
        if s:
            return s
    return ""


def _fetch_task_payload(base_url: str, task_id: str, api_key: str) -> dict | None:
    base = (base_url or "https://api.topmediai.com").rstrip("/")
    headers = {"x-api-key": api_key}
    candidates = [
        ("GET", f"{base}/v2/task/{task_id}", None),
        ("GET", f"{base}/v2/task", {"task_id": task_id}),
        ("GET", f"{base}/v2/task", {"id": task_id}),
        ("GET", f"{base}/v2/tasks/{task_id}", None),
        ("GET", f"{base}/v2/music/{task_id}", None),
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
        if isinstance(data, dict):
            return data
    return None


@app.task(name="ai.generate_music")
def generate_music_task(
    *,
    user_id: int,
    prompt: str,
    lyrics: str = "",
    title: str = "",
    is_auto: int = 1,
    model_version: str = "v4.5",
    instrumental: int = 1,
    continue_at: int = 0,
    continue_song_id: str = "",
    provider_slug: str = "topmedia",
    session_id: str | int | None = None,
) -> dict:
    User = get_user_model()

    prompt = (prompt or "").strip()
    if not prompt:
        return {"error": "No prompt provided"}

    try:
        user = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        return {"error": "User not found"}

    try:
        provider = AiProvider.objects.get(slug=(provider_slug or "topmedia").strip(), is_active=True)
    except AiProvider.DoesNotExist:
        return {"error": "TopMedia provider not found or inactive"}
    if not (provider.token or "").strip():
        return {"error": "TopMedia provider token is empty"}

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
            session = AiChatSession.objects.create(
                user=user,
                provider=provider,
                title=(title or prompt[:60] or "Music Chat").strip() or "Music Chat",
                chat_mode="music-chat",
            )

        request_meta = {
            "topmedia": {
                "mode": "submit-v2",
                "is_auto": int(is_auto or 1),
                "model_version": (model_version or "v4.5").strip(),
                "prompt": prompt,
                "lyrics": (lyrics or "").strip(),
                "title": (title or "").strip(),
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
        return {"error": "Лимиты на генерацию музыки исчерпаны. Пополните лимит или обновите тариф."}

    base_url = (provider.base_url or "https://api.topmediai.com").rstrip("/")
    headers = {"x-api-key": provider.token, "Content-Type": "application/json"}
    payload = {
        "is_auto": int(is_auto or 1),
        "model_version": (model_version or "v4.5").strip(),
        "prompt": prompt,
        "lyrics": (lyrics or "").strip(),
        "title": (title or "").strip(),
        "instrumental": int(instrumental or 0),
        "continue_at": int(continue_at or 0),
        "continue_song_id": (continue_song_id or "").strip(),
    }

    try:
        submit = requests.post(f"{base_url}/v2/submit", headers=headers, json=payload, timeout=45)
    except requests.RequestException as exc:
        return {"error": f"TopMedia submit failed: {exc}"}
    if submit.status_code >= 400:
        return {"error": f"TopMedia submit failed ({submit.status_code}): {submit.text[:300]}"}
    try:
        submit_data = submit.json()
    except Exception:
        return {"error": "TopMedia submit returned non-JSON response"}

    task_id = _extract_task_id(submit_data)
    if not task_id:
        immediate_urls = _collect_audio_urls(submit_data)
        if not immediate_urls:
            return {"error": "TopMedia submit did not return task_id"}
        audio_source = immediate_urls[0]
        task_payload = submit_data
    else:
        task_payload = None
        audio_source = ""
        deadline = time.time() + 60 * 5
        while time.time() < deadline:
            polled = _fetch_task_payload(base_url, task_id, provider.token)
            if polled is None:
                time.sleep(2)
                continue
            task_payload = polled
            urls = _collect_audio_urls(polled)
            if urls:
                audio_source = urls[0]
                break

            state = _extract_status(polled)
            if state in {"failed", "error", "cancelled"}:
                return {"error": f"TopMedia task failed (task_id={task_id})", "task_id": task_id}
            time.sleep(2)

        if not audio_source:
            return {"error": f"TopMedia task timeout (task_id={task_id})", "task_id": task_id}

    # Download generated audio and persist in media
    try:
        audio_resp = requests.get(audio_source, timeout=90)
        audio_resp.raise_for_status()
        audio_bytes = audio_resp.content
    except requests.RequestException as exc:
        return {"error": f"Failed to download generated audio: {exc}", "task_id": task_id}

    parsed_path = urlparse(audio_source).path or ""
    name = parsed_path.rsplit("/", 1)[-1] or f"{uuid.uuid4().hex}.mp3"
    if "." not in name:
        name = f"{name}.mp3"

    gen = AiGeneratedMusic(
        user=user,
        session=session,
        provider=provider,
        model_name=(model_version or "v4.5").strip(),
        prompt=prompt,
        lyrics=(lyrics or "").strip(),
        title=(title or "").strip(),
        instrumental=bool(int(instrumental or 0)),
        topmedia_task_id=task_id or "",
        source_url=audio_source,
        meta={"submit": submit_data, "task": task_payload},
    )
    gen.audio.save(name, ContentFile(audio_bytes), save=True)

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
            "instrumental": bool(int(instrumental or 0)),
        },
    )

    if subscription:
        try:
            subscription.consume("music")
        except Exception:
            pass

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
        },
        "message": {"id": getattr(assistant_msg, "id", None), "content": assistant_msg.content},
    }
