# -*- coding: utf-8 -*-
"""Отладка: выгрузить ответ на /start в файл, чтобы посмотреть разметку и кнопки глазами."""
import io


async def test_dump(h, tmp_path):
    out = await h.say("/start")
    path = tmp_path / "dump_start.txt"
    with io.open(path, "w", encoding="utf-8") as f:
        for r in out:
            f.write(f"\n=== {r.kind} ===\n{r.text!r}\n{r.text}\n")
            for b in r.buttons():
                # у кнопок нижней клавиатуры нет ни callback_data, ни url
                action = getattr(b, "callback_data", None) or getattr(b, "url", None) or ""
                f.write(f"   [{b.text}] {action}\n")
    print(f"ответ на /start: {path}")
    assert out, "на /start бот промолчал"
