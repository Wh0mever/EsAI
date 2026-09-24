"""Документ промпта видеостудии (`prompt_doc` v1, спецификация §4.1–4.3).

Промпт хранится документом со ссылками на asset.uid, а не текстом с «@Image 1»:
номер — это позиция фото в лотке, и после перестановки он меняется. Метка
вычисляется при показе (render_text) и при отправке модели (compiler), в
документ не пишется никогда.

    {"v": 1, "blocks": [[{"t": "text", "v": "Девушка "}, {"t": "ref", "asset": "<32 hex>"}], …]}

Блоки — абзацы, при сериализации их соединяет "\\n". Модуль чистый: без БД и сети.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

DOC_VERSION = 1
MAX_BLOCKS = 200
MAX_NODES_PER_BLOCK = 400
MAX_TEXT_CHARS = 20_000
MAX_REFS = 64

NODE_TEXT = "text"
NODE_REF = "ref"

SLOT_REFERENCE = "reference"
SLOT_FIRST = "first_frame"
SLOT_LAST = "last_frame"
SLOTS = (SLOT_REFERENCE, SLOT_FIRST, SLOT_LAST)

UID_RE = re.compile(r"^[0-9a-f]{32}$")
# Управляющие символы, кроме \n и \t (C0, DEL и C1). \r тоже нельзя: переводы
# строк в документе только "\n", иначе счётчик длины и копирование разъедутся.
_CTRL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")

# Грамматика текстовых тегов (§4.3) — ОДНО выражение с фронтом (lib/vstudio/promptDoc.ts).
# Голое «Image 1» без @ или скобки не распознаётся: это обычный текст английских промптов.
TAG_PATTERN = (r"(?<![\w])(?:@\s?|\[\s*|<\s*)(image|img|photo|фото|изображение|картинка|сүрөт)"
               r"[\s_]?(\d{1,2})(?:\s*[\]>])?")
TAG_RE = re.compile(TAG_PATTERN, re.IGNORECASE | re.UNICODE)
# Видео и звук как референсы — Фаза 1.5; сейчас это ошибка, а не молчаливый текст.
MEDIA_TAG_RE = re.compile(r"(?<![\w])@\s?(video|видео|audio|аудио|звук)[\s_]?\d",
                          re.IGNORECASE | re.UNICODE)
# Чипы кадров копируются как «@Первый кадр» / «@Последний кадр» (render_text).
# Распознаём их обратно, чтобы вставка скопированного текста давала те же чипы.
FRAME_TAG_RE = re.compile(r"(?<![\w])@\s?(первый кадр|последний кадр|first frame|last frame)(?![\w])",
                          re.IGNORECASE | re.UNICODE)
_FRAME_WORDS = {"первый кадр": SLOT_FIRST, "first frame": SLOT_FIRST,
                "последний кадр": SLOT_LAST, "last frame": SLOT_LAST}

# Как метка выглядит в человекочитаемом тексте (prompt_text): латиницей во всех языках.
FRAME_TAGS = {SLOT_FIRST: "@Первый кадр", SLOT_LAST: "@Последний кадр"}
EXCLUDED_TAG = "@Image —"


class PromptDocError(ValueError):
    """Документ не прошёл проверку → 422 prompt_doc_invalid."""

    code = "prompt_doc_invalid"
    message = "Не удалось прочитать текст запроса. Обновите страницу и попробуйте снова."

    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


def _fail(detail: str):
    raise PromptDocError(detail)


def validate(doc) -> dict:
    """Проверить документ по белому списку (§4.1) и вернуть его чистую копию.

    Лишние ключи запрещены везде: документ приходит от клиента, и всё, что мы
    не ждём, — либо ошибка фронта, либо попытка протащить своё в тело запроса.
    """
    if not isinstance(doc, dict):
        _fail("doc is not an object")
    if set(doc) != {"v", "blocks"}:
        _fail(f"doc keys: {sorted(map(str, doc))}")
    v = doc.get("v")
    # True == 1 в питоне, но версия — именно число.
    if type(v) is not int or v != DOC_VERSION:
        _fail(f"unsupported version {v!r}")
    blocks = doc.get("blocks")
    if not isinstance(blocks, list):
        _fail("blocks is not a list")
    if len(blocks) > MAX_BLOCKS:
        _fail(f"too many blocks: {len(blocks)}")

    total_chars = 0
    refs = 0
    out_blocks: list[list[dict]] = []
    for bi, block in enumerate(blocks):
        if not isinstance(block, list):
            _fail(f"block {bi} is not a list")
        if len(block) > MAX_NODES_PER_BLOCK:
            _fail(f"block {bi}: too many nodes ({len(block)})")
        out: list[dict] = []
        for ni, node in enumerate(block):
            if not isinstance(node, dict):
                _fail(f"node {bi}.{ni} is not an object")
            t = node.get("t")
            if t == NODE_TEXT:
                if set(node) != {"t", "v"}:
                    _fail(f"text node {bi}.{ni} keys: {sorted(map(str, node))}")
                text = node.get("v")
                if not isinstance(text, str):
                    _fail(f"text node {bi}.{ni}: v is not a string")
                if _CTRL_RE.search(text):
                    _fail(f"text node {bi}.{ni}: control characters")
                total_chars += len(text)
                out.append({"t": NODE_TEXT, "v": text})
            elif t == NODE_REF:
                if set(node) != {"t", "asset"}:
                    _fail(f"ref node {bi}.{ni} keys: {sorted(map(str, node))}")
                uid = node.get("asset")
                if not isinstance(uid, str) or not UID_RE.match(uid):
                    _fail(f"ref node {bi}.{ni}: bad asset uid")
                refs += 1
                out.append({"t": NODE_REF, "asset": uid})
            else:
                _fail(f"node {bi}.{ni}: unknown type {t!r}")
        out_blocks.append(out)
    if total_chars > MAX_TEXT_CHARS:
        _fail(f"text too long: {total_chars}")
    if refs > MAX_REFS:
        _fail(f"too many refs: {refs}")
    return {"v": DOC_VERSION, "blocks": out_blocks}


def is_valid(doc) -> bool:
    try:
        validate(doc)
    except PromptDocError:
        return False
    return True


def empty_doc() -> dict:
    return {"v": DOC_VERSION, "blocks": [[]]}


# ---------------------------------------------------------------- чтение

def ref_uids(doc: dict) -> list[str]:
    """uid упомянутых материалов в порядке первого появления, без повторов."""
    seen: list[str] = []
    for block in doc.get("blocks") or []:
        for node in block:
            if node.get("t") == NODE_REF and node.get("asset") not in seen:
                seen.append(node["asset"])
    return seen


def plain_text(doc: dict) -> str:
    """Только текст человека, без тегов: для «пусто?», языка и пропорций в тексте."""
    return "\n".join("".join(n.get("v", "") for n in block if n.get("t") == NODE_TEXT)
                     for block in (doc.get("blocks") or []))


def serialize(doc: dict, render_ref) -> str:
    """Собрать текст документа; render_ref(uid) -> str превращает ссылку в текст."""
    lines = []
    for block in doc.get("blocks") or []:
        parts = []
        for node in block:
            if node.get("t") == NODE_TEXT:
                parts.append(node.get("v", ""))
            elif node.get("t") == NODE_REF:
                parts.append(render_ref(node.get("asset")))
        lines.append("".join(parts))
    return "\n".join(lines)


def label_tag(label: str | None) -> str:
    """Метка → тег человекочитаемого текста: «Image 2» → «@Image 2»."""
    if label in FRAME_TAGS:
        return FRAME_TAGS[label]
    if label and label.startswith("Image "):
        return "@" + label
    return EXCLUDED_TAG


def render_text(doc: dict, labels: dict | None = None) -> str:
    """prompt_text (§4.2): документ с метками «@Image N» — для поиска, копирования и админки.

    labels — {uid: "Image 1" | "first_frame" | "last_frame"}. Материал без метки
    (выключен или не прикреплён) показывается как «@Image —», как серый чип.
    """
    labels = labels or {}
    return serialize(doc, lambda uid: label_tag(labels.get(uid)))


# ---------------------------------------------------------------- нумерация

def _attr(obj, name, default=None):
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _input_uid(inp) -> str:
    asset = _attr(inp, "asset")
    if isinstance(asset, str):
        return asset
    return str(_attr(asset, "uid", "") or "")


def _input_kind(inp) -> str:
    asset = _attr(inp, "asset")
    if isinstance(asset, str):
        return str(_attr(inp, "kind", "image") or "image")
    return str(_attr(asset, "kind", "image") or "image")


def _position(inp) -> int:
    try:
        return int(_attr(inp, "position", 0) or 0)
    except (TypeError, ValueError):
        return 0


def ordered(inputs, slot: str) -> list:
    """Входы слота в порядке лотка (position, затем порядок в запросе)."""
    rows = [(i, inp) for i, inp in enumerate(inputs or []) if _attr(inp, "slot") == slot]
    rows.sort(key=lambda r: (_position(r[1]), r[0]))
    return [inp for _, inp in rows]


def number_refs(inputs) -> dict[str, int]:
    """{uid: N} — номер «Image N» (§4.2).

    Номер — позиция среди ВКЛЮЧЁННЫХ референсов-картинок в порядке лотка, с
    единицы. То же правило у фронта (labels.ts), поэтому модель получает ровно
    то, что видит человек. Один и тот же uid дважды не нумеруется.
    """
    out: dict[str, int] = {}
    for inp in ordered(inputs, SLOT_REFERENCE):
        uid = _input_uid(inp)
        if not uid or uid in out:
            continue
        if not bool(_attr(inp, "included", True)) or _input_kind(inp) != "image":
            continue
        out[uid] = len(out) + 1
    return out


def frame_uids(inputs) -> dict[str, str]:
    """{slot: uid} первого включённого кадра каждого слота."""
    out: dict[str, str] = {}
    for slot in (SLOT_FIRST, SLOT_LAST):
        for inp in ordered(inputs, slot):
            if bool(_attr(inp, "included", True)) and _input_uid(inp):
                out[slot] = _input_uid(inp)
                break
    return out


# ---------------------------------------------------------------- из текста

@dataclass
class FromText:
    doc: dict
    warnings: list = field(default_factory=list)
    errors: list = field(default_factory=list)


def normalize_text(text: str) -> str:
    """Переводы строк → "\\n", управляющие символы (кроме \\n и \\t) убираем.

    Вставка из Word и Windows приносит \\r\\n и невидимый мусор — без этого
    документ не прошёл бы validate, хотя человек ничего не нарушал.
    """
    s = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    return _CTRL_RE.sub("", s)


def _split_blocks(text: str) -> list[str]:
    lines = text.split("\n")
    if len(lines) <= MAX_BLOCKS:
        return lines
    # Больше 200 строк: хвост уходит в последний абзац с "\n" внутри — текст
    # при сборке получается тот же, ничего не теряется.
    return lines[: MAX_BLOCKS - 1] + ["\n".join(lines[MAX_BLOCKS - 1:])]


def _push_text(nodes: list, s: str) -> None:
    """Дописать текст, склеивая с предыдущим текстовым узлом."""
    if not s:
        return
    if nodes and nodes[-1]["t"] == NODE_TEXT:
        nodes[-1]["v"] += s
    else:
        nodes.append({"t": NODE_TEXT, "v": s})


def from_text(text: str, inputs=()) -> FromText:
    """Текст с тегами «@Image 1», «[Image 2]», «<IMAGE_3>», «@Фото 1» → prompt_doc (§4.3).

    inputs — входы запроса (ResolvedInput компилятора или словари
    {asset, slot, position, included}). Тег с номером включённого
    референса становится ссылкой; без такого номера остаётся текстом с
    предупреждением tag_unknown. «@Видео 1» / «@Audio 1» — ошибка
    video_refs_unsupported. Больше 20 000 символов → PromptDocError.
    """
    from .compiler import issue  # сообщения §4.7 живут в компиляторе

    text = normalize_text(text)
    if len(text) > MAX_TEXT_CHARS:
        raise PromptDocError(f"text too long: {len(text)}")

    result = FromText(doc=empty_doc())
    if MEDIA_TAG_RE.search(text):
        result.errors.append(issue("video_refs_unsupported"))

    linker = _Linker(inputs, result.warnings)
    blocks: list[list[dict]] = []
    for line in _split_blocks(text):
        nodes: list[dict] = []
        linker.link_line(nodes, line)
        blocks.append(nodes)

    result.doc = {"v": DOC_VERSION, "blocks": blocks or [[]]}
    return result


class _Linker:
    """Теги в тексте → ссылки (одна грамматика для from_text и link_tags).

    Тег с номером включённого референса (или «@Первый кадр» при кадре)
    становится ссылкой; без такого фото остаётся текстом с tag_unknown (одно
    предупреждение на одинаковый текст). Не больше MAX_REFS ссылок на документ.
    """

    def __init__(self, inputs, warnings: list, refs: int = 0):
        from .compiler import issue  # сообщения §4.7 живут в компиляторе

        self._issue = issue
        self.by_number = {n: uid for uid, n in number_refs(inputs).items()}
        self.frames = frame_uids(inputs)
        self.warnings = warnings
        self.unknown_seen: set[str] = set()
        self.refs = refs

    def link_line(self, nodes: list, line: str) -> None:
        """Разобрать одну строку (без переноса) и дописать узлы в nodes."""
        matches = [(m.start(), m.end(), "tag", m) for m in TAG_RE.finditer(line)]
        matches += [(m.start(), m.end(), "frame", m) for m in FRAME_TAG_RE.finditer(line)]
        matches.sort(key=lambda r: (r[0], -r[1]))
        pos = 0
        for start, end, kind, m in matches:
            if start < pos:
                continue  # перекрылось с уже разобранным тегом
            raw = line[start:end]
            if kind == "tag":
                uid = self.by_number.get(int(m.group(2)))
            else:
                uid = self.frames.get(_FRAME_WORDS[m.group(1).lower()])
            _push_text(nodes, line[pos:start])
            if uid and self.refs < MAX_REFS:
                nodes.append({"t": NODE_REF, "asset": uid})
                self.refs += 1
            else:
                _push_text(nodes, raw)
                if not uid and raw not in self.unknown_seen:
                    self.unknown_seen.add(raw)
                    self.warnings.append(self._issue("tag_unknown", text=raw))
            pos = end
        _push_text(nodes, line[pos:])


def link_tags(doc: dict, inputs=()) -> FromText:
    """Теги, оставшиеся ТЕКСТОМ внутри документа, → ссылки (компилятор, §4.3).

    Редактор меняет набранный тег на чип, только когда тег «дописан», — тег,
    за которым ещё стоял курсор при нажатии «Создать», уходил текстом: модель
    получала буквальное «@Image 1» вместо своего тега, а человек видел
    «прикреплено, но не упомянуто». Теперь сервер сам привязывает такие теги,
    как при вставке текста (from_text): с фото — ссылка, без фото — tag_unknown,
    «@Видео 1» — ошибка video_refs_unsupported.

    doc — уже проверенный validate(). Возвращает FromText с новым документом;
    если привязывать нечего, документ тот же по содержанию.
    """
    from .compiler import issue

    result = FromText(doc=doc)
    existing = sum(1 for block in doc.get("blocks") or [] for n in block if n.get("t") == NODE_REF)
    linker = _Linker(inputs, result.warnings, refs=existing)
    media = False
    blocks: list[list[dict]] = []
    for block in doc.get("blocks") or []:
        nodes: list[dict] = []
        for node in block:
            if node.get("t") != NODE_TEXT:
                nodes.append(dict(node))
                continue
            text = node.get("v", "")
            if not media and MEDIA_TAG_RE.search(text):
                media = True
            # Перенос внутри абзаца — граница тега, как между строками в from_text.
            for i, line in enumerate(text.split("\n")):
                if i:
                    _push_text(nodes, "\n")
                linker.link_line(nodes, line)
        blocks.append(nodes)
    if media:
        result.errors.append(issue("video_refs_unsupported"))
    result.doc = {"v": DOC_VERSION, "blocks": blocks or [[]]}
    return result


__all__ = [
    "DOC_VERSION", "MAX_BLOCKS", "MAX_NODES_PER_BLOCK", "MAX_TEXT_CHARS", "MAX_REFS",
    "TAG_PATTERN", "TAG_RE", "MEDIA_TAG_RE", "FRAME_TAG_RE", "PromptDocError", "FromText",
    "validate", "is_valid", "empty_doc", "ref_uids", "plain_text", "serialize", "label_tag",
    "render_text", "number_refs", "frame_uids", "ordered", "normalize_text", "from_text",
    "link_tags",
]
