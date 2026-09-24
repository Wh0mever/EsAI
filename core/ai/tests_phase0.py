# -*- coding: utf-8 -*-
"""Фаза 0 перед видеостудией: журнал не ломает транзакцию, пуш ведёт в чат.

1. genlog.start вызывается внутри транзакции запроса (ATOMIC_REQUESTS). Упавшая
   вставка без savepoint помечала её «к откату», и следующий же запрос к базе в
   самой генерации падал с TransactionManagementError (на Postgres — «current
   transaction is aborted»): журнал, который «никогда не роняет генерацию»,
   ронял её.
2. Пуш довоза вёл на /chat/<uid> — такой страницы на сайте нет, человек из
   уведомления попадал на 404 вместо своего ролика.
"""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import DatabaseError, transaction
from django.db.models.sql.compiler import SQLInsertCompiler
from django.test import TestCase

from . import genlog, recovery
from .models import AiChatSession, GenerationLog

_real_insert = SQLInsertCompiler.execute_sql


def _broken_journal_insert(self, *args, **kwargs):
    """Вставка в журнал падает в самой базе, остальные таблицы пишутся как обычно."""
    if self.query.model is GenerationLog:
        raise DatabaseError("value too long for type character varying(8)")
    return _real_insert(self, *args, **kwargs)


class GenlogSavepointTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(email="sp@example.com", password="x")

    def test_failed_insert_does_not_poison_the_request_transaction(self):
        # TestCase уже держит транзакцию — ровно как ATOMIC_REQUESTS в запросе.
        with patch.object(SQLInsertCompiler, "execute_sql", _broken_journal_insert):
            entry = genlog.start(user=self.user, kind="video", model="m", prompt="кот")
        self.assertIsNone(entry.pk)
        self.assertTrue(entry.claim_delivery())  # пустышка, генерация идёт дальше
        # Генерация продолжает ходить в базу в той же транзакции.
        self.assertTrue(get_user_model().objects.filter(pk=self.user.pk).exists())
        AiChatSession.objects.create(user=self.user, title="после сбоя журнала")
        self.assertFalse(transaction.get_connection().needs_rollback)

    def test_failed_insert_inside_explicit_atomic_block(self):
        """Вложенная atomic вызывающего (выдача, списание) тоже остаётся живой."""
        with transaction.atomic():
            with patch.object(SQLInsertCompiler, "execute_sql", _broken_journal_insert):
                genlog.start(user=self.user, kind="image", model="m")
            AiChatSession.objects.create(user=self.user, title="в той же atomic")
        self.assertEqual(AiChatSession.objects.filter(user=self.user).count(), 1)
        self.assertFalse(GenerationLog.objects.exists())

    def test_normal_insert_still_lands(self):
        entry = genlog.start(user=self.user, kind="video", model="bytedance/seedance-2.0",
                             source="chat", prompt="кот" * 10, credits_planned=42)
        row = GenerationLog.objects.get(pk=entry.pk)
        self.assertEqual(row.credits_planned, 42)
        self.assertEqual(row.prompt, "кот" * 10)
        self.assertEqual(row.stages[0]["stage"], "started")


class RecoveryPushLinkTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(email="push@example.com", password="x")

    def test_push_opens_the_chat_page_that_exists(self):
        session = AiChatSession.objects.create(user=self.user, title="Видео")
        with patch("users.webpush.notify_user") as push:
            recovery._notify(self.user, session)
        push.assert_called_once()
        self.assertEqual(push.call_args.kwargs["url"], f"/dashboard/text-chat/{session.uid}")

    def test_push_without_chat_goes_home(self):
        with patch("users.webpush.notify_user") as push:
            recovery._notify(self.user, None)
        self.assertEqual(push.call_args.kwargs["url"], "/")
