from django.db import migrations, models


def _detect_kind(name: str, slug: str) -> str | None:
    n = (name or "").strip().lower()
    s = (slug or "").strip().lower()

    if n in {"gpt", "chatgpt", "openai"} or s in {"gpt", "chatgpt", "openai"}:
        return "gpt"
    if n in {"topmedia", "top-media"} or s in {"topmedia", "top-media"}:
        return "topmedia"
    if n in {"dall-e", "dalle", "dall·e", "dall_e", "dalle-3", "dalle3"} or s in {
        "dall-e",
        "dalle",
        "dall_e",
        "dalle-3",
        "dalle3",
    }:
        return "dall-e"
    return None


def _merge_provider_group(apps, canonical_name: str, canonical_slug: str, provider_ids: list[int]) -> None:
    if not provider_ids:
        return

    AiProvider = apps.get_model("ai", "AiProvider")
    AiChatSession = apps.get_model("ai", "AiChatSession")
    AiPromptTemplate = apps.get_model("ai", "AiPromptTemplate")
    AiGeneratedImage = apps.get_model("ai", "AiGeneratedImage")

    providers = list(AiProvider.objects.filter(id__in=provider_ids).order_by("id"))
    if not providers:
        return

    keeper = None
    for p in providers:
        if (p.slug or "").strip().lower() == canonical_slug:
            keeper = p
            break
    if keeper is None:
        for p in providers:
            if (p.name or "").strip() == canonical_name:
                keeper = p
                break
    if keeper is None:
        keeper = providers[0]

    duplicates = [p for p in providers if p.id != keeper.id]
    for dup in duplicates:
        AiChatSession.objects.filter(provider_id=dup.id).update(provider_id=keeper.id)
        AiPromptTemplate.objects.filter(provider_id=dup.id).update(provider_id=keeper.id)
        AiGeneratedImage.objects.filter(provider_id=dup.id).update(provider_id=keeper.id)
        dup.delete()

    changed = False
    if keeper.name != canonical_name:
        keeper.name = canonical_name
        changed = True
    if keeper.slug != canonical_slug:
        keeper.slug = canonical_slug
        changed = True
    if changed:
        keeper.save(update_fields=["name", "slug", "updated_at"])


def normalize_providers(apps, schema_editor):
    AiProvider = apps.get_model("ai", "AiProvider")
    providers = list(AiProvider.objects.all().only("id", "name", "slug"))

    by_kind: dict[str, list[int]] = {"gpt": [], "topmedia": [], "dall-e": []}
    for p in providers:
        kind = _detect_kind(getattr(p, "name", ""), getattr(p, "slug", ""))
        if kind:
            by_kind[kind].append(p.id)

    _merge_provider_group(
        apps,
        canonical_name="GPT",
        canonical_slug="gpt",
        provider_ids=by_kind["gpt"],
    )
    _merge_provider_group(
        apps,
        canonical_name="Topmedia",
        canonical_slug="topmedia",
        provider_ids=by_kind["topmedia"],
    )
    _merge_provider_group(
        apps,
        canonical_name="Dall-e",
        canonical_slug="dall-e",
        provider_ids=by_kind["dall-e"],
    )


class Migration(migrations.Migration):

    dependencies = [
        ("ai", "0002_ai_ru_model_labels"),
    ]

    operations = [
        migrations.AlterField(
            model_name="aiprovider",
            name="name",
            field=models.CharField(
                choices=[("GPT", "GPT"), ("Topmedia", "Topmedia"), ("Dall-e", "Dall-e")],
                max_length=100,
                unique=True,
            ),
        ),
        migrations.AlterField(
            model_name="aiprovider",
            name="slug",
            field=models.SlugField(editable=False, unique=True),
        ),
        migrations.RunPython(normalize_providers, migrations.RunPython.noop),
    ]
