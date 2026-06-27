import json
from typing import Any, Optional, List, Tuple
from django.db import transaction
from openai import OpenAI
from django.conf import settings

from .models import (
    AiProvider,
    AiChatSession,
    AiChatMessage,
    AiPromptTemplate,
    GPTModels,
)
from plans.models import UserSubscription
from plans.services import get_chat_access_state, consume_bonus_without_subscription
from django.core.exceptions import ValidationError
from .serializers import AiChatMessageSerializer

# No hard message count limit; we'll include full history.
HISTORY_LIMIT = None


def _provider_name_by_mode(mode: str | None) -> str:
    return AiProvider.NAME_GPT


def _load_active_provider(mode: str | None) -> tuple[Optional[AiProvider], Optional[str]]:
    provider_name = _provider_name_by_mode(mode)
    provider = AiProvider.objects.filter(name=provider_name, is_active=True).first()
    if provider:
        return provider, None
    fallback_slug = AiProvider.NAME_TO_SLUG.get(provider_name)
    if fallback_slug:
        provider = AiProvider.objects.filter(slug=fallback_slug, is_active=True).first()
        if provider:
            return provider, None
    return None, f"Provider '{provider_name}' not found or inactive"


def _resolve_session_for_user(user, session_ref: Any, for_update: bool = False) -> Optional[AiChatSession]:
    raw = (str(session_ref).strip() if session_ref is not None else "")
    if not raw:
        return None

    qs = AiChatSession.objects.filter(user=user, is_active=True)
    if for_update:
        qs = qs.select_for_update()

    if raw.isdigit():
        by_id = qs.filter(id=int(raw)).first()
        if by_id:
            return by_id
    return qs.filter(uid=raw).first()


def _build_openai_messages(session: AiChatSession, new_user_text: str, system_prompt: str, origin_base: str | None = None) -> List[dict]:
    """Build messages for Chat Completions, supporting image attachments.

    If a message has attachments with type "image" and a URL, we include them via
    multi-part content: [{type: 'text', text: ...}, {type: 'image_url', image_url: {url}}].
    """
    def to_abs(url: str) -> str:
        if not url:
            return url
        if url.startswith("http://") or url.startswith("https://"):
            return url
        base = (origin_base or "").rstrip("/")
        return f"{base}{url}" if base else url

    history = list(session.messages.order_by("created_at"))
    out: List[dict] = [{"role": "system", "content": system_prompt}]

    for m in history:
        parts = []
        txt = (m.content or "").strip()
        if txt:
            parts.append({"type": "text", "text": txt})
        try:
            atts = m.attachments or []
        except Exception:
            atts = []
        if isinstance(atts, list):
            for a in atts:
                try:
                    if (a or {}).get("type") == "image":
                        u = to_abs((a or {}).get("url") or "")
                        if u:
                            parts.append({"type": "image_url", "image_url": {"url": u}})
                except Exception:
                    continue
        # Fallback to simple string if no parts
        content_obj = parts if parts else (txt or "")
        out.append({"role": m.role, "content": content_obj})

    return out


def _parse_template(request, provider_name: str):
    raw = request.data.get("templates")
    if not raw:
        return None
    try:
        templates = json.loads(raw)
    except Exception:
        return None
    if not isinstance(templates, dict):
        return None
    return (
        templates.get(provider_name)
        or templates.get(provider_name.lower())
        or templates.get("GPT")
)

OPENAI_API_BASE = "https://api.openai.com/v1"


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
    slug = (provider.slug or "").strip().lower()
    # Do not depend on DB base_url for runtime routing.
    if slug == "gpt":
        kwargs["base_url"] = OPENAI_API_BASE
    # Respect global timeout to avoid gunicorn worker timeouts
    try:
        from django.conf import settings as dj_settings
        to = int(getattr(dj_settings, "OPENAI_TIMEOUT_SECONDS", 480) or 480)
    except Exception:
        to = 480
    kwargs["timeout"] = to
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


def _is_context_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return (
        "maximum context length" in msg
        or "context length" in msg
        or "too many tokens" in msg
        or "max tokens" in msg and "exceeded" in msg
        or "token limit" in msg
    )


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


def _pick_lang(request) -> tuple[str, str]:
    """Return (lang_code, human_name) from request (data.lang or Accept-Language)."""
    # Preferred: explicit lang from client
    raw = (getattr(request, "data", {}) or {}).get("lang")
    if isinstance(raw, str) and raw:
        code = raw.strip().lower()
    else:
        # Fallback: Accept-Language header like 'ru,en;q=0.9'
        header = (request.META.get("HTTP_ACCEPT_LANGUAGE") or "").split(",")[0]
        code = header.strip().lower() or "ru"

    # Normalize to base language
    if code.startswith("ru"): return "ru", "Russian"
    if code.startswith(("kg", "ky")): return "ky", "Kyrgyz"
    if code.startswith("en"): return "en", "English"
    if code.startswith("tr"): return "tr", "Turkish"
    if code.startswith("de"): return "de", "German"
    if code.startswith("fr"): return "fr", "French"
    # default
    return "ru", "Russian"


