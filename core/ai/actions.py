# core/ai/actions.py
from __future__ import annotations

import os
from typing import Set
from dataclasses import dataclass
from django.db import transaction
from django.utils import timezone
from openai import OpenAI
from .models import AiProvider, GPTModels

# OpenRouter defaults (overridable via env)
OPENROUTER_API_BASE_DEFAULT = "https://openrouter.ai/api/v1"
OPENROUTER_REFERER_DEFAULT = "https://esai.kg"
OPENROUTER_TITLE_DEFAULT = "ESAI"

class ProviderConfigError(Exception):
    pass


@dataclass(frozen=True)
class RemoteModel:
    id: str
    description: str = ""  # API does not provide; keep empty
    max_tokens: int = 0    # Unknown at fetch time


def _build_client(provider_slug: str | None = None) -> OpenAI:
    """Build an OpenRouter-compatible OpenAI client from environment config.

    The api_key / base_url come from env (OPENROUTER_API_KEY / OPENROUTER_API_BASE),
    not from AiProvider.token. AiProvider is kept only as an optional directory record.
    """
    api_key = (os.environ.get("OPENROUTER_API_KEY") or "").strip()
    if not api_key:
        raise ProviderConfigError(
            "OpenRouter is not configured: set OPENROUTER_API_KEY in the environment."
        )
    base_url = (os.environ.get("OPENROUTER_API_BASE") or OPENROUTER_API_BASE_DEFAULT).strip()
    referer = (os.environ.get("OPENROUTER_HTTP_REFERER") or OPENROUTER_REFERER_DEFAULT).strip()
    title = (os.environ.get("OPENROUTER_X_TITLE") or OPENROUTER_TITLE_DEFAULT).strip()
    return OpenAI(
        api_key=api_key,
        base_url=base_url,
        default_headers={"HTTP-Referer": referer, "X-Title": title},
    )

def _fetch_remote_models(client: OpenAI) -> list[RemoteModel]:
    # The /models endpoint returns .data (list of Model objects with .id)
    resp = client.models.list()
    return [RemoteModel(m.id) for m in resp.data]

@transaction.atomic
def sync_gpt_models() -> dict:
    """
    Verify the OpenRouter ids configured in GPTModels against the live OpenRouter
    catalogue. This is a non-destructive helper (the catalogue is managed by the
    client in the admin, not auto-imported): it only reports which of the configured
    openrouter_id values are currently available remotely. It never creates,
    deactivates or overwrites admin-managed rows.
    """
    client = _build_client()
    remote_all = _fetch_remote_models(client)

    now = timezone.now()
    remote_ids: Set[str] = {m.id for m in remote_all}

    configured = list(
        GPTModels.objects.all().only("id", "name", "openrouter_id", "is_active")
    )
    available = [m for m in configured if (m.openrouter_id or "") in remote_ids]
    missing = [m for m in configured if (m.openrouter_id or "") not in remote_ids]

    return {
        "timestamp": now.isoformat(),
        "remote_total": len(remote_all),
        "configured": len(configured),
        "available": [m.openrouter_id for m in available],
        "missing": [m.openrouter_id or m.name for m in missing],
    }


def get_gpt_models_action() -> list[str]:
    """
    Kept for backward compatibility: returns current active names.
    """
    stats = sync_gpt_models()
    names = list(
        GPTModels.objects.filter(is_active=True).order_by("name").values_list("name", flat=True)
    )
    print(f"[Models] Sync stats: {stats}")
    print(f"[Models] Active: {len(names)}")
    return names
