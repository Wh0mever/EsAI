# core/ai/actions.py
from __future__ import annotations

from typing import Iterable, Set
from dataclasses import dataclass
from django.db import transaction
from django.utils import timezone
from openai import OpenAI
from .models import AiProvider, GPTModels


@dataclass(frozen=True)
class RemoteModel:
    id: str
    description: str = ""  # API does not provide; keep empty
    max_tokens: int = 0    # Unknown at fetch time

def _build_client() -> OpenAI:
    provider = AiProvider.objects.get(slug="gpt", is_active=True)
    # openai>=1.0: use api_key, not token
    return OpenAI(api_key=provider.token)

def _fetch_remote_models(client: OpenAI) -> list[RemoteModel]:
    # The /models endpoint returns .data (list of Model objects with .id)
    resp = client.models.list()
    return [RemoteModel(m.id) for m in resp.data]

def _should_track(model_id: str) -> bool:
    """
    Keep policy simple & future-proof:
    - Track public chat/completion models (gpt-, o, o3, o4, omni, chatgpt-).
    - Ignore internal/embedding/audio-only tools if не нужно — при желании убери фильтр.
    """
    prefixes = ("gpt-", "o", "o3", "o4", "omni", "chatgpt-")
    return model_id.startswith(prefixes)

@transaction.atomic
def sync_gpt_models() -> dict:
    """
    Upsert models from OpenAI into GPTModels.
    Deactivate missing ones (soft).
    """
    client = _build_client()
    remote_all = _fetch_remote_models(client)
    remote = [m for m in remote_all if _should_track(m.id)]

    now = timezone.now()

    # Active set from remote
    active_ids: Set[str] = {m.id for m in remote}

    # Existing map
    existing: dict[str, GPTModels] = {
        obj.name: obj for obj in GPTModels.objects.all().only("id", "name", "is_active", "max_tokens", "description")
    }

    created, updated, activated, deactivated = 0, 0, 0, 0

    # Upsert current (create or update fields)
    for m in remote:
        obj = existing.get(m.id)
        if obj is None:
            GPTModels.objects.create(
                name=m.id,
                description=m.description,
                max_tokens=m.max_tokens,
                is_active=True,
            )
            created += 1
        else:
            changed = False
            if not obj.is_active:
                obj.is_active = True
                changed = True
                activated += 1
            # Keep description/max_tokens in sync if you later enrich them
            if obj.description != m.description:
                obj.description = m.description
                changed = True
            if obj.max_tokens != m.max_tokens:
                obj.max_tokens = m.max_tokens
                changed = True
            if changed:
                obj.save(update_fields=["description", "max_tokens", "is_active", "updated_at"])
                updated += 1

    # Deactivate models that disappeared remotely
    to_deactivate: Iterable[GPTModels] = GPTModels.objects.exclude(name__in=active_ids).filter(is_active=True)
    for obj in to_deactivate:
        obj.is_active = False
        obj.save(update_fields=["is_active", "updated_at"])
        deactivated += 1

    return {
        "timestamp": now.isoformat(),
        "remote_total": len(remote_all),
        "tracked": len(remote),
        "created": created,
        "updated": updated,
        "activated": activated,
        "deactivated": deactivated,
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
