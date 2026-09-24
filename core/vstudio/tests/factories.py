"""Фабрики для тестов видеостудии.

Простые функции без factory_boy (его нет в зависимостях). Каждая создаёт
строку с разумными значениями по умолчанию, всё можно переопределить
ключевыми словами. Денежные поля дубля согласованы с CheckConstraint
vs_take_open_reserved: открытый — reserved, done — charged, остальные
закрытые — released.

    user = make_user(balance=500)
    asset = make_asset(user)
    shot = make_shot(user, inputs=[asset])            # @Image 1 = asset
    take = make_take(shot, status="running", genlog=True)

Файлов на диск фабрики не пишут, пока не попросить store=True; тогда тест
должен подменить MEDIA_ROOT (см. media_root()).
"""
from __future__ import annotations

import io
import itertools
import shutil
import tempfile
from contextlib import contextmanager
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.test import override_settings

from ai.models import GenerationLog, GPTModels

from ..models import TAKE_OPEN, Asset, Project, Shot, ShotInput, Take

_seq = itertools.count(1)

VIDEO_MODEL_REF = "bytedance/seedance-2.0"
IMAGE_MODEL_REF = "google/gemini-2.5-flash-image"


def _n() -> int:
    return next(_seq)


# ---------------------------------------------------------------- люди и модели

def make_user(email: str | None = None, *, balance: int = 0, is_paid: bool = True,
              is_staff: bool = False, password: str = "x", **extra):
    User = get_user_model()
    user = User.objects.create_user(email=email or f"vs{_n()}@example.com", password=password,
                                    is_staff=is_staff, **extra)
    user.token_balance = balance
    user.is_paid = is_paid
    user.save(update_fields=["token_balance", "is_paid"])
    return user


def make_gpt_model(openrouter_id: str = VIDEO_MODEL_REF, *, category: str | None = None,
                   name: str | None = None, markup: float | Decimal = 1,
                   vstudio_enabled: bool = True, **extra) -> GPTModels:
    """Модель каталога; повторный вызов с тем же openrouter_id отдаёт ту же строку."""
    existing = GPTModels.objects.filter(openrouter_id=openrouter_id).first()
    if existing:
        return existing
    if category is None:
        category = "image" if openrouter_id == IMAGE_MODEL_REF or "image" in openrouter_id else "video"
    return GPTModels.objects.create(
        name=name or f"{openrouter_id} #{_n()}", openrouter_id=openrouter_id, max_tokens=100,
        markup_coefficient=Decimal(str(markup)), category=category,
        vstudio_enabled=vstudio_enabled, **extra)


# ---------------------------------------------------------------- проект и материалы

def make_project(user=None, **kw) -> Project:
    return Project.objects.create(user=user or make_user(), **kw)


def image_bytes(width: int = 640, height: int = 480, fmt: str = "JPEG",
                color=(200, 120, 40)) -> bytes:
    """Настоящая картинка в памяти (для загрузок, нормализатора и store=True)."""
    from PIL import Image

    mode = "RGBA" if fmt.upper() == "PNG" and len(color) == 4 else "RGB"
    buf = io.BytesIO()
    Image.new(mode, (width, height), color).save(buf, format=fmt)
    return buf.getvalue()


@contextmanager
def media_root():
    """Временный MEDIA_ROOT: store=True и конвейер пишут туда, а не в media/."""
    path = tempfile.mkdtemp(prefix="vstudio-test-")
    try:
        with override_settings(MEDIA_ROOT=path):
            yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def make_asset(user=None, *, project=None, kind: str = Asset.KIND_IMAGE,
               source: str = Asset.SOURCE_UPLOAD, status: str = Asset.STATUS_READY,
               width: int | None = 1024, height: int | None = 1024, store: bool = False,
               **kw) -> Asset:
    """Материал. Пути файлов — как у настоящих (vstudio/<user_id>/<uid>.jpg).

    store=True кладёт в default_storage настоящую JPEG-картинку нужного размера
    (только картинки; оберните тест в media_root()).
    """
    user = user or (project.user if project else make_user())
    asset = Asset(user=user, project=project, kind=kind, source=source, status=status,
                  width=width, height=height, **kw)
    ext = {Asset.KIND_IMAGE: "jpg", Asset.KIND_VIDEO: "mp4", Asset.KIND_AUDIO: "mp3"}[kind]
    if status != Asset.STATUS_PENDING and "file" not in kw:
        asset.file = f"vstudio/{user.pk}/{asset.uid}.{ext}"
        asset.thumb = kw.get("thumb", f"vstudio/{user.pk}/{asset.uid}_t.jpg")
        asset.mime = kw.get("mime", {"jpg": "image/jpeg", "mp4": "video/mp4",
                                     "mp3": "audio/mpeg"}[ext])
    if store:
        if kind != Asset.KIND_IMAGE:
            raise ValueError("store=True умеет только картинки")
        blob = image_bytes(width or 640, height or 480)
        asset.file = default_storage.save(asset.file or f"vstudio/{user.pk}/{asset.uid}.jpg",
                                          ContentFile(blob))
        asset.bytes = len(blob)
    asset.save()
    return asset


