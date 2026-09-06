# -*- coding: utf-8 -*-
"""Разметка ответа: Telegram не прощает непарных тегов."""
import re

import pytest

from bot.services.tg_format import CHUNK_LIMIT, plain, split_html, to_html


def open_tags(text: str) -> list[str]:
    stack = []
    for match in re.finditer(r"<(/?)(\w+)[^>]*>", text):
        closing, name = match.group(1), match.group(2).lower()
        if closing:
            if stack and stack[-1] == name:
                stack.pop()
            elif name in stack:
                stack.remove(name)
        else:
            stack.append(name)
    return stack


class TestMarkdown:
    def test_bold_and_italic(self):
        assert to_html("**жирный** и *курсив*") == "<b>жирный</b> и <i>курсив</i>"

    def test_code_block_keeps_content(self):
        html = to_html("```python\nprint('привет')\n```")
        assert '<pre><code class="language-python">' in html
        assert "print(&#x27;привет&#x27;)" in html or "print('привет')" in html

    def test_markdown_inside_code_is_not_touched(self):
        """В коде звёздочки — это код, а не разметка."""
        html = to_html("`a ** b`")
        assert "<b>" not in html
        assert "<code>a ** b</code>" == html

    def test_html_in_text_is_escaped(self):
        html = to_html("Тег <script>alert(1)</script> внутри")
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_links(self):
        assert to_html("[сайт](https://esai.kg)") == '<a href="https://esai.kg">сайт</a>'

    def test_headings_become_bold(self):
        assert to_html("## Заголовок") == "<b>Заголовок</b>"

    def test_bullets(self):
        assert to_html("- один\n- два") == "• один\n• два"

    def test_underscores_in_words_survive(self):
        """snake_case не должен превращаться в курсив."""
        assert "<i>" not in to_html("файл my_long_name.py")

    def test_empty(self):
        assert to_html("") == ""


class TestSplit:
    def test_short_text_is_one_piece(self):
        assert split_html("<b>коротко</b>") == ["<b>коротко</b>"]

    def test_long_text_is_split_within_limit(self):
        parts = split_html("абзац. " * 2000)
        assert len(parts) > 1
        assert all(len(part) <= CHUNK_LIMIT for part in parts)

    def test_tags_are_closed_in_every_piece(self):
        """Иначе Telegram отвергнет сообщение целиком."""
        text = "<b>" + ("слово " * 3000) + "</b>"
        parts = split_html(text)
        assert len(parts) > 1
        for part in parts:
            assert open_tags(part) == [], "кусок с незакрытым тегом"

    def test_split_prefers_paragraph_border(self):
        text = ("а" * 3000) + "\n\n" + ("б" * 3000)
        parts = split_html(text)
        assert parts[0].endswith("а")

    def test_nothing_is_lost(self):
        text = "".join(f"строка {i}\n" for i in range(1200))
        joined = "".join(plain(p) for p in split_html(to_html(text)))
        assert "строка 0" in joined and "строка 1199" in joined


class TestPlain:
    def test_tags_removed(self):
        assert plain("<b>жирно</b> и <i>косо</i>") == "жирно и косо"

    def test_entities_restored(self):
        assert plain("&lt;тег&gt;") == "<тег>"
