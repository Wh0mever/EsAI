from openai import OpenAI
from typing import Any, List, Optional
from openai import OpenAI
from .models import AiProvider, AiChatSession, AiChatMessage
from .serializers import (
    AiChatMessageSerializer,
)

SYSTEM_PROMPT = "You must always tell like a Yoda. Jedi Master you are. Speak like Yoda, you must. Use the Force, you will. and you must tell only on Russian language. Do not use any other languages, only Russian. Speak like Yoda, you must. Use the Force, you will."
DEFAULT_MODEL = "gpt-4o"
HISTORY_LIMIT = 20


def _build_openai_messages(session: AiChatSession, new_user_text: str) -> List[dict]:
    history = list(
        session.messages.order_by("-created_at")[:HISTORY_LIMIT][::-1]
    )
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for m in history:
        if m.content:
            messages.append({"role": m.role, "content": m.content})
    messages.append({"role": "user", "content": new_user_text})
    return messages


def OpenAIHandler(request):
    try:
        message = request.data.get("message", "")
        if not isinstance(message, str) or not message.strip():
            return {"error": "No message provided"}

        provider_slug = request.data.get("provider_slug", "gpt")
        model = request.data.get("model", DEFAULT_MODEL)
        attachments = request.data.get("attachments")
        session_id = request.data.get("session_id")

        try:
            provider = AiProvider.objects.get(
                slug=provider_slug, is_active=True)
        except AiProvider.DoesNotExist:
            return {"error": f"Provider '{provider_slug}' not found or inactive"}

        client = OpenAI(api_key=provider.token)

        session: Optional[AiChatSession] = None
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
            # title based on the first message
            title = message.strip()[:60]
            session = AiChatSession.objects.create(
                user=request.user,
                provider=provider,
                title=title or "New Chat",
            )

        # 2) Save user message
        user_msg = AiChatMessage.objects.create(
            session=session,
            role="user",
            content=message.strip(),
            attachments=attachments if isinstance(attachments, list) else None,
        )

        # 3) Create OpenAI messages
        messages = _build_openai_messages(session, message.strip())

        try:
            completion = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.7,
                max_tokens=1000,
                top_p=1,
            )
        except Exception as e:
            raise

        answer = completion.choices[0].message.content if completion.choices else ""

        # usage: token usage metadata
        usage_meta: dict[str, Any] = {}
        try:
            usage = completion.usage
            if usage:
                usage_meta = {
                    "model": model,
                    "prompt_tokens": getattr(usage, "prompt_tokens", None),
                    "completion_tokens": getattr(usage, "completion_tokens", None),
                    "total_tokens": getattr(usage, "total_tokens", None),
                }
        except Exception:
            usage_meta = {"model": model}

        # 4) Save assistant message
        assistant_msg = AiChatMessage.objects.create(
            session=session,
            role="assistant",
            content=answer or "",
            attachments=None,
            meta=usage_meta,
        )

        # 5) Result
        return {
            "session": {
                "id": session.id,
                "title": session.title,
                "provider": provider.slug,
                "updated_at": session.updated_at,
            },
            "response": answer,
            "message": AiChatMessageSerializer(assistant_msg).data,
        },
    except Exception as e:
        print(f"Error in GPTHandler: {e}")
        
