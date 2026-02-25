# core/ai/actions.py
from __future__ import annotations

from typing import Iterable, Set
from dataclasses import dataclass
from django.db import transaction
from django.utils import timezone
from openai import OpenAI
from .models import AiProvider, GPTModels, TopMediaModels

class ProviderConfigError(Exception):
    pass


@dataclass(frozen=True)
class RemoteModel:
    id: str
    description: str = ""  # API does not provide; keep empty
    max_tokens: int = 0    # Unknown at fetch time


TOPMEDIA_STATIC_MODELS: tuple[tuple[str, str, str], ...] = (
    # name, kind, description
    ("v4.5-plus", TopMediaModels.KIND_MUSIC, "AI Music Generator model_version"),
    ("v4.5", TopMediaModels.KIND_MUSIC, "AI Music Generator model_version"),
    ("v4.0", TopMediaModels.KIND_MUSIC, "AI Music Generator model_version"),
    ("v3.5", TopMediaModels.KIND_MUSIC, "AI Music Generator model_version"),
    ("v3.0", TopMediaModels.KIND_MUSIC, "AI Music Generator model_version"),
    ("Gen", TopMediaModels.KIND_VOICE_CLONE, "Voice Cloning model"),
    ("HD", TopMediaModels.KIND_VOICE_CLONE, "Voice Cloning model"),
)

def _build_client(provider_slug: str) -> OpenAI:
    provider = AiProvider.objects.filter(slug=provider_slug).first()
    if provider is None:
        # Auto-create provider record to simplify initial setup, then ask for config.
        if provider_slug == "topmedia":
            AiProvider.objects.get_or_create(
                name=AiProvider.NAME_TOPMEDIA,
                defaults={"is_active": False, "token": "", "description": "Auto-created provider record"},
            )
            raise ProviderConfigError(
                "TopMedia provider was missing and has been auto-created. "
                "Open AI providers in admin, set token/base_url and enable it."
            )
        if provider_slug == "gpt":
            AiProvider.objects.get_or_create(
                name=AiProvider.NAME_GPT,
                defaults={"is_active": False, "token": "", "description": "Auto-created provider record"},
            )
            raise ProviderConfigError(
                "GPT provider was missing and has been auto-created. "
                "Open AI providers in admin, set token/base_url and enable it."
            )
        raise ProviderConfigError(f"Provider '{provider_slug}' does not exist.")
    if not provider.is_active:
        raise ProviderConfigError(f"Provider '{provider.name}' is disabled.")
    if not (provider.token or "").strip():
        raise ProviderConfigError(f"Provider '{provider.name}' has empty token.")
    # openai>=1.0: use api_key, not token
    kwargs = {"api_key": provider.token}
    if provider.base_url:
        kwargs["base_url"] = provider.base_url.rstrip("/")
    return OpenAI(**kwargs)

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
    client = _build_client("gpt")
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


@transaction.atomic
def sync_topmedia_models() -> dict:
    """
    Upsert TopMedia models from static documented catalog.
    TopMedia does not provide a models endpoint.
    """
    remote_all = [
        {"name": name, "kind": kind, "description": description}
        for name, kind, description in TOPMEDIA_STATIC_MODELS
    ]
    remote = remote_all

    now = timezone.now()
    active_ids: Set[str] = {m["name"] for m in remote}

    existing: dict[str, TopMediaModels] = {
        obj.name: obj
        for obj in TopMediaModels.objects.all().only(
            "id", "name", "kind", "is_active", "max_tokens", "description"
        )
    }

    created, updated, activated, deactivated = 0, 0, 0, 0

    for m in remote:
        obj = existing.get(m["name"])
        if obj is None:
            TopMediaModels.objects.create(
                name=m["name"],
                kind=m["kind"],
                description=m["description"],
                max_tokens=0,
                is_active=True,
            )
            created += 1
        else:
            changed = False
            if not obj.is_active:
                obj.is_active = True
                changed = True
                activated += 1
            if obj.kind != m["kind"]:
                obj.kind = m["kind"]
                changed = True
            if obj.description != m["description"]:
                obj.description = m["description"]
                changed = True
            if changed:
                obj.save(update_fields=["kind", "description", "is_active", "updated_at"])
                updated += 1

    to_deactivate: Iterable[TopMediaModels] = TopMediaModels.objects.exclude(name__in=active_ids).filter(is_active=True)
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


def get_topmedia_models_action() -> list[str]:
    stats = sync_topmedia_models()
    names = list(
        TopMediaModels.objects.filter(is_active=True).order_by("name").values_list("name", flat=True)
    )
    print(f"[TopMedia Models] Sync stats: {stats}")
    print(f"[TopMedia Models] Active: {len(names)}")
    return names
