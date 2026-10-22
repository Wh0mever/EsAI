# -*- coding: utf-8 -*-
"""Сквозные проверки бота: настоящий Dispatcher, имитаторы Telegram и сервера, без сети.

Файлы названы check_*.py, чтобы обычный прогон (pytest tests) их не собирал.
Запуск из bot/: python -m pytest -q tests/e2e/check_selftest.py tests/e2e/check_smoke.py
"""
import logging

import pytest
import pytest_asyncio

from tests.e2e.fakes import Harness


@pytest_asyncio.fixture
async def h(monkeypatch):
    stand = Harness()
    await stand.start(monkeypatch)
    try:
        yield stand
    finally:
        await stand.stop()


@pytest.fixture
def no_errors(caplog):
    """Обработчик, упавший внутри, не должен пройти незамеченным.

    ErrorsMiddleware ловит исключение и отвечает человеку вежливым текстом —
    для пользователя это хорошо, а для проверки означает «тест зелёный, хотя код
    упал». Поэтому после сценария сверяем журнал: записей ERROR быть не должно.
    """
    caplog.set_level(logging.WARNING)
    yield caplog
    bad = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert not bad, "в журнале бота ошибки:\n" + "\n".join(
        f"{r.name}: {r.getMessage()}\n{r.exc_text or ''}" for r in bad)
