"""«Сжать с ИИ» (спецификация §4.8): короткая версия длинного промпта с целыми тегами.

Главная жалоба клиента — длинные промпты: 2–4 тысячи символов на одну сцену,
а Seedance уверенно понимает ~150 слов, остальное додумывает. Кнопка просит
дешёвую текстовую модель (VSTUDIO_ASSIST_MODEL) переписать текст в одну сцену
под лимит выбранной модели. Ничего не меняется без согласия человека: ответ
показывается диалогом «было/стало».

Как не потерять фото. Узлы-ссылки документа модель не видит: вместо них в
текст встают плейсхолдеры ⟦1⟧, ⟦2⟧… (номер — по материалу, в порядке первого
упоминания). В ответе каждый должен стоять РОВНО один раз: пропавший тег — фото
выпало из промпта (оплачено, но не упомянуто), лишний или выдуманный — чужое
место в тексте. Не сошлось — одна повторная попытка с объяснением, что не так,
потом отказ condense_failed. Фото, упомянутое в исходнике дважды, в сжатом
тексте упоминается один раз (дальше — «она», «он»): для привязки этого хватает.

Лимиты считает тот же компилятор, что и счётчик под полем: «было/стало» в
диалоге совпадают с числами, которые человек видит в композере, а бюджет для
модели учитывает, во что превратятся теги («[Image 1]», «героиня (reference
image 1)») и строки привязки ролей.

Модуль не пишет в БД; сеть — только запрос к OpenRouter (_ask).
"""
from __future__ import annotations

import json
import logging
import re
import time
from collections import Counter
from dataclasses import dataclass, field

import requests
from django.conf import settings

from . import compiler
from . import prompt_doc as pd
from .caps import KIND_VIDEO

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "google/gemini-2.5-flash"
# (connect, read) одного вызова — §4.8; обе попытки вместе — не дольше DEADLINE_S.
TIMEOUT = (10, 30)
DEADLINE_S = 60.0
MIN_RETRY_S = 10.0
MAX_ATTEMPTS = 2
TEMPERATURE = 0.3
# С запасом: у Gemini 2.5 размышления тоже едят max_tokens, а ответ — до ~1500 символов.
MAX_TOKENS = 2000

# У картинок мягкого лимита слов нет — сжимаем до разумной одной картинки.
DEFAULT_TARGET_WORDS = 120
MIN_TARGET_WORDS = 25
# Грубая длина слова с пробелом в русском тексте: чтобы лимит слов не противоречил
# лимиту символов (у Runway и Hailuo 2.3 жёсткий потолок 1000–2000 символов).
CHARS_PER_WORD = 7
HARD_SHARE = 0.9  # от жёсткого лимита — запас на неточное следование лимиту

PH_OPEN, PH_CLOSE = "⟦", "⟧"
# Похожие скобки 〚〛 модели иногда подставляют сами — принимаем их тоже.
# «@» прямо перед плейсхолдером — привычка из тегов «@Image 1»: убираем,
# иначе в тексте рядом с чипом остался бы лишний «@».
_PH_RE = re.compile(r"(?:@\s?)?[⟦〚]\s*(\d{1,3})\s*[⟧〛]")
_BRACKET_RE = re.compile(r"[⟦⟧〚〛]")
_WS_RE = re.compile(r"[ \t\u00a0]+")
_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)
_KY_RE = re.compile(r"[ңөүҢӨҮ]")
_LATIN_RE = re.compile(r"[A-Za-z]")
_LETTER_RE = re.compile(r"[^\W\d_]", re.UNICODE)

LANG_NAMES = {"ru": "Russian", "ky": "Kyrgyz", "en": "English"}

# Причины отказа (поле reason в 422 condense_failed — для логов и отладки фронта).
REASON_EMPTY = "empty"
REASON_ALREADY_SHORT = "already_short"
REASON_PROVIDER = "provider"
REASON_BAD_ANSWER = "bad_answer"
REASON_PLACEHOLDERS = "placeholders"
REASON_TOO_LONG = "too_long"
REASON_NOT_SHORTER = "not_shorter"

