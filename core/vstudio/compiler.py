"""Компилятор запроса видеостудии (спецификация §4.4–4.7).

Одна чистая функция compile(...) превращает то, что видит человек (документ с
@-тегами, лоток фото, параметры панели), в тело запроса к OpenRouter под
конкретную модель. Её вызывают и quote (цена на кнопке + подсказки), и запуск:
цена и то, что уйдёт провайдеру, не могут разойтись.

Правила, ради которых модуль существует:
- frame_images и input_references НИКОГДА не уходят в одном теле: провайдер
  молча выбрал бы кадры и выкинул оплаченные референсы;
- текст не обрезается нигде: длинный — предупреждение или блок с объяснением;
- пропорция только явная: «кинематографичный» в тексте не превращается в 21:9,
  а лишь предлагается кнопкой;
- выключенное человеком не отправляется и не оплачивается.

Без ORM-записей и без сети: на вход AssetView и ResolvedInput.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from fractions import Fraction

from . import prompt_doc as pd
from .caps import FRAME_FIRST, FRAME_LAST, KIND_IMAGE, KIND_VIDEO, Caps
from .caps import defaults as caps_defaults

SLOT_REFERENCE = pd.SLOT_REFERENCE
MAX_INPUTS = 16
ROLE_MAX = 60
NEGATIVE_MAX = 2000
SEED_MAX = 2**32 - 1
SCRIPT_MIN_CHARS = 1500
SCRIPT_MIN_SIGNS = 2
CYRILLIC_SHARE = 0.30
# Эвристики текста (сценарий, язык, пропорция) смотрят только начало: подсказка
# от этого не хуже, а время разбора не растёт с длиной вставки.
HEURISTIC_SCAN_CHARS = 8000

MODE_T2V, MODE_I2V, MODE_FLF2V, MODE_R2V, MODE_R2V_PIN = "t2v", "i2v", "flf2v", "r2v", "r2v_pin"
MODE_T2I, MODE_I2I = "t2i", "i2i"

LEVEL_OK, LEVEL_SOFT, LEVEL_HARD = "ok", "soft", "hard"

# ---------------------------------------------------------------- ошибки и предупреждения (§4.7)

BLOCKING = frozenset({
    "prompt_empty", "prompt_too_long", "prompt_doc_invalid", "mention_not_attached",
    "asset_not_found", "asset_not_ready", "asset_failed", "refs_not_supported", "too_many_refs",
    "frames_not_supported", "last_frame_not_supported", "last_frame_with_refs",
    "frames_refs_conflict", "ref_too_small", "ref_bad_aspect", "video_refs_unsupported",
    "invalid_param", "model_unavailable", "too_many_inputs", "service_misconfigured",
})
WARNINGS = frozenset({
    "prompt_long", "looks_like_script", "ref_unmentioned", "tag_unknown", "frame_soft_pin",
    "duration_forced", "faces_risk", "aspect_in_text", "lang_hint", "input_excluded",
})

MESSAGES = {
    # Блокирующие (422 blocked).
    "prompt_empty": "Опишите, что должно происходить в кадре.",
    "prompt_too_long": ("Текст длиннее, чем принимает {model}: {chars} из {hard} символов. "
                        "Сократите его или нажмите «Сжать с ИИ»."),
    "prompt_doc_invalid": "Не удалось прочитать текст запроса. Обновите страницу и попробуйте снова.",
    "mention_not_attached": ("В тексте есть тег фото, которого нет в запросе. "
                             "Уберите красный тег или добавьте фото заново."),
    "asset_not_found": "Фото не найдено — возможно, оно удалено.",
    "asset_not_ready": "{subject} ещё создаётся — подождите несколько секунд.",
    "asset_failed": "{subject} не получилось — удалите его или создайте заново.",
    "refs_not_supported": ("{model} не умеет работать с фото-референсами. "
                           "Сделайте фото первым кадром или выберите другую модель."),
    "too_many_refs": "{model} принимает не больше {max} фото-референсов, а у вас {n}.",
    "frames_not_supported": "{model} не умеет начинать видео с вашего кадра.",
    "last_frame_not_supported": "{model} не умеет заканчивать видео заданным кадром.",
    "last_frame_with_refs": ("С фото-референсами {model} не может закончить видео заданным кадром. "
                             "Уберите последний кадр или референсы."),
    "frames_refs_conflict": ("{model} не может одновременно использовать кадры и фото-референсы. "
                             "Выберите что-то одно."),
    "ref_too_small": "{subject} слишком маленькое для {model}: нужно от {min} px по короткой стороне.",
    "ref_bad_aspect": ("{subject} слишком вытянутое для {model}: "
                       "подойдёт соотношение сторон от {lo_text} до {hi_text}."),
    "video_refs_unsupported": ("Видео и звук как референсы появятся позже. "
                               "Сейчас можно добавить только фото."),
    "invalid_param": "{model} не поддерживает {field_text} = {value_text}. Доступно: {allowed_text}.",
    "model_unavailable": "Эта модель сейчас недоступна. Выберите другую.",
    "too_many_inputs": "Слишком много материалов в одном запросе (максимум {max}).",
    "service_misconfigured": "Студия временно недоступна. Мы уже чиним.",
    # Предупреждения (запуск разрешён).
    "prompt_long": ("{model} лучше всего понимает до ~{soft} слов, а у вас {words}. "
                    "Детали в конце могут потеряться — попробуйте «Сжать с ИИ»."),
    "looks_like_script": ("Похоже на сценарий из нескольких сцен. Один ролик покажет только одну "
                          "сцену — лучше снять сцены по отдельности."),
    "ref_unmentioned": ("{subject} прикреплено, но не упомянуто в тексте — модель решит сама, "
                        "как его использовать. Лучше написать, кто или что это."),
    "tag_unknown": "«{text}» похоже на тег, но такого фото в запросе нет.",
    "frame_soft_pin": "Первый кадр отправим как Image {k}: начало видео будет похожим, но не точь-в-точь.",
    "duration_forced": "С фото-референсами {model} снимает только {value} с — цена пересчитана.",
    "faces_risk": ("{model} не принимает фото реальных людей. Если на фото человек, генерация "
                   "может не пройти — кредиты тогда не спишутся."),
    "aspect_in_text": "В тексте указано {value}, а в настройках — {current_text}. Применить {value}?",
    "lang_hint": "{model} лучше понимает английский. Русский текст тоже сработает, но точность ниже.",
    "input_excluded": "{subject} не учитывается и не оплачивается.",
}
# «@Первый кадр слишком маленькое» — не по-русски; у кадров свой род.
FRAME_MESSAGES = {
    "asset_failed": "{subject} не получился — удалите его или создайте заново.",
    "ref_too_small": "{subject} слишком маленький для {model}: нужно от {min} px по короткой стороне.",
    "ref_bad_aspect": ("{subject} слишком вытянутый для {model}: "
                       "подойдёт соотношение сторон от {lo_text} до {hi_text}."),
}
FIELD_NAMES = {
    "duration": "длительность", "resolution": "качество", "aspect_ratio": "пропорции",
    "seed": "seed", "negative_prompt": "негатив", "role": "роль", "slot": "слот",
    "generate_audio": "звук",
}
SUBJECT_FRAMES = {FRAME_FIRST: "@Первый кадр", FRAME_LAST: "@Последний кадр"}


class _Blank(dict):
    def __missing__(self, key):
        return ""


def issue(code: str, *, fix: dict | None = None, fixes: list | None = None,
          fmt: dict | None = None, frame: bool = False, **params) -> dict:
    """Запись ошибки или предупреждения: {code, params, message, fix?, fixes?}.

    params уходят фронту (он переводит по code, `vstudio:errors.<code>`), русский
    message — defaultValue. fmt — значения только для русского текста. fixes —
    все варианты исправления, если их больше одного (fix — основной).
    """
    template = (FRAME_MESSAGES.get(code) if frame else None) or MESSAGES[code]
    values = _Blank({k: v for k, v in params.items()})
    values.update(fmt or {})
    out = {"code": code, "params": params, "message": template.format_map(values)}
    if fix:
        out["fix"] = fix
    if fixes and len(fixes) > 1:
        out["fixes"] = fixes
    return out


# ---------------------------------------------------------------- входы и результат

@dataclass(frozen=True)
class AssetView:
    """Что компилятору нужно знать о материале (снимок строки Asset, без ORM)."""

    uid: str
    kind: str = "image"
    status: str = "ready"
    width: int | None = None
    height: int | None = None
    flags: dict = field(default_factory=dict, hash=False, compare=False)
    file: str = ""
    deleted: bool = False
    # Сверх §4.4: faces_risk смотрит на source=upload, заголовок — на алиас (1.5).
    source: str = "upload"
    label: str = ""

    @classmethod
    def from_asset(cls, asset) -> "AssetView":
        """Снимок vstudio.models.Asset (только чтение полей)."""
        return cls(
            uid=str(asset.uid), kind=str(asset.kind or "image"), status=str(asset.status or "ready"),
            width=asset.width, height=asset.height, flags=dict(asset.flags or {}),
            file=str(asset.file or ""), deleted=asset.deleted_at is not None,
            source=str(asset.source or ""), label=str(getattr(asset, "label", "") or ""),
        )


@dataclass(frozen=True)
class ResolvedInput:
    asset: AssetView
    slot: str
    position: int = 0
    role: str = ""
    included: bool = True


@dataclass
class Compiled:
    kind: str
    model: str
    mode: str = ""
    body: dict = field(default_factory=dict)
    serialized_prompt: str = ""
    prompt_text: str = ""
    labels: dict = field(default_factory=dict)
    used: list = field(default_factory=list)
    dropped: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    billable_images: int = 0
    effective: dict = field(default_factory=dict)
    price_aspect: str | None = None
    meter: dict = field(default_factory=dict)
    # Входы после нормализации: порядок лотка, позиции 0..n-1 в каждом слоте,
    # без повторов (slot, asset). Из них API пишет ShotInput — ограничения
    # vs_input_pos и vs_input_once не сработают.
    inputs: list = field(default_factory=list)
    # Документ после привязки тегов, набранных текстом (prompt_doc.link_tags):
    # его и хранит Shot — ссылки в нём те же, что ушли модели. None — компилятор
    # не дошёл до документа (модель недоступна, документ кривой).
    doc: dict | None = None

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict:
        return {
            "kind": self.kind, "model": self.model, "mode": self.mode, "body": self.body,
            "serialized_prompt": self.serialized_prompt, "prompt_text": self.prompt_text,
            "labels": self.labels, "used": self.used, "dropped": self.dropped,
            "warnings": self.warnings, "errors": self.errors,
            "billable_images": self.billable_images, "effective": self.effective,
            "price_aspect": self.price_aspect, "meter": self.meter, "inputs": self.inputs,
        }


# ---------------------------------------------------------------- помощники

def _clean_role(value) -> str:
    return re.sub(r"\s+", " ", pd.normalize_text(str(value or ""))).strip()


def _normalize_inputs(inputs, errors: list, model: str) -> list[ResolvedInput]:
    """Порядок лотка, позиции 0..n-1 внутри слота, без повторов одного фото в слоте."""
    seen: set[tuple[str, str]] = set()
    by_slot: dict[str, list[ResolvedInput]] = {s: [] for s in pd.SLOTS}
    bad_slots: list[str] = []
    for slot in pd.SLOTS:
        for inp in pd.ordered(list(inputs or []), slot):
            key = (slot, inp.asset.uid)
            if key in seen:
                continue
            seen.add(key)
            by_slot[slot].append(inp)
    for inp in inputs or []:
        if inp.slot not in pd.SLOTS and inp.slot not in bad_slots:
            bad_slots.append(str(inp.slot))
    for slot in bad_slots:
        errors.append(issue("invalid_param", field="slot", value=slot, allowed=list(pd.SLOTS),
                            model=model, fmt=_param_fmt("slot", slot, list(pd.SLOTS))))
    out: list[ResolvedInput] = []
    for slot in pd.SLOTS:
        for pos, inp in enumerate(by_slot[slot]):
            out.append(ResolvedInput(asset=inp.asset, slot=slot, position=pos,
                                     role=_clean_role(inp.role), included=bool(inp.included)))
    return out


def _param_fmt(field_name: str, value, allowed) -> dict:
    if isinstance(allowed, (list, tuple)):
        allowed_text = ", ".join(str(a) for a in allowed) if allowed else "—"
    else:
        allowed_text = str(allowed)
    return {"field_text": FIELD_NAMES.get(field_name, field_name),
            "value_text": "пусто" if value in (None, "") else str(value),
            "allowed_text": allowed_text}


def _ratio_text(value: float) -> str:
    fr = Fraction(value).limit_denominator(10)
    return f"{fr.numerator}:{fr.denominator}"


def _aspect_value(a: AssetView) -> float | None:
    if a.width and a.height:
        return a.width / a.height
    return None


def _nearest_aspect(ratio: float, allowed) -> str | None:
    best, best_d = None, None
    for a in allowed:
        m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)\s*", str(a))
        if not m or float(m.group(2)) == 0:
            continue
        d = abs(math.log(float(m.group(1)) / float(m.group(2))) - math.log(ratio))
        if best_d is None or d < best_d:
            best, best_d = str(a), d
    return best


def _cap_first(s: str) -> str:
    return s[:1].upper() + s[1:] if s else s


# Отступ в начале строки — только пробелы и табы, не \s: \s ловит и \n, и с
# MULTILINE каждое начало строки пересканировало бы все переводы строк после
# него. «a» + 20 000 × «\n» считалось 13 секунд и держало GIL — один гость
# с quote/ клал процесс gunicorn целиком (ReDoS).
_SCENE_RE = re.compile(r"^[ \t]*(?:сцена|scene|кадр|shot)[ \t]*\d+", re.IGNORECASE | re.MULTILINE)
_TIMECODE_RE = re.compile(r"(?<!\d)\d{1,2}:\d{2}(?!\d)")
_NUMBERED_RE = re.compile(r"^[ \t]*\d{1,2}[.)]\s+\S", re.MULTILINE)
_SEQUENCE_RE = re.compile(r"(?<![\w])(?:затем|потом|после этого|then)(?![\w])", re.IGNORECASE)
_LETTER_RE = re.compile(r"[^\W\d_]", re.UNICODE)
_CYR_RE = re.compile(r"[Ѐ-ӿ]")


def script_signs(text: str) -> int:
    """Сколько признаков сценария: «Сцена N», таймкоды, нумерованный список, «затем/потом».

    Каждый вид засчитывается не больше двух раз, слова-связки — один: пара
    «затем» в длинном описании ещё не сценарий.
    """
    text = str(text or "")[:HEURISTIC_SCAN_CHARS]
    return (min(len(_SCENE_RE.findall(text)), 2) + min(len(_TIMECODE_RE.findall(text)), 2)
            + min(len(_NUMBERED_RE.findall(text)), 2) + min(len(_SEQUENCE_RE.findall(text)), 1))


def cyrillic_share(text: str) -> float:
    letters = _LETTER_RE.findall(text)
    if not letters:
        return 0.0
    return sum(1 for ch in letters if _CYR_RE.match(ch)) / len(letters)


def _default_storage_url(name: str) -> str:
    from django.core.files.storage import default_storage

    return default_storage.url(name)


# ---------------------------------------------------------------- компилятор

def compile(caps: Caps | None, kind: str, doc, inputs, params, *, site_base: str,
            inline_refs: bool = False, allow_deleted: bool = False,
            storage_url=None) -> Compiled:
    """Документ + входы + параметры → тело запроса и всё, что показывает quote (§4.4).

    - caps — vstudio.caps.for_model(...) (None → model_unavailable);
    - kind — "video" | "image";
    - doc — prompt_doc v1 (проверяется здесь же);
    - inputs — [ResolvedInput], только материалы ЭТОГО человека (чужие API не находит);
    - params — {duration, resolution, aspect_ratio|"auto", generate_audio, seed, negative_prompt};
    - site_base — settings.SITE_BASE_URL; пусто и не inline_refs → service_misconfigured;
    - inline_refs — dev: URL остаются относительными, submit_take подменит их data-URL;
    - allow_deleted — повтор старого кадра: удалённое фото ещё живёт, пока на него ссылаются;
    - storage_url — name → URL (по умолчанию default_storage.url).

    Ошибки не бросаются, а копятся в .errors: quote показывает их вместе с ценой.
    Если есть хоть одна ошибка, body пустой — запускать такое нельзя.
    """
    model = caps.model if caps else ""
    out = Compiled(kind=kind, model=model)
    errors, warnings = out.errors, out.warnings
    name = caps.name if caps else ""
    params = dict(params or {})

    if caps is None or kind not in (KIND_VIDEO, KIND_IMAGE) or caps.kind != kind:
        errors.append(issue("model_unavailable"))
        return out
    try:
        doc = pd.validate(doc)
    except pd.PromptDocError:
        errors.append(issue("prompt_doc_invalid"))
        return out

    raw_inputs = list(inputs or [])
    if len(raw_inputs) > MAX_INPUTS:
        errors.append(issue("too_many_inputs", max=MAX_INPUTS))
    norm = _normalize_inputs(raw_inputs, errors, name)
    out.inputs = [{"asset": i.asset.uid, "slot": i.slot, "position": i.position, "role": i.role,
                   "included": i.included} for i in norm]

    # Теги, набранные текстом и не ставшие чипами (курсор стоял сразу за тегом
    # при «Создать», телефонная клавиатура, старый клиент), привязываем так же,
    # как вставку (§4.3): модель получит свой тег, а не буквальное «@Image 1»;
    # тег без фото — tag_unknown, «@Видео 1» — video_refs_unsupported.
    linked = pd.link_tags(doc, norm)
    doc = linked.doc
    errors.extend(linked.errors)
    warnings.extend(linked.warnings)
    out.doc = doc
    for i in norm:
        if len(i.role) > ROLE_MAX:
            errors.append(issue("invalid_param", field="role", value=i.role[:80], allowed=f"до {ROLE_MAX} символов",
                                model=name, asset=i.asset.uid,
                                fmt=_param_fmt("role", i.role[:80], f"до {ROLE_MAX} символов")))

    # --- 1. Упоминания и состояние материалов.
    included = [i for i in norm if i.included]
    for i in norm:
        if not i.included:
            out.dropped.append({"asset": i.asset.uid, "slot": i.slot, "reason": "excluded_by_user"})
    if any(i.asset.kind != "image" for i in included):
        errors.append(issue("video_refs_unsupported"))
    refs = [i for i in included if i.slot == SLOT_REFERENCE and i.asset.kind == "image"]
    firsts = [i for i in included if i.slot == FRAME_FIRST and i.asset.kind == "image"]
    lasts = [i for i in included if i.slot == FRAME_LAST and i.asset.kind == "image"]
    first = firsts[0] if firsts else None
    last = lasts[0] if lasts else None
    for extra in firsts[1:] + lasts[1:]:
        # Кадр в слоте один; лишний не отправляем и не оплачиваем.
        out.dropped.append({"asset": extra.asset.uid, "slot": extra.slot, "reason": "duplicate_frame"})

    ref_no = {i.asset.uid: n for n, i in enumerate(refs, start=1)}
    labels: dict[str, str] = {}
    for i in refs:
        labels[i.asset.uid] = f"Image {ref_no[i.asset.uid]}"
    for fr in (first, last):
        if fr is not None and fr.asset.uid not in labels:
            labels[fr.asset.uid] = fr.slot
    out.labels = labels

    def subject(i: ResolvedInput) -> str:
        if i.slot in SUBJECT_FRAMES:
            return SUBJECT_FRAMES[i.slot]
        n = ref_no.get(i.asset.uid)
        return f"@Image {n}" if n else "Выключенное фото"

    def asset_params(i: ResolvedInput) -> dict:
        n = ref_no.get(i.asset.uid) if i.slot == SLOT_REFERENCE else None
        return {"asset": i.asset.uid, "slot": i.slot, "n": n,
                "label": labels.get(i.asset.uid) if i.included else None}

    candidates = refs + [fr for fr in (first, last) if fr is not None]
    for i in candidates:
        a = i.asset
        is_frame = i.slot != SLOT_REFERENCE
        if a.deleted and not allow_deleted:
            errors.append(issue("asset_not_found", **asset_params(i),
                                fix={"action": "exclude_inputs", "assets": [a.uid]}))
        elif a.status == "pending":
            errors.append(issue("asset_not_ready", **asset_params(i), fmt={"subject": subject(i)}))
        elif a.status == "failed":
            errors.append(issue("asset_failed", **asset_params(i), fmt={"subject": subject(i)},
                                frame=is_frame, fix={"action": "exclude_inputs", "assets": [a.uid]}))
        elif not a.file:
            errors.append(issue("asset_not_found", **asset_params(i),
                                fix={"action": "exclude_inputs", "assets": [a.uid]}))

    by_uid: dict[str, list[ResolvedInput]] = {}
    for i in norm:
        by_uid.setdefault(i.asset.uid, []).append(i)
    mentioned = pd.ref_uids(doc)
    for uid in mentioned:
        rows = by_uid.get(uid)
        if not rows:
            errors.append(issue("mention_not_attached", asset=uid))
        elif not any(r.included for r in rows):
            r = rows[0]
            warnings.append(issue("input_excluded", asset=uid, slot=r.slot, n=None,
                                  fmt={"subject": subject(r)}))

    # --- 2. Режим.
    frame_uids_all = [fr.asset.uid for fr in (first, last) if fr is not None]
    ref_uids_all = [i.asset.uid for i in refs]
    pin = False
    if kind == KIND_VIDEO:
        if not refs and first is None and last is None:
            out.mode = MODE_T2V
        elif not refs:
            out.mode = MODE_I2V if (first is not None and last is None) else MODE_FLF2V
            if first is not None and FRAME_FIRST not in caps.frames:
                errors.append(issue("frames_not_supported", model=name,
                                    fix={"action": "exclude_inputs", "assets": frame_uids_all}))
            if last is not None and FRAME_LAST not in caps.frames:
                errors.append(issue("last_frame_not_supported", model=name,
                                    fix={"action": "exclude_inputs", "assets": [last.asset.uid]}))
        elif first is None and last is None:
            out.mode = MODE_R2V
            if not caps.refs_enabled:
                fixes = []
                if FRAME_FIRST in caps.frames:
                    fixes.append({"action": "move_to_first_frame", "asset": refs[0].asset.uid})
                fixes.append({"action": "exclude_inputs", "assets": ref_uids_all})
                errors.append(issue("refs_not_supported", model=name, fix=fixes[0], fixes=fixes))
        else:
            out.mode = MODE_R2V
            if not caps.refs_enabled:
                # Кадр уже стоит, а референсы модель не умеет вовсе — честнее
                # сказать именно это, чем «выберите что-то одно».
                errors.append(issue("refs_not_supported", model=name,
                                    fix={"action": "exclude_inputs", "assets": ref_uids_all}))
            elif caps.frames_with_refs == "soft_pin":
                out.mode = MODE_R2V_PIN
                pin = first is not None
                if last is not None:
                    errors.append(issue("last_frame_with_refs", model=name,
                                        fix={"action": "exclude_inputs", "assets": [last.asset.uid]}))
                if first is None:
                    out.mode = MODE_R2V
            else:
                fixes = [{"action": "use_frames_only", "assets": ref_uids_all},
                         {"action": "use_refs_only", "assets": frame_uids_all}]
                errors.append(issue("frames_refs_conflict", model=name, fix=fixes[0], fixes=fixes))
    else:
        out.mode = MODE_I2I if refs else MODE_T2I
        if first is not None or last is not None:
            errors.append(issue("frames_not_supported", model=name,
                                fix={"action": "exclude_inputs", "assets": frame_uids_all}))
        if refs and not caps.refs_enabled:
            errors.append(issue("refs_not_supported", model=name,
                                fix={"action": "exclude_inputs", "assets": ref_uids_all}))

    # Что реально уйдёт провайдеру (при ошибках — что ушло бы).
    if out.mode in (MODE_R2V, MODE_R2V_PIN, MODE_I2I):
        send_refs = list(refs)
        send_frames: list[ResolvedInput] = []
    elif out.mode in (MODE_I2V, MODE_FLF2V):
        send_refs = []
        send_frames = [fr for fr in (first, last) if fr is not None]
    else:
        send_refs, send_frames = [], []
    pinned = first if pin else None
    pin_k = len(send_refs) + 1 if pinned is not None else None

    # --- 3. Лимиты.
    if send_refs and caps.refs_enabled:
        n_sent = len(send_refs) + (1 if pinned is not None else 0)
        if n_sent > caps.max_image_refs:
            keep = max(0, caps.max_image_refs - (1 if pinned is not None else 0))
            overflow = [i.asset.uid for i in send_refs[keep:]]
            errors.append(issue("too_many_refs", model=name, max=caps.max_image_refs, n=n_sent,
                                fix={"action": "exclude_inputs", "assets": overflow}))
    sent_images = send_refs + send_frames + ([pinned] if pinned is not None else [])
    for i in sent_images:
        a = i.asset
        is_frame = i.slot != SLOT_REFERENCE
        short = min(a.width, a.height) if a.width and a.height else None
        if caps.min_ref_px and short is not None and short < caps.min_ref_px:
            errors.append(issue("ref_too_small", **asset_params(i), model=name, min=caps.min_ref_px,
                                fmt={"subject": subject(i)}, frame=is_frame,
                                fix={"action": "exclude_inputs", "assets": [a.uid]}))
        ratio = _aspect_value(a)
        if caps.ref_aspect_range and ratio is not None:
            lo, hi = caps.ref_aspect_range
            if ratio < lo or ratio > hi:
                errors.append(issue("ref_bad_aspect", **asset_params(i), model=name, lo=lo, hi=hi,
                                    fmt={"subject": subject(i), "lo_text": _ratio_text(lo),
                                         "hi_text": _ratio_text(hi)},
                                    frame=is_frame, fix={"action": "exclude_inputs", "assets": [a.uid]}))
    if caps.rejects_real_faces:
        uploads = [i.asset.uid for i in sent_images if i.asset.source == "upload"]
        if uploads:
            warnings.append(issue("faces_risk", model=name, assets=uploads))

    # --- 4. Параметры.
    human = pd.plain_text(doc)
    effective: dict = {}
    body_params: dict = {}
    requested_ar = params.get("aspect_ratio")
    if requested_ar in (None, "", "auto"):
        chosen_ar = "auto"
    else:
        from ai.aspect import normalize as _norm_aspect

        norm_ar = _norm_aspect(requested_ar)
        if norm_ar and norm_ar in caps.aspect_ratios:
            chosen_ar = norm_ar
        else:
            allowed = list(caps.aspect_ratios) + ["auto"]
            errors.append(issue("invalid_param", model=name, field="aspect_ratio", value=str(requested_ar),
                                allowed=allowed, fix={"action": "set_param", "field": "aspect_ratio",
                                                      "value": "auto"},
                                fmt=_param_fmt("aspect_ratio", requested_ar, allowed)))
            chosen_ar = "auto"

    if kind == KIND_VIDEO:
        dflt = caps_defaults(caps)
        forced = caps.ref_forces_duration if (caps.ref_forces_duration and send_refs) else None
        duration = dflt["duration"]
        raw_d = params.get("duration")
        if raw_d not in (None, ""):
            try:
                duration = int(raw_d)
                valid_d = not isinstance(raw_d, bool) and float(raw_d) == duration and duration > 0
            except (TypeError, ValueError):
                valid_d = False
            if valid_d and caps.durations:
                valid_d = duration in caps.durations
            if not valid_d and forced is None:
                allowed = list(caps.durations)
                nearest = (min(caps.durations, key=lambda d: (abs(d - duration), d))
                           if caps.durations else dflt["duration"])
                errors.append(issue("invalid_param", model=name, field="duration", value=raw_d,
                                    allowed=allowed,
                                    fix={"action": "set_param", "field": "duration", "value": nearest},
                                    fmt=_param_fmt("duration", raw_d, allowed)))
                duration = dflt["duration"]
        if forced is not None:
            if duration != forced:
                warnings.append(issue("duration_forced", model=name, value=forced))
            duration = forced

        resolution = dflt["resolution"]
        raw_r = params.get("resolution")
        if raw_r not in (None, ""):
            low = {r.lower(): r for r in caps.resolutions}
            if str(raw_r).lower() in low:
                resolution = low[str(raw_r).lower()]
            elif not caps.resolutions:
                resolution = str(raw_r)
            else:
                allowed = list(caps.resolutions)
                errors.append(issue("invalid_param", model=name, field="resolution", value=str(raw_r),
                                    allowed=allowed, fix={"action": "set_param", "field": "resolution",
                                                          "value": dflt["resolution"]},
                                    fmt=_param_fmt("resolution", raw_r, allowed)))

        body_params["duration"] = duration
        body_params["resolution"] = resolution
        if chosen_ar != "auto":
            body_params["aspect_ratio"] = chosen_ar
        audio = None
        if caps.audio:
            raw_a = params.get("generate_audio")
            if isinstance(raw_a, str):
                # «false» из формы — это нет, а не непустая строка.
                raw_a = raw_a.strip().lower() in ("1", "true", "yes", "on")
            audio = True if raw_a is None else bool(raw_a)
            body_params["generate_audio"] = audio
        if caps.seed:
            raw_s = params.get("seed")
            if raw_s not in (None, ""):
                ok_seed = isinstance(raw_s, int) and not isinstance(raw_s, bool) and 0 <= raw_s <= SEED_MAX
                if ok_seed:
                    body_params["seed"] = raw_s
                else:
                    errors.append(issue("invalid_param", model=name, field="seed", value=str(raw_s),
                                        allowed=f"0…{SEED_MAX}",
                                        fmt=_param_fmt("seed", raw_s, f"целое от 0 до {SEED_MAX}")))
        negative = pd.normalize_text(str(params.get("negative_prompt") or "")).strip()
        if negative and caps.negative:
            if len(negative) > NEGATIVE_MAX:
                errors.append(issue("invalid_param", model=name, field="negative_prompt",
                                    value=f"{len(negative)} симв.", allowed=f"до {NEGATIVE_MAX} символов",
                                    fmt=_param_fmt("negative_prompt", f"{len(negative)} симв.",
                                                   f"до {NEGATIVE_MAX} символов")))
            else:
                # Верхнеуровневого negative_prompt в /videos нет — только passthrough.
                body_params["provider"] = {"options": {caps.negative_slug: {
                    "parameters": {caps.negative_param: negative}}}}
        effective = {"duration": duration, "resolution": resolution, "aspect_ratio": chosen_ar,
                     "generate_audio": audio}

        if chosen_ar != "auto":
            out.price_aspect = chosen_ar
        else:
            frame_ratio = _aspect_value(first.asset) if first is not None else None
            if frame_ratio and caps.aspect_ratios:
                out.price_aspect = _nearest_aspect(frame_ratio, caps.aspect_ratios)
            if not out.price_aspect:
                from ai.video_cost import default_aspect

                out.price_aspect = default_aspect({"supported_aspect_ratios": list(caps.aspect_ratios)})
    else:
        if chosen_ar != "auto":
            body_params["aspect_ratio"] = chosen_ar
        effective = {"aspect_ratio": chosen_ar}
        out.price_aspect = chosen_ar if chosen_ar != "auto" else None
    out.effective = effective

    # Пропорция из текста только предлагается — скрытых 21:9 в студии нет.
    from ai.aspect import from_prompt as _aspect_from_prompt

    found = _aspect_from_prompt(human[:HEURISTIC_SCAN_CHARS])
    if found and found != chosen_ar and found in caps.aspect_ratios:
        warnings.append(issue("aspect_in_text", value=found, current=chosen_ar,
                              fix={"action": "set_param", "field": "aspect_ratio", "value": found},
                              fmt={"current_text": "авто" if chosen_ar == "auto" else chosen_ar}))

    # --- 5. Сериализация (§4.5).
    send_ref_no = {i.asset.uid: n for n, i in enumerate(send_refs, start=1)}
    send_frame_by_uid = {fr.asset.uid: fr for fr in send_frames}

    def tag(n: int) -> str:
        return caps.mention_template.format(n=n)

    def who(i: ResolvedInput) -> str:
        alias = (i.asset.label or "").strip()
        role = i.role
        if alias and role:
            return f"{alias} ({role})"
        return alias or role

    def render_ref(uid: str) -> str:
        if uid in send_ref_no:
            n = send_ref_no[uid]
            if caps.mention_style == "natural":
                inp = next(i for i in send_refs if i.asset.uid == uid)
                name_ = (inp.asset.label or "").strip() or inp.role
                return f"{name_} (reference image {n})" if name_ else f"(the subject of reference image {n})"
            return tag(n)
        if pinned is not None and uid == pinned.asset.uid:
            return tag(pin_k)
        fr = send_frame_by_uid.get(uid)
        if fr is not None:
            return caps.frame_words[0] if fr.slot == FRAME_FIRST else caps.frame_words[1]
        # Выключенное или не прикреплённое: модели его не показываем, но роль
        # (если человек её задал) оставляем словами — смысл фразы сохранится.
        rows = by_uid.get(uid) or []
        alias = next(((r.asset.label or "").strip() for r in rows if (r.asset.label or "").strip()), "")
        return alias or next((r.role for r in rows if r.role), "")

    lines: list[str] = []
    if pinned is not None:
        lines.append(f"{_cap_first(tag(pin_k))} is the first frame of the video.")
        warnings.append(issue("frame_soft_pin", k=pin_k, asset=pinned.asset.uid))
    if caps.bind_template and caps.mention_style == "indexed":
        for i in send_refs:
            w = who(i)
            if w:
                lines.append(caps.bind_template.format(tag=_cap_first(tag(send_ref_no[i.asset.uid])), who=w))
    text_body = pd.serialize(doc, render_ref)
    out.serialized_prompt = "\n".join(lines + [text_body]) if lines else text_body

    human_labels = dict(labels)
    for i in norm:
        if not i.included and i.slot != SLOT_REFERENCE:
            human_labels.setdefault(i.asset.uid, i.slot)
    out.prompt_text = pd.render_text(doc, human_labels)

    mentioned_set = set(mentioned)
    for i in send_refs:
        if i.asset.uid not in mentioned_set:
            n = send_ref_no[i.asset.uid]
            warnings.append(issue("ref_unmentioned", asset=i.asset.uid, slot=i.slot, n=n,
                                  label=f"Image {n}", fmt={"subject": f"@Image {n}"}))

    # --- 6. Длина. Обрезки нет нигде: только счётчик, предупреждение или блок.
    chars = len(out.serialized_prompt)
    words = len(re.findall(r"\S+", out.serialized_prompt))
    soft, hard = caps.prompt_soft_words, caps.prompt_hard_chars
    level = LEVEL_OK
    if not human.strip():
        errors.append(issue("prompt_empty"))
    if chars > hard:
        level = LEVEL_HARD
        errors.append(issue("prompt_too_long", model=name, chars=chars, hard=hard,
                            fix={"action": "condense"}))
    elif soft and words > soft:
        level = LEVEL_SOFT
    if soft and words > soft:
        warnings.append(issue("prompt_long", model=name, soft=soft, words=words,
                              fix={"action": "condense"}))
    # Текст уже заблокирован длиной — советы про сценарий и язык ему не помогут,
    # а разбор длинной вставки стоит времени.
    if level != LEVEL_HARD:
        if chars > SCRIPT_MIN_CHARS and script_signs(human) >= SCRIPT_MIN_SIGNS:
            warnings.append(issue("looks_like_script"))
        if caps.prompt_lang == "en" and cyrillic_share(human[:HEURISTIC_SCAN_CHARS]) > CYRILLIC_SHARE:
            warnings.append(issue("lang_hint", model=name))
    out.meter = {"chars": chars, "words": words, "soft_words": soft, "hard_chars": hard, "level": level}

    # --- 7. Тело запроса.
    to_url = storage_url or _default_storage_url
    base = str(site_base or "").strip().rstrip("/")
    if sent_images and not base and not inline_refs:
        # Молча уйти в text-to-video нельзя: человек заплатил бы за ролик без своих фото.
        errors.append(issue("service_misconfigured"))

    def url(a: AssetView) -> str:
        u = str(to_url(a.file) or "")
        if u.startswith(("http://", "https://")) or not base:
            return u
        return base + (u if u.startswith("/") else "/" + u)

    body: dict = {"model": caps.model, "prompt": out.serialized_prompt}
    used: list[dict] = []
    if kind == KIND_VIDEO:
        body["duration"] = body_params["duration"]
        body["resolution"] = body_params["resolution"]
        for key in ("aspect_ratio", "generate_audio", "seed"):
            if key in body_params:
                body[key] = body_params[key]
        if out.mode in (MODE_I2V, MODE_FLF2V) and send_frames:
            body["frame_images"] = [
                {"type": "image_url", "image_url": {"url": url(fr.asset)}, "frame_type": fr.slot}
                for fr in send_frames]
            used = [{"asset": fr.asset.uid, "slot": fr.slot, "label": fr.slot} for fr in send_frames]
        elif out.mode in (MODE_R2V, MODE_R2V_PIN) and send_refs:
            items = [(i, f"Image {send_ref_no[i.asset.uid]}") for i in send_refs]
            if pinned is not None:
                items.append((pinned, f"Image {pin_k}"))
            body["input_references"] = [{"type": "image_url", "image_url": {"url": url(i.asset)}}
                                        for i, _ in items]
            used = [{"asset": i.asset.uid, "slot": i.slot, "label": lbl} for i, lbl in items]
        if "provider" in body_params:
            body["provider"] = body_params["provider"]
    else:
        if "aspect_ratio" in body_params:
            body["aspect_ratio"] = body_params["aspect_ratio"]
        if send_refs:
            body["input_references"] = [{"type": "image_url", "image_url": {"url": url(i.asset)}}
                                        for i in send_refs]
            used = [{"asset": i.asset.uid, "slot": i.slot, "label": f"Image {send_ref_no[i.asset.uid]}"}
                    for i in send_refs]
    if "frame_images" in body and "input_references" in body:
        # Недостижимо по построению; если когда-нибудь случится — лучше упасть
        # здесь, чем отправить тело, где провайдер молча выкинет референсы.
        raise AssertionError("frame_images и input_references в одном теле")

    out.used = used
    out.billable_images = len(used)
    out.body = {} if errors else body
    return out


compile_shot = compile

__all__ = [
    "AssetView", "ResolvedInput", "Compiled", "compile", "compile_shot", "issue",
    "MESSAGES", "BLOCKING", "WARNINGS", "MAX_INPUTS", "script_signs", "cyrillic_share",
]