# ---------------------------------------------------------------- запрос

def prompt_doc(*parts) -> dict:
    """Документ §4.1 из кусков: строка — текст, Asset или uid (32 hex) — ссылка.

    Список внутри parts — отдельный абзац: prompt_doc("a", ["b", asset]).
    """
    def node(part):
        if isinstance(part, Asset):
            return {"t": "ref", "asset": part.uid}
        if isinstance(part, str) and len(part) == 32 and all(c in "0123456789abcdef" for c in part):
            return {"t": "ref", "asset": part}
        return {"t": "text", "v": str(part)}

    def block(items):
        # Соседние куски текста — один узел, как их отдаёт редактор.
        out = []
        for n in map(node, items):
            if n["t"] == "text" and out and out[-1]["t"] == "text":
                out[-1] = {"t": "text", "v": out[-1]["v"] + n["v"]}
            else:
                out.append(n)
        return out

    blocks, current = [], []
    for part in parts:
        if isinstance(part, (list, tuple)):
            if current:
                blocks.append(block(current))
                current = []
            blocks.append(block(part))
        else:
            current.append(part)
    if current or not blocks:
        blocks.append(block(current))
    return {"v": 1, "blocks": blocks}


def render_prompt_text(doc: dict, inputs: list[ShotInput]) -> str:
    """«@Image N» по включённым референсам в порядке лотка (§4.2), кадры — по имени."""
    refs = sorted((i for i in inputs if i.slot == ShotInput.SLOT_REFERENCE and i.included),
                  key=lambda i: i.position)
    labels = {i.asset.uid: f"@Image {n}" for n, i in enumerate(refs, start=1)}
    frames = {ShotInput.SLOT_FIRST_FRAME: "@Первый кадр", ShotInput.SLOT_LAST_FRAME: "@Последний кадр"}
    for i in inputs:
        if i.slot in frames:
            labels.setdefault(i.asset.uid, frames[i.slot])
    out = []
    for block in doc.get("blocks", []):
        out.append("".join(n["v"] if n["t"] == "text" else labels.get(n["asset"], "@Image —")
                           for n in block))
    return "\n".join(out)


def make_shot(user=None, *, project=None, kind: str = Shot.KIND_VIDEO, model=None,
              model_ref: str | None = None, prompt: str = "Девушка идёт по крыше",
              doc: dict | None = None, prompt_text: str | None = None, params: dict | None = None,
              inputs=(), **kw) -> Shot:
    """Запрос с материалами.

    inputs — Asset (референс), (asset, slot) или dict(asset=…, slot=…, role=…,
    included=…, position=…). Позиции по умолчанию — порядок внутри слота.
    Без doc промпт = prompt + упоминание каждого референса по порядку.
    """
    if project is None:
        project = make_project(user)
    user = user or project.user
    if model is None and model_ref is None:
        model = make_gpt_model(VIDEO_MODEL_REF if kind == Shot.KIND_VIDEO else IMAGE_MODEL_REF)
    model_ref = model_ref or (model.openrouter_id if model else VIDEO_MODEL_REF)

    rows = []
    for item in inputs:
        if isinstance(item, Asset):
            item = {"asset": item}
        elif isinstance(item, (list, tuple)):
            item = {"asset": item[0], "slot": item[1]}
        rows.append({"slot": ShotInput.SLOT_REFERENCE, **item})
    if doc is None:
        parts = [prompt]
        for row in rows:
            if row["slot"] == ShotInput.SLOT_REFERENCE:
                parts += [" ", row["asset"]]
        doc = prompt_doc(*parts)

    shot = Shot.objects.create(user=user, project=project, kind=kind, model=model,
                               model_ref=model_ref, prompt_doc=doc, prompt_text=prompt_text or "",
                               params=params if params is not None else {}, **kw)
    used = {}
    created = []
    for row in rows:
        slot = row["slot"]
        position = row.get("position", used.get(slot, 0))
        used[slot] = position + 1
        created.append(ShotInput.objects.create(
            shot=shot, asset=row["asset"], slot=slot, position=position,
            role=row.get("role", ""), included=row.get("included", True)))
    if prompt_text is None:
        shot.prompt_text = render_prompt_text(doc, created)
        shot.save(update_fields=["prompt_text"])
    return shot