MESSAGE_FAILED = "Не получилось сжать текст. Попробуйте ещё раз или сократите вручную."
MESSAGES = {
    REASON_EMPTY: "Сжимать нечего — сначала опишите, что должно происходить в кадре.",
    REASON_ALREADY_SHORT: "Текст уже укладывается в лимит модели — сжимать нечего.",
    REASON_PROVIDER: ("Помощник сейчас не отвечает. Попробуйте ещё раз через минуту "
                      "или сократите текст вручную."),
}


class CondenseError(Exception):
    """Сжать не вышло → 422 condense_failed. message — русский текст для человека."""

    code = "condense_failed"

    def __init__(self, reason: str, detail: str = "", *, attempts: int = 0):
        self.reason = reason
        self.detail = detail
        self.attempts = attempts
        self.message = MESSAGES.get(reason, MESSAGE_FAILED)
        super().__init__(f"{reason}: {detail}" if detail else reason)


class _ProviderError(Exception):
    """Модель не ответила (сеть, таймаут, HTTP, нет ключа) — повтор не поможет сразу."""


class _Rejected(Exception):
    """Модель ответила, но ответ не годится. problems — по-английски, для повторной просьбы."""

    def __init__(self, reason: str, problems: list[str]):
        self.reason = reason
        self.problems = problems
        super().__init__("; ".join(problems))


# ---------------------------------------------------------------- плейсхолдеры

@dataclass
class Placeheld:
    """Документ как текст для модели: ссылки заменены на ⟦n⟧."""

    text: str
    uids: list[str] = field(default_factory=list)   # uids[n-1] — материал ⟦n⟧
    counts: dict = field(default_factory=dict)      # n → сколько раз стоит в исходнике

    @property
    def size(self) -> int:
        return len(self.uids)


def placeholder(n: int) -> str:
    return f"{PH_OPEN}{n}{PH_CLOSE}"


def to_placeholders(doc: dict) -> Placeheld:
    """prompt_doc → текст с ⟦n⟧. Одинаковый материал — один номер.

    Свои ⟦⟧ в тексте человека превращаем в обычные [ ]: иначе проверка не
    отличила бы его скобки от наших плейсхолдеров.
    """
    numbers: dict[str, int] = {}
    counts: Counter = Counter()
    lines = []
    for block in doc.get("blocks") or []:
        parts = []
        for node in block:
            if node.get("t") == pd.NODE_TEXT:
                parts.append(_BRACKET_RE.sub(lambda m: "[" if m.group(0) in "⟦〚" else "]", node.get("v", "")))
            elif node.get("t") == pd.NODE_REF:
                uid = node.get("asset")
                if uid not in numbers:
                    numbers[uid] = len(numbers) + 1
                counts[numbers[uid]] += 1
                parts.append(placeholder(numbers[uid]))
        lines.append("".join(parts))
    uids = [uid for uid, _ in sorted(numbers.items(), key=lambda kv: kv[1])]
    return Placeheld(text="\n".join(lines), uids=uids, counts=dict(counts))


def check_placeholders(text: str, size: int) -> list[str]:
    """Что не так с плейсхолдерами ответа (по-английски — это уйдёт модели). [] — всё верно."""
    found = Counter(int(m.group(1)) for m in _PH_RE.finditer(text))
    problems = []
    missing = [n for n in range(1, size + 1) if found[n] == 0]
    repeated = [n for n in range(1, size + 1) if found[n] > 1]
    unknown = sorted(n for n in found if not 1 <= n <= size)
    if missing:
        problems.append("missing: " + ", ".join(placeholder(n) for n in missing))
    if repeated:
        problems.append("used more than once: " + ", ".join(
            f"{placeholder(n)} ×{found[n]}" for n in repeated))
    if unknown:
        problems.append("not in the source (do not invent placeholders): "
                        + ", ".join(placeholder(n) for n in unknown))
    if _BRACKET_RE.search(_PH_RE.sub("", text)):
        problems.append(f"a broken placeholder: write them exactly like {placeholder(1)}")
    return problems


def _push_text(nodes: list, s: str) -> None:
    """Дописать текст, склеивая с предыдущим текстовым узлом (как prompt_doc.from_text)."""
    if not s:
        return
    if nodes and nodes[-1]["t"] == pd.NODE_TEXT:
        nodes[-1]["v"] += s
    else:
        nodes.append({"t": pd.NODE_TEXT, "v": s})


