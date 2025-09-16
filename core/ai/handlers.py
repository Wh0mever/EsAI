import json
from typing import Any, Optional, List, Tuple
from django.db import transaction
from openai import OpenAI
from django.core.files.base import ContentFile
from django.conf import settings
import base64
import uuid

from .models import (
    AiProvider,
    AiChatSession,
    AiChatMessage,
    AiPromptTemplate,
    GPTModels,
    AiGeneratedImage,
)
from plans.models import UserSubscription
from .serializers import AiChatMessageSerializer

HISTORY_LIMIT = 15


def _build_openai_messages(session: AiChatSession, new_user_text: str, system_prompt: str) -> List[dict]:
    history = list(session.messages.order_by("-created_at")[:HISTORY_LIMIT][::-1])
    messages = [{"role": "system", "content": system_prompt}]
    for m in history:
        if m.content:
            messages.append({"role": m.role, "content": m.content})
    messages.append({"role": "user", "content": new_user_text})
    return messages


def _parse_template(request):
    templates = json.loads(request.data['templates'])
    return templates.get('GPT', None)


def _render_messages_as_dialog(messages: List[dict]) -> str:
    # Fallback for Responses API when we don't want to rebuild rich content
    lines = []
    for m in messages:
        role = m.get("role", "user").upper()
        content = m.get("content", "")
        lines.append(f"{role}: {content}")
    return "\n\n".join(lines)


def _is_reasoning(model_name: str) -> bool:
    m = model_name.lower()
    return m.startswith(("o1", "o3", "o4")) or "reasoning" in m


def _is_new_chat(model_name: str) -> bool:
    # Newer chat models prefer max_completion_tokens
    m = model_name.lower()
    return m.startswith(("gpt-4o", "gpt-4.1"))


def _make_openai_client(provider: AiProvider) -> OpenAI:
    kwargs = {"api_key": provider.token}
    if provider.base_url:
        kwargs["base_url"] = provider.base_url.rstrip("/")
    return OpenAI(**kwargs)


def _call_chat_completions_with_fallback(
    client: OpenAI,
    model_name: str,
    messages: List[dict],
    max_tokens_limit: Optional[int],
    allow_temperature: bool,
    requested_temperature: Optional[float],
) -> Tuple[Any, str]:
    """
    Try Chat Completions:
      1) Try max_completion_tokens (newer chat models).
      2) If 400 unsupported_parameter -> retry with max_tokens (legacy).
      3) If 400 unsupported_value on temperature/top_p -> retry without them.
    Returns (completion_obj, "chat").
    Raises the last exception if all attempts fail.
    """
    # Base params
    base = {"model": model_name, "messages": messages}

    # Temperature: add only if allowed/requested
    if allow_temperature and requested_temperature is not None:
        base["temperature"] = requested_temperature

    attempts = []

    # Prefer new field first
    if max_tokens_limit:
        attempts.append({**base, "max_completion_tokens": min(1000, max_tokens_limit)})
    attempts.append({**base})  # no explicit token limit
    if max_tokens_limit:
        attempts.append({**base, "max_tokens": min(1000, max_tokens_limit)})

    last_exc = None
    for params in attempts:
        try:
            return client.chat.completions.create(**params), "chat"
        except Exception as e:
            msg = str(e).lower()
            # Retry logic on common parameter errors
            if "unsupported parameter" in msg or "unsupported value" in msg:
                # If temperature/top_p caused error, drop them and try once more
                if "temperature" in msg and "unsupported" in msg:
                    p2 = {k: v for k, v in params.items() if k != "temperature" and k != "top_p"}
                    try:
                        return client.chat.completions.create(**p2), "chat"
                    except Exception as e2:
                        last_exc = e2
                        continue
                # If max_completion_tokens unsupported, try next attempt (we have both variants queued)
                last_exc = e
                continue
            last_exc = e
            continue

    if last_exc:
        raise last_exc
    raise RuntimeError("Chat completions fallback exhausted")