def OpenAIHandler(request):
    try:
        mode = request.data.get("mode") or "text-chat"
        lang_code, _ = _pick_lang(request)
        access = get_chat_access_state(request.user, "kg" if lang_code == "ky" else lang_code, kind="text")
        if access.get("blocked"):
            return {"error": access.get("error"), "error_code": access.get("error_code"), "grace_until": access.get("grace_until")}
        # 1) Model + subscription/limits
        subscription = (
            UserSubscription.objects
            .filter(user=request.user, status="active")
            .select_related("plan")
            .order_by("-start_date")
            .first()
        )
        # Use plan's configured LLM engine name
        plan_obj = getattr(subscription, "plan", None)
        plan_engine = getattr(plan_obj, "llm_engine", None)
        default_model_name = getattr(plan_engine, "name", None) or "gpt-4o-mini"
        model_obj = GPTModels.objects.filter(name=request.data.get("model", default_model_name), is_active=True).first()

        model_name = request.data.get("model", default_model_name)
        provider_name = _provider_name_by_mode(mode)
        template_data = _parse_template(request, provider_name)
        selected_model_name = model_obj.name if model_obj else model_name
        model_max_tokens = model_obj.max_tokens if model_obj else None

        # 2) Provider
        provider, provider_error = _load_active_provider(mode)
        if provider_error:
            return {"error": provider_error}
        if not (provider.token or "").strip():
            return {"error": "Text provider is not configured."}

        # 3) System prompt + locale policy
        lang_code, lang_name = _pick_lang(request)
        system_prompt = "You are a helpful assistant."
        # Enforce reply language strictly
        locale_policy = (
            f"Always and strictly reply in {lang_name} language (locale: {lang_code}). "
            f"Do not switch languages unless explicitly told to translate into another language, "
            f"and prefer {lang_name} for all outputs and explanations."
        )
        if template_data:
            template = AiPromptTemplate.objects.filter(
                id=template_data['id'], is_active=True, provider=provider
            ).first()
            if template:
                system_prompt = template.template
                template.usage_count = (template.usage_count or 0) + 1
                template.save(update_fields=["usage_count"])

        # Combine template/system with locale rule
        system_prompt = f"{system_prompt}\n\n{locale_policy}"

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
        # Support both keys from clients: session_id and chat_id
        session_id = request.data.get("session_id") or request.data.get("chat_id")
        with transaction.atomic():
            if session_id:
                session = _resolve_session_for_user(request.user, session_id, for_update=True)
                if not session:
                    return {"error": "Session not found"}
            else:
                title = message[:60] or "New Chat"
                session = AiChatSession.objects.create(
                    user=request.user,
                    provider=provider,
                    title=title,
                    chat_mode=mode
                )

            AiChatMessage.objects.create(
                session=session,
                role="user",
                content=message,
                attachments=attachments if isinstance(attachments, list) else None,
            )

        # 6) Limits pre-check (text)
        consume_kind = "text"
        if subscription and not subscription.can_consume(consume_kind):
            is_unpaid = str(getattr(subscription, "payment_status", "")).lower() == "unpaid"
            code = "chat_blocked_limits_exhausted_unpaid" if is_unpaid else "chat_blocked_limits_exhausted"
            return {
                "error": "Лимиты на генерацию текста исчерпаны. Пополните лимит или обновите тариф.",
                "error_code": code,
            }

        # 7) Build messages and call OpenAI
        # Build origin base for absolute URLs (multi-domain support)
        try:
            proto = request.headers.get("X-Forwarded-Proto") or ("https" if request.is_secure() else "http")
            host = request.get_host() or ""
            origin_base = f"{proto}://{host}" if host else None
        except Exception:
            origin_base = None

        messages = _build_openai_messages(session, message, system_prompt, origin_base)
        client = _make_openai_client(provider)

        # Determine completion tokens limit from selected model settings
        max_limit = model_max_tokens or None
        is_reason = _is_reasoning(selected_model_name)
        is_newchat = _is_new_chat(selected_model_name)

        # Heuristic: only add temperature if explicitly asked AND model is not reasoning
        allow_temperature = (not is_reason) and (req_temperature is not None)

        # Try, and if context too long, progressively trim oldest messages while keeping system+latest user
        messages_work = list(messages)
        while True:
            try:
                completion, endpoint = _call_chat_completions_with_fallback(
                    client=client,
                    model_name=selected_model_name,
                    messages=messages_work,
                    max_tokens_limit=max_limit if is_newchat else max_limit,
                    allow_temperature=allow_temperature,
                    requested_temperature=req_temperature,
                )
                break
            except Exception as chat_err:
                # Try Responses API
                try:
                    completion, endpoint = _call_responses_api(
                        client=client,
                        model_name=selected_model_name,
                        messages=messages_work,
                        max_tokens_limit=max_limit,
                    )
                    break
                except Exception as resp_err:
                    if _is_context_error(chat_err) or _is_context_error(resp_err):
                        # Keep system at [0] and last user at end; drop the oldest content message at [1]
                        if len(messages_work) > 3:
                            del messages_work[1]
                            continue
                    # No context issue or cannot shrink further: raise the original chat error
                    raise chat_err

        answer = _extract_text_from_result(completion, endpoint)
        if not (answer or "").strip():
            return {"error": "Failed to generate response."}

        usage_meta = _extract_usage_meta(completion, endpoint, selected_model_name)

        # 8) Save assistant message
        assistant_msg = AiChatMessage.objects.create(
            session=session,
            role="assistant",
            content=answer or "",
            attachments=None,
            meta=usage_meta,
        )

        # 9) Consume one unit (best-effort; race-safe inside consume)
        if subscription:
            try:
                subscription.consume(consume_kind)
            except ValidationError:
                # Very rare race; ignore here to not break user flow
                pass
        else:
            consume_bonus_without_subscription(request.user, consume_kind)

        return {
            "session": {
                "id": session.id,
                "uid": session.uid,
                "title": session.title,
                "provider": provider.slug,
                "updated_at": session.updated_at,
            },
            "response": answer,
            "message": AiChatMessageSerializer(assistant_msg).data,
            "warning": access.get("warning"),
            "warning_code": access.get("warning_code"),
            "grace_until": access.get("grace_until"),
        }

    except Exception as e:
        print(f"Error in OpenAIHandler: {e} ")
        return {"error": str(e)}