def from_placeholders(text: str, uids: list[str]) -> dict:
    """Ответ модели → prompt_doc. Плейсхолдеры уже проверены (check_placeholders).

    Строки — абзацы; пустые строки выкидываем, пробелы схлопываем: сжатый
    текст должен быть компактным, а не с дырами от форматирования модели.
    """
    blocks: list[list[dict]] = []
    for raw_line in pd.normalize_text(text).split("\n"):
        line = _WS_RE.sub(" ", raw_line).strip()
        if not line:
            continue
        nodes: list[dict] = []
        pos = 0
        for m in _PH_RE.finditer(line):
            _push_text(nodes, line[pos:m.start()])
            nodes.append({"t": pd.NODE_REF, "asset": uids[int(m.group(1)) - 1]})
            pos = m.end()
        _push_text(nodes, line[pos:])
        blocks.append(nodes)
    return pd.validate({"v": pd.DOC_VERSION, "blocks": blocks or [[]]})


# ---------------------------------------------------------------- счётчик и бюджет

def _compile(caps, doc: dict, inputs) -> compiler.Compiled:
    # Параметры на текст не влияют (длительность и пропорция в промпт не пишутся),
    # а тело запроса нам не нужно: inline_refs — чтобы не было service_misconfigured.
    return compiler.compile(caps, caps.kind, doc, list(inputs or []), {}, site_base="", inline_refs=True)


def _stats(meter: dict, doc: dict) -> dict:
    if meter:
        return {"chars": int(meter["chars"]), "words": int(meter["words"])}
    text = pd.render_text(doc, {})
    return {"chars": len(text), "words": len(re.findall(r"\S+", text))}


def text_stats(caps, doc: dict, inputs) -> dict:
    """{chars, words} — как счётчик под полем (meter компилятора: сериализованный текст)."""
    return _stats(_compile(caps, doc, inputs).meter, doc)


@dataclass(frozen=True)
class Budget:
    words: int
    chars: int