def _call_responses_api(
    client: OpenAI,
    model_name: str,
    messages: List[dict],
    max_tokens_limit: Optional[int],
) -> Tuple[Any, str]:
    """
    Use Responses API for reasoning models or as a final fallback.
    - Use input as flattened dialog text.
    - Use max_output_tokens if provided.
    Returns (response_obj, "responses").
    """
    input_text = _render_messages_as_dialog(messages)
    params = {"model": model_name, "input": input_text}
    if max_tokens_limit:
        params["max_output_tokens"] = min(1000, max_tokens_limit)

    resp = client.responses.create(**params)
    return resp, "responses"


def _extract_text_from_result(result: Any, endpoint: str) -> str:
    if endpoint == "chat":
        return (result.choices[0].message.content if getattr(result, "choices", None) else "") or ""
    # Responses API
    # SDK provides .output_text convenience; fallback to parsing content/items
    text = getattr(result, "output_text", None)
    if text:
        return text
    # Fallback parse
    try:
        parts = []
        for item in getattr(result, "output", []) or getattr(result, "content", []):
            if isinstance(item, dict):
                if item.get("type") in ("output_text", "text") and "text" in item:
                    parts.append(item["text"])
            else:
                s = str(item)
                if s:
                    parts.append(s)
        return "\n".join(parts).strip()
    except Exception:
        return ""
    

def _extract_usage_meta(result: Any, endpoint: str, model_name: str) -> dict:
    meta = {"model": model_name, "endpoint": endpoint}
    usage = getattr(result, "usage", None)
    if not usage:
        return meta
    try:
        if endpoint == "chat":
            meta.update({
                "prompt_tokens": getattr(usage, "prompt_tokens", None),
                "completion_tokens": getattr(usage, "completion_tokens", None),
                "total_tokens": getattr(usage, "total_tokens", None),
            })
        else:
            # Responses API naming
            meta.update({
                "input_tokens": getattr(usage, "input_tokens", None),
                "output_tokens": getattr(usage, "output_tokens", None),
                "total_tokens": getattr(usage, "total_tokens", None),
            })
    except Exception:
        pass
    return meta


def OpenAIHandler(request):
    try:
        # 1) Model
        subscription = UserSubscription.objects.filter(user=request.user).select_related("plan").first()
        default_model_name = getattr(getattr(subscription, "plan", None), "llm_engine", None) or "gpt-4o-mini"
        model_name = request.data.get("model", default_model_name)
        template_data = _parse_template(request)

        gpt_model = GPTModels.objects.filter(name=model_name, is_active=True).first()
        if not gpt_model:
            return {"error": f"Model '{model_name}' not found or inactive"}

        # 2) Provider
        provider_slug = request.data.get("provider_slug", "gpt")
        try:
            provider = AiProvider.objects.get(slug=provider_slug, is_active=True)
        except AiProvider.DoesNotExist:
            return {"error": f"Provider '{provider_slug}' not found or inactive"}

        # 3) System prompt
        system_prompt = "You are a helpful assistant."
        if template_data:
            template = AiPromptTemplate.objects.filter(
                id=template_data['id'], is_active=True, provider=provider
            ).first()
            if template:
                system_prompt = template.template
                template.usage_count = (template.usage_count or 0) + 1
                template.save(update_fields=["usage_count"])

        # 4) User message
        message = (request.data.get("message") or "").strip()
        if not message:
            return {"error": "No message provided"}
        attachments = request.data.get("attachments")

        # Optional temperature from request (only if user passes explicitly)
        req_temperature = request.data.get("temperature", None)
        try:
            if req_temperature is not None:
                req_temperature = float(req_temperature)
        except Exception:
            req_temperature = None

        # 5) Session + user message (transactional)
        session_id = request.data.get("session_id")
        with transaction.atomic():
            if session_id:
                session = (
                    AiChatSession.objects
                    .filter(id=session_id, user=request.user, is_active=True)
                    .select_for_update()
                    .first()
                )
                if not session:
                    return {"error": "Session not found"}
            else:
                title = message[:60] or "New Chat"
                session = AiChatSession.objects.create(
                    user=request.user,
                    provider=provider,
                    title=title,
                    chat_mode=request.data['mode'] or 'text-chat'
                )

            AiChatMessage.objects.create(
                session=session,
                role="user",
                content=message,
                attachments=attachments if isinstance(attachments, list) else None,
            )

        # 6) Build messages and call OpenAI
        messages = _build_openai_messages(session, message, system_prompt)
        client = _make_openai_client(provider)

        max_limit = gpt_model.max_tokens or None
        is_reason = _is_reasoning(gpt_model.name)
        is_newchat = _is_new_chat(gpt_model.name)

        # Heuristic: only add temperature if explicitly asked AND model is not reasoning
        allow_temperature = (not is_reason) and (req_temperature is not None)

        # First try Chat Completions with safe params (no temp by default)
        try:
            completion, endpoint = _call_chat_completions_with_fallback(
                client=client,
                model_name=gpt_model.name,
                messages=messages,
                max_tokens_limit=max_limit if is_newchat else max_limit,
                allow_temperature=allow_temperature,
                requested_temperature=req_temperature,
            )
        except Exception as chat_err:
            # If chat failed, try Responses API (esp. for reasoning models)
            try:
                completion, endpoint = _call_responses_api(
                    client=client,
                    model_name=gpt_model.name,
                    messages=messages,
                    max_tokens_limit=max_limit,
                )
            except Exception:
                # Re-raise original chat error to keep root cause
                raise chat_err

        answer = _extract_text_from_result(completion, endpoint)

        usage_meta = _extract_usage_meta(completion, endpoint, gpt_model.name)

        # 7) Save assistant message
        assistant_msg = AiChatMessage.objects.create(
            session=session,
            role="assistant",
            content=answer or "",
            attachments=None,
            meta=usage_meta,
        )

        return {
            "session": {
                "id": session.id,
                "title": session.title,
                "provider": provider.slug,
                "updated_at": session.updated_at,
            },
            "response": answer,
            "message": AiChatMessageSerializer(assistant_msg).data,
        }

    except Exception as e:
        print(f"Error in OpenAIHandler: {e} ")
        return {"error": str(e)}


