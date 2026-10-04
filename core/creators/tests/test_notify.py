"""Уведомления креатору: тексты на трёх языках и доставка после фиксации транзакции.

emit() зовут изнутри денежных операций, поэтому главное здесь — что он ничего
не роняет и ничего не отправляет, пока транзакция не зафиксирована.
"""
import string
from unittest import mock

from django.db import transaction
from django.test import override_settings

from users.models import Notification, NotificationDelivery

from .. import notify
from . import factories as f

# Подстановки каждого события — как их передают сервисы (§7 спецификации).
CTX = {
    "application_approved": {"level_title": "CREATOR PRO", "percent": "15"},
    "application_rejected": {"reason": "Мало подписчиков"},
    "level_changed": {"level_title": "AMBASSADOR", "percent": "20", "old_title": "CREATOR PRO"},
    "credits_granted": {"amount": 1000, "category": "start"},
    "new_referral": {"user_label": "@friend"},
    "new_paying_user": {"user_label": "@friend"},
    "commission_accrued": {"amount_usdt": "0.115", "base_usdt": "1.15", "percent": "10"},
    "payout_approved": {"amount_usdt": "48.50"},
    "payout_sent": {"amount_usdt": "48.50", "txid": "a" * 64},
    "publication_approved": {"url": "https://instagram.com/p/1"},
    "publication_rejected": {"url": "https://instagram.com/p/1", "reason": "Не про EsAI"},
    "next_level_ready": {"next_title": "AMBASSADOR", "next_percent": "20"},
    "payout_rejected": {"amount_usdt": "48.50", "reason": "Неверный адрес"},
}


def _fields(template: str) -> set:
    return {name for _, name, _, _ in string.Formatter().parse(template) if name}


class TextsTests(f.CreatorsTestCase):
    def test_events_are_the_client_list_plus_payout_rejected(self):
        self.assertEqual(len(notify.EVENTS), 13)
        self.assertEqual(len(set(notify.EVENTS)), 13)
        self.assertEqual(notify.EVENTS[-1], "payout_rejected")
        self.assertEqual(set(notify.TEXTS), set(notify.EVENTS))
        self.assertEqual(set(CTX), set(notify.EVENTS))

    def test_every_event_renders_in_three_languages(self):
        for event in notify.EVENTS:
            self.assertEqual(set(notify.TEXTS[event]), {"ru", "en", "kg"}, event)
            for lang in ("ru", "en", "kg"):
                title, body = notify.render(event, lang, CTX[event])
                self.assertTrue(title and body, (event, lang))
                self.assertLessEqual(len(title), 200)
                self.assertNotIn("{", body)
                self.assertNotIn("}", body)
                # Без единой подстановки тоже не падает: пропуски — пустые строки.
                empty_title, empty_body = notify.render(event, lang, {})
                self.assertTrue(empty_title and empty_body, (event, lang))
                self.assertNotIn("{", empty_body)

    def test_translations_keep_the_same_placeholders(self):
        for event in notify.EVENTS:
            ru = _fields(notify.TEXTS[event]["ru"][1])
            # Каждая подстановка русского текста — из тех, что передаёт сервис.
            self.assertTrue(ru <= set(CTX[event]), (event, ru))
            for lang in ("en", "kg"):
                self.assertEqual(_fields(notify.TEXTS[event][lang][1]), ru, (event, lang))
                self.assertEqual(_fields(notify.TEXTS[event][lang][0]), set(), (event, lang))

    def test_russian_texts_match_the_spec(self):
        self.assertEqual(
            notify.render("application_approved", "ru", CTX["application_approved"]),
            ("Заявка одобрена", "Вы участник EsAI Creators. Уровень: CREATOR PRO, комиссия 15%. "
                                "Создайте свой промокод в кабинете."))
        self.assertEqual(
            notify.render("commission_accrued", "ru", CTX["commission_accrued"]),
            ("Начислена комиссия", "+0.115 USDT (10% с оплаты 1.15 USDT)."))
        self.assertEqual(
            notify.render("payout_sent", "ru", CTX["payout_sent"]),
            ("Выплата отправлена", f"48.50 USDT отправлены. TXID: {'a' * 64}"))
        self.assertEqual(
            notify.render("next_level_ready", "ru", CTX["next_level_ready"]),
            ("Условия уровня выполнены",
             "Условия уровня AMBASSADOR выполнены. Ожидает подтверждения EsAI."))
        self.assertEqual(
            notify.render("credits_granted", "ru", CTX["credits_granted"]),
            ("Получены Creator Credits", "Вам начислено 1000 Creator Credits."))

    def test_unknown_language_falls_back_to_russian(self):
        ru = notify.render("payout_approved", "ru", CTX["payout_approved"])
        for lang in ("de", "", None, "RU"):
            self.assertEqual(notify.render("payout_approved", lang, CTX["payout_approved"]), ru)
        self.assertNotEqual(notify.render("payout_approved", "en", CTX["payout_approved"]), ru)

    def test_empty_reason_leaves_no_trailing_space(self):
        title, body = notify.render("application_rejected", "ru", {"reason": ""})
        self.assertEqual(body, "К сожалению, заявка в EsAI Creators отклонена.")
        _, body = notify.render("payout_rejected", "ru", {"amount_usdt": "10.00", "reason": None})
        self.assertEqual(body, "Заявка на 10.00 USDT отклонена.")

    def test_braces_in_values_are_not_interpreted(self):
        _, body = notify.render("publication_rejected", "ru",
                                {"url": "https://x.com/{reason}", "reason": "{url}"})
        self.assertEqual(body, "Публикация не засчитана: https://x.com/{reason}. {url}")