def budget(caps, held: Placeheld, inputs) -> Budget:
    """Сколько слов и символов просить у модели, чтобы итог уложился в лимиты caps.

    Итоговый промпт длиннее текста модели: каждый ⟦n⟧ станет тегом модели
    («[Image 1]» — два слова, у Veo «(the subject of reference image 1)» — пять),
    сверху добавятся строки ролей и «Image k is the first frame…». Этот
    «накладной» объём меряем компилятором на документе из одних тегов.
    """
    probe_nodes: list[dict] = []
    for uid in held.uids:
        if probe_nodes:
            probe_nodes.append({"t": pd.NODE_TEXT, "v": " "})
        probe_nodes.append({"t": pd.NODE_REF, "asset": uid})
    meter = _compile(caps, {"v": pd.DOC_VERSION, "blocks": [probe_nodes]}, inputs).meter or {}
    bare = " ".join(placeholder(n) for n in range(1, held.size + 1))
    extra_words = max(0, int(meter.get("words") or 0) - held.size)
    extra_chars = max(0, int(meter.get("chars") or 0) - len(bare))

    soft = caps.prompt_soft_words
    words = (soft - extra_words) if soft else DEFAULT_TARGET_WORDS
    chars = int(caps.prompt_hard_chars * HARD_SHARE) - extra_chars
    words = max(MIN_TARGET_WORDS, min(words, chars // CHARS_PER_WORD))
    chars = max(chars, words * 4)
    return Budget(words=int(words), chars=int(chars))


def detect_lang(text: str) -> str | None:
    """Язык исходника: ru | ky | en | None (смешанный или другой — «как в исходнике»)."""
    letters = _LETTER_RE.findall(text or "")
    if not letters:
        return None
    cyr = compiler.cyrillic_share(text)
    if cyr >= 0.5:
        return "ky" if _KY_RE.search(text) else "ru"
    latin = sum(1 for ch in letters if _LATIN_RE.match(ch)) / len(letters)
    if latin >= 0.9:
        return "en"
    return None


# ---------------------------------------------------------------- просьба к модели

def _who(inputs_for_uid) -> str:
    rows = [r for r in inputs_for_uid if r.included] or list(inputs_for_uid)
    for r in rows:
        alias = (r.asset.label or "").strip()
        role = (r.role or "").strip()
        who = f"{alias} ({role})" if alias and role else (alias or role)
        if who:
            return re.sub(r"[\"«»\n]+", " ", who).strip()[:60]
    return ""


def legend(held: Placeheld, inputs, kind: str) -> list[str]:
    """Что стоит за каждым ⟦n⟧: модели проще писать о «героине», чем о безликом номере."""
    by_uid: dict[str, list] = {}
    for i in inputs or []:
        by_uid.setdefault(i.asset.uid, []).append(i)
    out = []
    for n, uid in enumerate(held.uids, start=1):
        rows = by_uid.get(uid) or []
        included = [r for r in rows if r.included]
        slot = (included or rows)[0].slot if rows else None
        if slot == pd.SLOT_FIRST and kind == KIND_VIDEO:
            what = "the first frame of the video"
        elif slot == pd.SLOT_LAST and kind == KIND_VIDEO:
            what = "the last frame of the video"
        elif slot == pd.SLOT_REFERENCE:
            what = "a reference photo"
        else:
            what = "a photo"
        who = _who(rows)
        line = f"{placeholder(n)} — {what}"
        if who:
            line += f', who/what: "{who}"'
        if held.counts.get(n, 0) > 1:
            line += f" (mentioned {held.counts[n]} times in the source — mention it once)"
        out.append(line)
    return out


def system_prompt(kind: str, target: Budget, lang: str | None, size: int) -> str:
    video = kind == KIND_VIDEO
    if video:
        intro = ("You shorten prompts for an AI video generator. The user's prompt is too long for "
                 "the model: details at the end get lost. Rewrite it as ONE short prompt for ONE "
                 "continuous shot.")
        order = "subject → action → place → camera → light and style → sound"
        keep = "who, what they do, where, the camera and the look"
        scenes = ("If the source describes several scenes, keep only the main moment as one "
                  "continuous shot.")
        nothing_new = "people, objects, places, actions, styles or sounds"
    else:
        intro = ("You shorten prompts for an AI image generator. The user's prompt is too long for "
                 "the model. Rewrite it as ONE short prompt for ONE picture.")
        order = "subject → pose or action → place → framing → light and style"
        keep = "who, what they do, where, the framing and the look"
        scenes = "If the source describes several pictures, keep only the main one."
        nothing_new = "people, objects, places, poses or styles"
    language = (f"Write in {LANG_NAMES[lang]}, the language of the source. Never translate."
                if lang in LANG_NAMES else
                "Write in the same language as the source. Never translate.")
    if size:
        names = ", ".join(placeholder(n) for n in range(1, size + 1)) if size <= 3 else \
            f"{placeholder(1)} … {placeholder(size)}"
        tags = (f"- Placeholders ({names}) stand for the user's photos. "
                "Every placeholder listed by the user must appear in your text EXACTLY ONCE, "
                "written exactly as given (same brackets, same number), where that photo is meant. "
                "Never drop, repeat, renumber or invent placeholders, never replace them with words, "
                "and never add \"@\" or brackets of your own around them. If the source mentions "
                "a photo several times, mention it once and use pronouns after that.")
    else:
        tags = f"- The source has no placeholders; never add any {PH_OPEN}…{PH_CLOSE}."
    return "\n".join([
        intro,
        "Rules:",
        f"- At most {target.words} words and at most {target.chars} characters in total "
        "(a placeholder counts as one word). Shorter is fine.",
        f"- Order: {order}.",
        f"- Keep what matters most: {keep}. Drop repetitions, filler and minor details first. "
        + scenes,
        f"- Add nothing that is not in the source: no new {nothing_new}.",
        f"- {language}",
        tags,
        "- Plain text in one paragraph: no line breaks, no markdown, no quotes around the text.",
        'Answer JSON only: {"text": "..."}',
    ])


def user_prompt(held: Placeheld, lines: list[str]) -> str:
    parts = []
    if lines:
        parts.append("Placeholders (each exactly once in your answer):\n" + "\n".join(lines))
    parts.append("Source prompt:\n<<<\n" + held.text + "\n>>>")
    return "\n\n".join(parts)


def retry_prompt(problems: list[str]) -> str:
    return ("Your answer was rejected: " + "; ".join(problems) + ". Fix it and answer again. "
            'JSON only: {"text": "..."}')


# ---------------------------------------------------------------- вызов модели

def assist_model() -> str:
    return str(getattr(settings, "VSTUDIO_ASSIST_MODEL", "") or DEFAULT_MODEL).strip() or DEFAULT_MODEL


def _ask(messages: list[dict], *, read_timeout: float) -> tuple[str, str]:
    """Один вызов chat/completions → (content, finish_reason). Сбои — _ProviderError."""
    from ai.handlers import _openrouter_config

    cfg = _openrouter_config()
    api_key = str(cfg.get("api_key") or "").strip()
    if not api_key:
        raise _ProviderError("нет ключа OpenRouter")
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    if cfg.get("referer"):
        headers["HTTP-Referer"] = cfg["referer"]
    if cfg.get("title"):
        headers["X-Title"] = cfg["title"]
    body = {
        "model": assist_model(),
        "messages": messages,
        "temperature": TEMPERATURE,
        "max_tokens": MAX_TOKENS,
        "response_format": {"type": "json_object"},
    }
    url = f"{str(cfg.get('base_url') or '').rstrip('/')}/chat/completions"
    try:
        r = requests.post(url, json=body, headers=headers, timeout=(TIMEOUT[0], read_timeout))
    except requests.Timeout as exc:
        raise _ProviderError(f"таймаут: {exc}") from exc
    except requests.RequestException as exc:
        raise _ProviderError(f"сеть: {exc}") from exc
    if not 200 <= r.status_code < 300:
        raise _ProviderError(f"http {r.status_code}: {(r.text or '')[:200]}")
    try:
        data = r.json()
    except ValueError as exc:
        raise _ProviderError("ответ OpenRouter не JSON") from exc
    if not isinstance(data, dict) or data.get("error"):
        # OpenRouter иногда отвечает 200 с {"error": …} (нет кредитов, модель недоступна).
        detail = data.get("error") if isinstance(data, dict) else data
        raise _ProviderError(f"ошибка OpenRouter: {str(detail)[:200]}")
    choice = ((data.get("choices") or [{}])[0]) or {}
    content = (choice.get("message") or {}).get("content") or ""
    if isinstance(content, list):  # части ответа [{type:text, text}] у некоторых провайдеров
        content = "".join(str(p.get("text") or "") for p in content if isinstance(p, dict))
    return str(content), str(choice.get("finish_reason") or "")


def parse_answer(content: str, finish_reason: str = "") -> str:
    """{"text": "..."} → текст. Обрезанный или не-JSON ответ — _Rejected."""
    if finish_reason == "length":
        raise _Rejected(REASON_BAD_ANSWER, ["the answer was cut off — make it shorter"])
    raw = _FENCE_RE.sub("", content or "").strip()
    match = re.search(r"\{.*\}", raw, flags=re.S)
    try:
        data = json.loads(match.group(0) if match else raw)
    except ValueError:
        raise _Rejected(REASON_BAD_ANSWER, ['the answer is not JSON of the form {"text": "..."}']) from None
    text = data.get("text") if isinstance(data, dict) else None
    if text is None and isinstance(data, dict):
        text = data.get("prompt")
    if not isinstance(text, str) or not text.strip():
        raise _Rejected(REASON_BAD_ANSWER, ['the "text" field is empty'])
    return text.strip()


# ---------------------------------------------------------------- сжатие

@dataclass
class Condensed:
    doc: dict
    before: dict
    after: dict
    attempts: int
    target: Budget

    def to_json(self) -> dict:
        """Ответ assist/condense/ (§8.2)."""
        return {"prompt_doc": self.doc, "before": dict(self.before), "after": dict(self.after)}


def _accept(caps, content: str, finish_reason: str, held: Placeheld, inputs,
            before: dict) -> tuple[dict, dict]:
    """Проверить ответ модели и собрать документ. Не годится — _Rejected."""
    text = parse_answer(content, finish_reason)
    problems = check_placeholders(text, held.size)
    if problems:
        raise _Rejected(REASON_PLACEHOLDERS, [f"placeholders — {p}" for p in problems])
    if not _LETTER_RE.search(_PH_RE.sub("", text)):
        raise _Rejected(REASON_BAD_ANSWER, ["the text has no words besides placeholders"])
    try:
        doc = from_placeholders(text, held.uids)
    except pd.PromptDocError:
        raise _Rejected(REASON_BAD_ANSWER, ["the text is too long"]) from None
    after = text_stats(caps, doc, inputs)
    hard = caps.prompt_hard_chars
    if after["chars"] > hard:
        raise _Rejected(REASON_TOO_LONG, [f"still too long: about {after['chars']} characters, "
                                          f"the model accepts at most {hard}"])
    if after["words"] >= before["words"] and after["chars"] >= before["chars"]:
        raise _Rejected(REASON_NOT_SHORTER, ["the text is not shorter than the source"])
    return doc, after


def _clock() -> float:
    return time.monotonic()


def condense(caps, doc, inputs=(), lang: str | None = None) -> Condensed:
    """Сжать документ под лимиты модели caps. Бросает CondenseError (→ 422 condense_failed).

    - caps — vstudio.caps.for_model(...) выбранной модели (не None);
    - doc — prompt_doc v1 (PromptDocError, если кривой — вьюха отвечает prompt_doc_invalid);
    - inputs — [compiler.ResolvedInput] материалов человека: подписи ⟦n⟧ и счётчик;
    - lang — ru | ky | en; по умолчанию язык исходника (перевода в Фазе 1 нет).

    Модель зовётся не больше MAX_ATTEMPTS раз и только когда ответ есть, но
    плохой (теги не сошлись, не JSON, не короче, всё ещё длиннее лимита). Сеть,
    таймаут и ошибки HTTP сразу дают отказ: второй вызов удвоил бы ожидание.
    """
    doc = pd.validate(doc)
    inputs = list(inputs or [])
    if not pd.plain_text(doc).strip():
        raise CondenseError(REASON_EMPTY)
    meter = _compile(caps, doc, inputs).meter
    if meter and meter.get("level") == compiler.LEVEL_OK:
        # Кнопка показывается только над лимитом (жёлтый или красный счётчик):
        # звать модель ради текста, который и так уложился, незачем.
        raise CondenseError(REASON_ALREADY_SHORT)
    before = _stats(meter, doc)
    held = to_placeholders(doc)
    target = budget(caps, held, inputs)
    language = lang if lang in LANG_NAMES else detect_lang(pd.plain_text(doc))
    messages = [
        {"role": "system", "content": system_prompt(caps.kind, target, language, held.size)},
        {"role": "user", "content": user_prompt(held, legend(held, inputs, caps.kind))},
    ]

    started = _clock()
    last: _Rejected | None = None
    attempts = 0
    while attempts < MAX_ATTEMPTS:
        read_timeout = float(TIMEOUT[1])
        if attempts:
            left = DEADLINE_S - (_clock() - started)
            if left < MIN_RETRY_S:
                break
            read_timeout = min(read_timeout, left)
        attempts += 1
        try:
            content, finish = _ask(messages, read_timeout=read_timeout)
        except _ProviderError as exc:
            logger.warning("vstudio condense: модель не ответила (model=%s, попытка %s): %s",
                           caps.model, attempts, exc)
            raise CondenseError(REASON_PROVIDER, str(exc), attempts=attempts) from exc
        try:
            new_doc, after = _accept(caps, content, finish, held, inputs, before)
        except _Rejected as rej:
            last = rej
            logger.info("vstudio condense: ответ отклонён (model=%s, попытка %s): %s",
                        caps.model, attempts, rej)
            messages = messages + [{"role": "assistant", "content": content[:4000]},
                                   {"role": "user", "content": retry_prompt(rej.problems)}]
            continue
        logger.debug("vstudio condense ok model=%s attempts=%s words %s→%s chars %s→%s target=%s",
                     caps.model, attempts, before["words"], after["words"], before["chars"],
                     after["chars"], target.words)
        return Condensed(doc=new_doc, before=before, after=after, attempts=attempts, target=target)

    reason = last.reason if last else REASON_BAD_ANSWER
    logger.warning("vstudio condense failed model=%s attempts=%s reason=%s: %s",
                   caps.model, attempts, reason, last)
    raise CondenseError(reason, str(last or ""), attempts=attempts)


__all__ = [
    "CondenseError", "Condensed", "Placeheld", "Budget", "condense", "to_placeholders",
    "from_placeholders", "check_placeholders", "text_stats", "budget", "detect_lang", "legend",
    "system_prompt", "user_prompt", "parse_answer", "assist_model", "placeholder",
    "DEFAULT_MODEL", "TIMEOUT", "MAX_ATTEMPTS", "MESSAGE_FAILED",
]