def OpenAIImageHandler(request):
    """Generate image via OpenAI Images (DALL·E/gpt-image-1) and persist file + DB entry.

    Request expects:
      - message: prompt text (required)
      - session_id: optional existing session id
      - size: optional size like '1024x1024'
      - model: optional model name (default gpt-image-1)
      - provider_slug: optional provider (default 'gpt')
    """
    try:
        prompt = (request.data.get("message") or "").strip()
        if not prompt:
            return {"error": "No prompt provided"}

        size = (request.data.get("size") or "1024x1024").strip()
        model_name = (request.data.get("model") or "gpt-image-1").strip()
        provider_slug = request.data.get("provider_slug", "gpt")

        try:
            provider = AiProvider.objects.get(slug=provider_slug, is_active=True)
        except AiProvider.DoesNotExist:
            return {"error": f"Provider '{provider_slug}' not found or inactive"}

        client = _make_openai_client(provider)

        # Ensure session in image-chat mode and store user prompt
        session_id = request.data.get("session_id") or request.data.get("chat_id")
        with transaction.atomic():
            if session_id:
                session = (
                    AiChatSession.objects
                    .filter(id=session_id, user=request.user, is_active=True)
                    .select_for_update()
                    .first()
                )
                if not session:
                    return {"error": "Session not found"}
            else:
                title = (prompt[:60] or "Image Chat").strip() or "Image Chat"
                session = AiChatSession.objects.create(
                    user=request.user,
                    provider=provider,
                    title=title,
                    chat_mode='image-chat',
                )

            AiChatMessage.objects.create(
                session=session,
                role="user",
                content=prompt,
                attachments=None,
            )

        # Call Images API
        result = client.images.generate(model=model_name, prompt=prompt, size=size, n=1)
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

        # Persist image
        gen = AiGeneratedImage(
            user=request.user,
            session=session,
            provider=provider,
            model_name=model_name,
            prompt=prompt,
            size=size,
        )
        # Use stable name
        filename = f"{uuid.uuid4().hex}.png"
        gen.image.save(filename, ContentFile(raw), save=True)

        # Assistant message with image URL in content for simple rendering
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

        return {
            "session": {"id": session.id, "title": session.title, "provider": provider.slug, "updated_at": session.updated_at},
            "image": {"url": url, "size": size, "id": gen.id, "uniqid": gen.uniqid},
            "message": AiChatMessageSerializer(assistant_msg).data if assistant_msg else None,
        }

    except Exception as e:
        print(f"Error in OpenAIImageHandler: {e}")
        return {"error": str(e)}