@override_settings(CREATORS_LINK_BASE="https://esai.kg/")
class EmitTests(f.CreatorsTestCase):
    def setUp(self):
        super().setUp()
        self.creator = f.make_creator()
        patcher = mock.patch("botapi.tasks.notify")
        self.tg = patcher.start()
        self.addCleanup(patcher.stop)

    def test_in_app_notification_appears_only_after_commit(self):
        with self.captureOnCommitCallbacks() as callbacks:
            notify.emit(self.creator, "payout_approved", amount_usdt="48.50")
        # Транзакция ещё не зафиксирована — ничего не создано и не отправлено.
        self.assertEqual(len(callbacks), 1)
        self.assertEqual(Notification.objects.count(), 0)
        self.tg.assert_not_called()

        callbacks[0]()
        notification = Notification.objects.get()
        self.assertEqual(notification.title, "Выплата одобрена")
        self.assertEqual(notification.body, "Заявка на 48.50 USDT одобрена и ждёт отправки.")
        delivery = NotificationDelivery.objects.get(notification=notification)
        self.assertEqual(delivery.recipient, self.creator.user)
        self.assertFalse(delivery.is_read)

    def test_rolled_back_operation_sends_nothing(self):
        class Boom(Exception):
            pass

        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            with self.assertRaises(Boom):
                with transaction.atomic():
                    notify.emit(self.creator, "commission_accrued", amount_usdt="1.5",
                                base_usdt="10.00", percent="15")
                    raise Boom()
        self.assertEqual(callbacks, [])
        self.assertEqual(Notification.objects.count(), 0)
        self.tg.assert_not_called()

    def test_telegram_called_with_kind_creator(self):
        with self.captureOnCommitCallbacks(execute=True):
            notify.emit(self.creator, "payout_sent", amount_usdt="48.50", txid="ab" * 32)
        self.tg.assert_called_once()
        args, kwargs = self.tg.call_args
        self.assertEqual(args[0], self.creator.user)
        self.assertEqual(args[1], "creator")
        self.assertEqual(args[2], f"<b>Выплата отправлена</b>\n48.50 USDT отправлены. "
                                  f"TXID: {'ab' * 32}")
        self.assertEqual(kwargs, {"url": "https://esai.kg/creators/dashboard",
                                  "url_label": "Открыть кабинет"})

    def test_creator_language_is_used(self):
        for lang, title, label in (("en", "Level changed", "Open dashboard"),
                                   ("kg", "Деңгээл өзгөртүлдү", "Кабинетти ачуу")):
            creator = f.make_creator(lang=lang)
            self.tg.reset_mock()
            with self.captureOnCommitCallbacks(execute=True):
                notify.emit(creator, "level_changed", level_title="AMBASSADOR", percent="20",
                            old_title="CREATOR PRO")
            self.assertEqual(Notification.objects.filter(recipients=creator.user).get().title,
                             title)
            self.assertEqual(self.tg.call_args.kwargs["url_label"], label)
            self.assertIn("AMBASSADOR", self.tg.call_args.args[2])

    def test_language_is_read_at_delivery_time(self):
        with self.captureOnCommitCallbacks() as callbacks:
            notify.emit(self.creator, "payout_approved", amount_usdt="10.00")
        type(self.creator).objects.filter(pk=self.creator.pk).update(lang="en")
        callbacks[0]()
        self.assertEqual(Notification.objects.get().title, "Payout approved")

    def test_values_are_converted_to_strings(self):
        from decimal import Decimal

        with self.captureOnCommitCallbacks(execute=True):
            notify.emit(self.creator, "credits_granted", amount=1000, category=None)
            notify.emit(self.creator, "commission_accrued", amount_usdt=Decimal("0.115"),
                        base_usdt=Decimal("1.15"), percent=Decimal("10"))
        bodies = set(Notification.objects.values_list("body", flat=True))
        self.assertEqual(bodies, {"Вам начислено 1000 Creator Credits.",
                                  "+0.115 USDT (10% с оплаты 1.15 USDT)."})

    def test_telegram_text_is_html_escaped(self):
        with self.captureOnCommitCallbacks(execute=True):
            notify.emit(self.creator, "publication_rejected", url="https://x.com/?a=1&b=2",
                        reason="<b>спам</b>")
        text = self.tg.call_args.args[2]
        self.assertTrue(text.startswith("<b>Публикация отклонена</b>\n"))
        self.assertIn("a=1&amp;b=2", text)
        self.assertIn("&lt;b&gt;спам&lt;/b&gt;", text)
        # В колокольчике текст как есть — его показывает сайт, не Telegram.
        self.assertIn("<b>спам</b>", Notification.objects.get().body)

    def test_unknown_event_is_ignored(self):
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            with self.assertLogs("creators", level="WARNING"):
                notify.emit(self.creator, "creator_deleted", x=1)
        self.assertEqual(callbacks, [])
        self.assertEqual(Notification.objects.count(), 0)
        self.tg.assert_not_called()

    def test_missing_creator_does_not_raise(self):
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            notify.emit(None, "payout_approved", amount_usdt="10.00")
            notify.emit(type(self.creator)(), "payout_approved", amount_usdt="10.00")
        self.assertEqual(callbacks, [])
        # Креатор пропал между постановкой и доставкой — тихо выходим.
        notify._deliver(10 ** 9, "payout_approved", {"amount_usdt": "10.00"})
        self.assertEqual(Notification.objects.count(), 0)

    def test_raising_telegram_keeps_the_in_app_notification(self):
        self.tg.side_effect = RuntimeError("telegram down")
        with self.assertLogs("creators", level="ERROR"):
            with self.captureOnCommitCallbacks(execute=True):
                notify.emit(self.creator, "payout_approved", amount_usdt="10.00")
        self.assertEqual(Notification.objects.count(), 1)

    def test_raising_in_app_channel_still_sends_telegram(self):
        with mock.patch.object(Notification.objects, "create", side_effect=RuntimeError("db")):
            with self.assertLogs("creators", level="ERROR"):
                with self.captureOnCommitCallbacks(execute=True):
                    notify.emit(self.creator, "payout_approved", amount_usdt="10.00")
        self.assertEqual(Notification.objects.count(), 0)
        self.tg.assert_called_once()

    def test_emit_never_raises_when_scheduling_fails(self):
        with mock.patch("creators.notify.transaction.on_commit", side_effect=RuntimeError("x")):
            with self.assertLogs("creators", level="ERROR"):
                notify.emit(self.creator, "payout_approved", amount_usdt="10.00")
                notify.emit_to_user(self.creator.user, "ru", "application_rejected", reason="")

    def test_delivery_failure_does_not_raise(self):
        with mock.patch("creators.notify._send", side_effect=RuntimeError("boom")):
            with self.assertLogs("creators", level="ERROR"):
                notify._deliver(self.creator.pk, "payout_approved", {})
                notify._deliver_to_user(self.creator.user_id, "ru", "application_rejected", {})

    def test_scheduled_with_robust_on_commit(self):
        with mock.patch("creators.notify.transaction.on_commit") as on_commit:
            notify.emit(self.creator, "payout_approved", amount_usdt="10.00")
        on_commit.assert_called_once()
        self.assertIs(on_commit.call_args.kwargs.get("robust"), True)


