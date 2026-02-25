from __future__ import annotations

from core.celery import app
from django.db import transaction
from django.contrib.auth import get_user_model
from .models import AiProvider, AiChatSession, AiChatMessage, AiGeneratedImage
from .handlers import _make_openai_client
from plans.models import UserSubscription
from django.core.files.base import ContentFile
import base64
import uuid


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
