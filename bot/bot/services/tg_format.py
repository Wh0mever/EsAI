"""Перевод ответа модели в разметку Telegram.

Модель отвечает на Markdown, Telegram понимает свой куцый набор тегов. Если
отдать ему markdown как есть, человек увидит звёздочки и решётки; если отдать
непарные теги — Telegram вернёт ошибку и сообщение не дойдёт вовсе. Поэтому
переводим сами и следим за парностью, в том числе на границе кусков.
"""
from __future__ import annotations

import html
import re

# Telegram принимает только эти теги.
ALLOWED = ("b", "i", "u", "s", "code", "pre", "a", "blockquote")
# Лимит сообщения 4096; оставляем запас на служебные подписи.
CHUNK_LIMIT = 3800

_CODE_BLOCK = re.compile(r"```(\w+)?\n?(.*?)```", re.S)
_INLINE_CODE = re.compile(r"`([^`\n]+)`")
_BOLD = re.compile(r"\*\*(.+?)\*\*", re.S)
_BOLD_ALT = re.compile(r"__(.+?)__", re.S)
_ITALIC = re.compile(r"(?<![\w*])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\w*])")
_ITALIC_ALT = re.compile(r"(?<![\w_])_(?!\s)([^_\n]+?)(?<!\s)_(?![\w_])")
_STRIKE = re.compile(r"~~(.+?)~~", re.S)
_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", re.M)
_BULLET = re.compile(r"^\s{0,3}[-*+]\s+", re.M)
_QUOTE = re.compile(r"^\s{0,3}>\s?(.*)$", re.M)
_HR = re.compile(r"^\s{0,3}([-*_])\s*(?:\1\s*){2,}$", re.M)


def esc(value) -> str:
    """Обезвредить чужой текст перед вставкой в HTML-сообщение.

    Имя человека, название файла, промпт, заголовок ссылки, факт из памяти —
    всё это может содержать «<», и тогда Telegram отвергает СООБЩЕНИЕ ЦЕЛИКОМ
    («can't parse entities»), а человек видит ошибку вместо экрана. Любая
    подстановка не из наших текстов проходит через эту функцию.
    """
    return html.escape(str(value if value is not None else ""), quote=False)


def esc_attr(value) -> str:
    """То же для значения внутри кавычек — например href ссылки."""
    return html.escape(str(value if value is not None else ""), quote=True)


def to_html(text: str) -> str:
    """Markdown → HTML-подмножество Telegram."""
    if not text:
        return ""

    blocks: list[str] = []

    def stash_code(match: re.Match) -> str:
        lang = (match.group(1) or "").strip()
        body = html.escape(match.group(2).rstrip("\n"))
        opening = f'<pre><code class="language-{lang}">' if lang else "<pre>"
        closing = "</code></pre>" if lang else "</pre>"
        blocks.append(f"{opening}{body}{closing}")
        return f"\x00CODE{len(blocks) - 1}\x00"

    def stash_inline(match: re.Match) -> str:
        blocks.append(f"<code>{html.escape(match.group(1))}</code>")
        return f"\x00CODE{len(blocks) - 1}\x00"

    # Код прячем первым: внутри него разметку трогать нельзя.
    text = _CODE_BLOCK.sub(stash_code, text)
    text = _INLINE_CODE.sub(stash_inline, text)

    text = html.escape(text)
    # Адрес НЕ экранируем повторно: строка выше уже прошла html.escape целиком
    # (включая кавычки), и «&» в ней стал «&amp;». Второй проход превратил бы
    # его в «&amp;amp;» — Telegram декодирует ровно один раз, и человек уходил
    # по ссылке с литеральным «&amp;» между параметрами, то есть не туда.
    text = _LINK.sub(lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>', text)
    text = _HEADING.sub(lambda m: f"<b>{m.group(1)}</b>", text)
    text = _HR.sub("—" * 12, text)
    text = _BOLD.sub(lambda m: f"<b>{m.group(1)}</b>", text)
    text = _BOLD_ALT.sub(lambda m: f"<b>{m.group(1)}</b>", text)
    text = _STRIKE.sub(lambda m: f"<s>{m.group(1)}</s>", text)
    text = _ITALIC.sub(lambda m: f"<i>{m.group(1)}</i>", text)
    text = _ITALIC_ALT.sub(lambda m: f"<i>{m.group(1)}</i>", text)
    text = _QUOTE.sub(lambda m: f"<blockquote>{m.group(1)}</blockquote>", text)
    text = _BULLET.sub("• ", text)

    for index, block in enumerate(blocks):
        text = text.replace(f"\x00CODE{index}\x00", block)
    return text.strip()


def _open_tags(chunk: str) -> list[str]:
    """Какие теги остались незакрытыми к концу куска."""
    stack: list[str] = []
    for match in re.finditer(r"<(/?)(\w+)[^>]*>", chunk):
        closing, name = match.group(1), match.group(2).lower()
        if name not in ALLOWED:
            continue
        if closing:
            if stack and stack[-1] == name:
                stack.pop()
            elif name in stack:
                stack.remove(name)
        else:
            stack.append(name)
    return stack


def split_html(text: str, limit: int = CHUNK_LIMIT) -> list[str]:
    """Разрезать длинный ответ, не ломая теги и по возможности — абзацы."""
    if not text:
        return []
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    rest = text
    carry: list[str] = []

    while rest:
        prefix = "".join(f"<{tag}>" for tag in carry)
        room = limit - len(prefix)
        if len(rest) <= room:
            chunks.append(prefix + rest)
            break

        window = rest[:room]
        # Режем по самой «спокойной» границе: абзац, строка, пробел.
        cut = window.rfind("\n\n")
        if cut < room // 3:
            cut = window.rfind("\n")
        if cut < room // 3:
            cut = window.rfind(" ")
        if cut <= 0:
            cut = room
        # Не разрываем тег пополам.
        tag_start = window.rfind("<", 0, cut)
        if tag_start != -1 and ">" not in window[tag_start:cut]:
            cut = tag_start

        head, rest = rest[:cut], rest[cut:].lstrip("\n")
        opened = _open_tags(prefix + head)
        tail = "".join(f"</{tag}>" for tag in reversed(opened))
        chunks.append(prefix + head + tail)
        carry = opened

    return [c for c in chunks if c.strip()]


def plain(text: str) -> str:
    """Совсем без разметки — запасной вариант, если Telegram её не принял."""
    text = re.sub(r"<[^>]+>", "", text or "")
    return html.unescape(text)