@override_settings(CREATORS_LINK_BASE="https://esai.kg")
class EmitToUserTests(f.CreatorsTestCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch("botapi.tasks.notify")
        self.tg = patcher.start()
        self.addCleanup(patcher.stop)

    def test_rejected_applicant_without_creator_row(self):
        user = f.make_user()
        with self.captureOnCommitCallbacks() as callbacks:
            notify.emit_to_user(user, "en", "application_rejected", reason="Not enough followers")
        self.assertEqual(Notification.objects.count(), 0)
        callbacks[0]()
        notification = Notification.objects.get()
        self.assertEqual(notification.title, "Application rejected")
        self.assertIn("Not enough followers", notification.body)
        self.assertEqual(list(notification.recipients.all()), [user])
        args, kwargs = self.tg.call_args
        self.assertEqual((args[0], args[1]), (user, "creator"))
        # Кабинета у него нет — кнопка ведёт на страницу программы.
        self.assertEqual(kwargs, {"url": "https://esai.kg/creators",
                                  "url_label": "About the program"})

    def test_unknown_event_and_missing_user(self):
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            with self.assertLogs("creators", level="WARNING"):
                notify.emit_to_user(f.make_user(), "ru", "nope")
            notify.emit_to_user(None, "ru", "application_rejected", reason="")
        self.assertEqual(callbacks, [])
        notify._deliver_to_user(10 ** 9, "ru", "application_rejected", {})
        self.assertEqual(Notification.objects.count(), 0)
        self.tg.assert_not_called()
