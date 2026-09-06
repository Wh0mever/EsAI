# -*- coding: utf-8 -*-
"""Раунд 2: гонка двойной доставки готового ролика.

Статус задачи становится done раньше, чем ядро успевает отдать ролик Telegram.
Бот в этот момент опрашивает задачу и, не увидев отметки, отправляет видео сам —
человек получает его дважды. Отметка теперь означает «ядро уже отправляет» и
снимается, только если Telegram отказал.

Сеть не трогаем: Telegram подменён заглушкой. Кэш свой (LocMem) — прогон в
боевом контейнере однажды положил тестовые данные в общий Redis.
"""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings

from .models import AiChatSession, GenerationJob

TEST_CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                           "LOCATION": "notify-race-tests"}}


@override_settings(CACHES=TEST_CACHES, TELEGRAM_NOTIFY_ENABLED=True,
                   TELEGRAM_PRODUCT_BOT_TOKEN="1:x", SITE_BASE_URL="https://esai.kg")
class NotifyRaceTests(TestCase):
    def setUp(self):
        from botapi.models import TelegramChat

        cache.clear()
        User = get_user_model()
        self.user = User.objects.create_user(email="race@example.com", password="x")
        self.session = AiChatSession.objects.create(user=self.user, title="t")
        TelegramChat.objects.create(user=self.user, telegram_id=91, chat_id=91)

    def _done_job(self):
        return GenerationJob.objects.create(
            user=self.user, session=self.session, need_credits=20, notify="telegram",
            status=GenerationJob.STATUS_DONE,
            params={"model": "test/video", "message": "кот", "lang": "ru"},
            result={"message": {"attachments": [{"type": "video", "url": "/media/v.mp4"}]},
                    "tokens_charged": 20, "balance_tokens": 80})

    def test_mark_is_visible_before_telegram_answers(self):
        """Пока ядро ждёт Telegram, бот уже должен видеть отметку.

        Именно в этот промежуток бот и опрашивал задачу: раньше он читал
        notified=False и слал ролик вторым.
        """
        from .tasks import _notify_job_result

        job = self._done_job()
        seen = {}

        def spy(method, **kwargs):
            # Читаем из базы, а не из объекта в памяти: бот ходит отдельным
            # запросом и видит ровно то, что записано.
            seen["notified_at"] = GenerationJob.objects.get(pk=job.pk).notified_at
            return {}

        with patch("botapi.telegram.tg_api", side_effect=spy):
            _notify_job_result(job)

        self.assertIsNotNone(seen.get("notified_at"))
        job.refresh_from_db()
        self.assertIsNotNone(job.notified_at)
        self.assertTrue(job.public()["notified"])

    def test_mark_is_removed_when_telegram_refuses(self):
        """Отказ Telegram возвращает доставку боту — иначе ролик пропадёт."""
        from botapi.telegram import TelegramError

        from .tasks import _notify_job_result

        job = self._done_job()
        with patch("botapi.telegram.tg_api",
                   side_effect=TelegramError("chat not found", code=400)):
            _notify_job_result(job)

        job.refresh_from_db()
        self.assertIsNone(job.notified_at)
        self.assertFalse(job.public()["notified"])

    def test_mark_is_removed_on_unexpected_error(self):
        """Любой сбой отправки — тоже «ядро не доставило»."""
        from .tasks import _notify_job_result

        job = self._done_job()
        with patch("botapi.telegram.tg_api", side_effect=RuntimeError("boom")):
            _notify_job_result(job)

        job.refresh_from_db()
        self.assertIsNone(job.notified_at)

    def test_no_mark_without_telegram_chat(self):
        """Чата нет — отправлять некому, и притворяться отправившим нельзя."""
        from botapi.models import TelegramChat

        from .tasks import _notify_job_result

        TelegramChat.objects.all().delete()
        job = self._done_job()
        with patch("botapi.telegram.tg_api") as api:
            _notify_job_result(job)

        api.assert_not_called()
        job.refresh_from_db()
        self.assertIsNone(job.notified_at)

    def test_failed_job_notice_also_marks(self):
        """Сообщение «видео не получилось» тоже дублировалось — метим и его."""
        from .tasks import _notify_job_result

        job = self._done_job()
        job.status = GenerationJob.STATUS_FAILED
        job.result = {"balance_tokens": 80}
        job.save(update_fields=["status", "result"])
        seen = {}

        def spy(method, **kwargs):
            seen["notified_at"] = GenerationJob.objects.get(pk=job.pk).notified_at
            return {}

        with patch("botapi.telegram.tg_api", side_effect=spy):
            _notify_job_result(job)

        self.assertIsNotNone(seen.get("notified_at"))

    def test_link_is_sent_when_telegram_refuses_the_video(self):
        """Отказ на самом ролике не должен оставлять человека ни с чем.

        Отметка стоит с начала отправки, и бот по ней уже ушёл: снять её —
        значит потерять оплаченный результат. Поэтому запасной путь свой —
        ссылка сообщением, как в bot deliver(). Отметка остаётся: результат
        доставлен, дублировать нечего.
        """
        from botapi.telegram import TelegramError

        from .tasks import _notify_job_result

        job = self._done_job()
        calls = []

        def spy(method, **kwargs):
            calls.append((method, kwargs))
            if method == "sendVideo":
                # Так Telegram отвечает на ролик тяжелее 20 МБ по ссылке.
                raise TelegramError("failed to get HTTP URL content", code=400)
            return {}

        with patch("botapi.telegram.tg_api", side_effect=spy):
            _notify_job_result(job)

        self.assertEqual([m for m, _ in calls], ["sendVideo", "sendMessage"])
        self.assertIn("https://esai.kg/media/v.mp4", calls[1][1]["text"])
        job.refresh_from_db()
        self.assertIsNotNone(job.notified_at)

    def test_mark_is_removed_when_even_the_link_fails(self):
        """Не прошло вообще ничего — отдаём доставку боту и оставляем след."""
        from botapi.telegram import TelegramError

        from .tasks import _notify_job_result

        job = self._done_job()
        with patch("botapi.telegram.tg_api",
                   side_effect=TelegramError("failed to get HTTP URL content", code=400)):
            _notify_job_result(job)

        job.refresh_from_db()
        self.assertIsNone(job.notified_at)