# ---------------------------------------------------------------- дубль и журнал

def _default_mode(shot: Shot) -> str:
    slots = {i.slot for i in shot.inputs.all() if i.included}
    if shot.kind == Shot.KIND_IMAGE:
        return Take.MODE_I2I if slots else Take.MODE_T2I
    if ShotInput.SLOT_REFERENCE in slots:
        return Take.MODE_R2V
    if ShotInput.SLOT_LAST_FRAME in slots:
        return Take.MODE_FLF2V
    if ShotInput.SLOT_FIRST_FRAME in slots:
        return Take.MODE_I2V
    return Take.MODE_T2V


def make_genlog(take: Take, **kw) -> GenerationLog:
    """Запись журнала, как её пишет submit_take: source=vstudio, params.take=uid."""
    status = kw.pop("status", {
        Take.STATUS_QUEUED: GenerationLog.STATUS_SUBMITTING,
        Take.STATUS_SUBMITTING: GenerationLog.STATUS_SUBMITTING,
        Take.STATUS_RUNNING: GenerationLog.STATUS_SUBMITTED,
        Take.STATUS_SAVING: GenerationLog.STATUS_SUBMITTED,
        Take.STATUS_DONE: GenerationLog.STATUS_DELIVERED,
        Take.STATUS_FAILED: GenerationLog.STATUS_FAILED,
        Take.STATUS_CANCELED: GenerationLog.STATUS_FAILED,
        Take.STATUS_LOST: GenerationLog.STATUS_LOST,
    }[take.status])
    params = {"take": take.uid, "mode": take.mode, **(take.effective or {})}
    params.update(kw.pop("params", {}))
    return GenerationLog.objects.create(
        user=take.user, kind=take.kind, source=GenerationLog.SOURCE_VSTUDIO, model=take.model_ref,
        status=status, provider_id=take.provider_id, polling_url=take.polling_url,
        prompt=take.serialized_prompt, params=params, credits_planned=take.credits_reserved,
        credits_charged=take.credits_charged,
        needs_review=kw.pop("needs_review", take.status == Take.STATUS_LOST), **kw)


def make_take(shot: Shot | None = None, *, status: str = Take.STATUS_QUEUED,
              credits: int = 150, genlog: bool | dict = False, **kw) -> Take:
    """Дубль в нужном состоянии с согласованными деньгами.

    genlog=True (или dict с полями записи) — создать и привязать запись журнала.
    """
    shot = shot or make_shot()
    if "charge_state" not in kw:
        if status in TAKE_OPEN:
            kw["charge_state"] = Take.CHARGE_RESERVED
        elif status == Take.STATUS_DONE:
            kw["charge_state"] = Take.CHARGE_CHARGED
        else:
            kw["charge_state"] = Take.CHARGE_RELEASED
    if kw["charge_state"] == Take.CHARGE_CHARGED:
        kw.setdefault("credits_charged", credits)
    if status not in (Take.STATUS_QUEUED, Take.STATUS_CANCELED):
        kw.setdefault("provider_id", f"gen-vid-{_n()}" if shot.kind == Shot.KIND_VIDEO else "")
        if shot.kind == Shot.KIND_VIDEO:
            kw.setdefault("polling_url", f"https://openrouter.ai/api/v1/videos/{kw['provider_id']}")
    body = {"model": shot.model_ref, "prompt": shot.prompt_text}
    take = Take.objects.create(
        user=shot.user, shot=shot, project=shot.project, kind=shot.kind,
        mode=kw.pop("mode", None) or _default_mode(shot), model_ref=shot.model_ref,
        status=status, serialized_prompt=kw.pop("serialized_prompt", shot.prompt_text),
        request_body=kw.pop("request_body", body),
        effective=kw.pop("effective", {"duration": 5, "resolution": "720p", "aspect_ratio": "16:9",
                                       "generate_audio": True}
                         if shot.kind == Shot.KIND_VIDEO else {"aspect_ratio": "auto"}),
        credits_quoted=kw.pop("credits_quoted", credits),
        credits_reserved=kw.pop("credits_reserved", credits),
        **kw)
    if genlog:
        entry = make_genlog(take, **(genlog if isinstance(genlog, dict) else {}))
        Take.objects.filter(pk=take.pk).update(genlog=entry)
        take.genlog = entry
    return take
