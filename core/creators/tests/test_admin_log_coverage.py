"""Журнал действий администратора: каждая кнопка админки оставляет ровно одну строку.

ТЗ п.35 — «полный лог ручных изменений администратора». Тест табличный:
для каждого изменяющего адреса раздела Creators (и двух старых адресов,
которые теперь двигают деньги креаторов) проверяется код действия, кто его
сделал и к какому креатору оно относится. Отдельно — случаи, где строк две,
и то, что отказ не оставляет в журнале ничего.
"""
from django.utils import timezone

from audit.models import ADMIN_ACTIONS, AdminActionLog
from plans.wallet import credit_tokens

from ..models import Creator, CreatorCommission, CreatorPublication
from . import factories as f
from . import test_api_public as api
from . import test_commission as money

M = api.MANAGE + "creators/"
PAYMENTS = api.MANAGE + "payments/"


class LogCoverageBase(api.ApiTestCase):
    def setUp(self):
        super().setUp()
        self.patch("botapi.stars.tg_api")
        self.su_user = f.make_user(superuser=True)
        self.su = self.client_for(self.su_user)

    # ------------------------------------------------------------ помощники

    def new_rows(self, mark):
        """Строки журнала, появившиеся после отметки (фабрики пишут свои — их не считаем)."""
        return list(AdminActionLog.objects.filter(pk__gt=mark).order_by("pk"))

    def mark(self) -> int:
        return AdminActionLog.objects.order_by("-pk").values_list("pk", flat=True).first() or 0

    def send(self, method, url, body=None):
        return getattr(self.su, method)(url, body or {}, format="json")

    def publication(self, creator):
        return CreatorPublication.objects.create(
            creator=creator, network="instagram", url=f"https://instagram.com/p/{creator.pk}",
            url_norm=f"instagram.com/p/{creator.pk}")

    def paid_commission(self, creator, **kwargs):
        """Комиссия, уже вышедшая из холда: под неё можно одобрять вывод."""
        return f.make_commission(creator, amount="50.000000", base="500.000000",
                                 available_in_days=-1, **kwargs)

    def stars_payment(self, buyer):
        payment = f.make_payment(buyer, provider="telegram_stars", amount="170", tokens=500)
        money.star_invoice(payment)
        f.credit_purchase(payment)
        return payment

    # ----------------------------------------------- случаи: одна строка

    # Каждый случай готовит свои данные и возвращает
    # (метод, адрес, тело, код действия, креатор в строке журнала | None).

    def case_application_approve(self):
        application = api.make_application()
        return ("post", M + f"applications/{application.pk}/approve/", {"level": "creator"},
                "application.approve", lambda: Creator.objects.get(user=application.user).pk)

    def case_application_reject(self):
        application = api.make_application()
        return ("post", M + f"applications/{application.pk}/reject/", {"reason": "Мало работ"},
                "application.reject", None)

    def case_application_block(self):
        application = api.make_application()
        return ("post", M + f"applications/{application.pk}/reject/",
                {"reason": "Накрутка", "block": True}, "application.block", None)

    def case_application_unblock(self):
        application = api.make_application(status="blocked")
        return ("post", M + f"applications/{application.pk}/unblock/", {"reason": "Ошиблись"},
                "application.unblock", None)

    def case_creator_level(self):
        creator = f.make_creator()
        return ("post", M + f"{creator.pk}/level/", {"level": "ambassador", "reason": "Рост"},
                "creator.level_change", creator.pk)

    def case_creator_block(self):
        creator = f.make_creator()
        return ("post", M + f"{creator.pk}/block/", {"reason": "Накрутка"},
                "creator.block", creator.pk)

    def case_creator_unblock(self):
        creator = f.make_creator(status="blocked")
        return ("post", M + f"{creator.pk}/unblock/", {"reason": "Разобрались"},
                "creator.unblock", creator.pk)

    def case_creator_code_change(self):
        creator = f.make_creator(code="OLDCODE1")
        return ("post", M + f"{creator.pk}/code/", {"code": "NEWCODE1", "reason": "Просьба"},
                "creator.code_change", creator.pk)

    def case_creator_code_set(self):
        # У креатора ещё нет кода — администратор задаёт первый.
        creator = f.make_creator()
        return ("post", M + f"{creator.pk}/code/", {"code": "FIRST001", "reason": "Просьба"},
                "creator.code_set", creator.pk)

    def case_credits_grant(self):
        creator = f.make_creator()
        return ("post", M + f"{creator.pk}/credits/",
                {"amount": 500, "category": "content", "note": "За ролик"},
                "credits.grant", creator.pk)

    def case_publication_approve(self):
        creator = f.make_creator()
        publication = self.publication(creator)
        return ("post", M + f"publications/{publication.pk}/approve/", {},
                "publication.approve", creator.pk)

    def case_publication_reject(self):
        creator = f.make_creator()
        publication = self.publication(creator)
        return ("post", M + f"publications/{publication.pk}/reject/", {"reason": "Не про EsAI"},
                "publication.reject", creator.pk)

    def case_referral_rebind(self):
        old, new = f.make_creator(), f.make_creator()
        user = f.make_user()
        f.make_referral(old, user)
        return ("post", M + "referrals/rebind/",
                {"user_id": user.pk, "creator_id": new.pk, "reason": "Ошибка привязки"},
                "referral.rebind", new.pk)

    def case_referral_unbind(self):
        old = f.make_creator()
        user = f.make_user()
        f.make_referral(old, user)
        return ("post", M + "referrals/rebind/",
                {"user_id": user.pk, "creator_id": None, "reason": "Просьба"},
                "referral.rebind", old.pk)

    def case_referral_clear_suspect(self):
        creator = f.make_creator()
        referral = f.make_referral(creator, f.make_user(), suspect=True)
        return ("post", M + f"referrals/{referral.pk}/clear-suspect/", {"reason": "Проверили"},
                "referral.clear_suspect", creator.pk)

    def case_commission_void(self):
        creator = f.make_creator()
        row = f.make_commission(creator)
        return ("post", M + f"commissions/{row.pk}/void/", {"reason": "Самовыкуп"},
                "commission.void", creator.pk)

    def case_commission_release(self):
        creator = f.make_creator()
        row = f.make_commission(creator, status="held", reason="creator_blocked")
        return ("post", M + f"commissions/{row.pk}/release/", {"reason": "Проверили"},
                "commission.release", creator.pk)

    def case_commission_restore(self):
        creator = f.make_creator()
        row = f.make_commission(creator, status="reversed", reason="refund:admin")
        return ("post", M + f"commissions/{row.pk}/restore/", {"reason": "Отмена была ошибкой"},
                "commission.restore", creator.pk)

    def case_withdrawal_approve(self):
        creator = f.make_creator()
        self.paid_commission(creator)
        withdrawal = f.make_withdrawal(creator, "10.00")
        return ("post", M + f"withdrawals/{withdrawal.pk}/approve/", {},
                "withdrawal.approve", creator.pk)

    def case_withdrawal_reject(self):
        creator = f.make_creator()
        withdrawal = f.make_withdrawal(creator, "10.00")
        return ("post", M + f"withdrawals/{withdrawal.pk}/reject/", {"reason": "Неверный адрес"},
                "withdrawal.reject", creator.pk)

    def case_withdrawal_mark_paid(self):
        creator = f.make_creator()
        self.paid_commission(creator)
        withdrawal = f.make_withdrawal(creator, "10.00", status="approved")
        return ("post", M + f"withdrawals/{withdrawal.pk}/mark-paid/", {"txid": "1a" * 32},
                "withdrawal.mark_paid", creator.pk)

    def case_withdrawal_fix_txid(self):
        creator = f.make_creator()
        self.paid_commission(creator)
        withdrawal = f.make_withdrawal(creator, "10.00", status="paid")
        return ("post", M + f"withdrawals/{withdrawal.pk}/txid/",
                {"txid": "2b" * 32, "reason": "Опечатка"}, "withdrawal.fix_txid", creator.pk)

    def case_withdrawal_reopen(self):
        creator = f.make_creator()
        self.paid_commission(creator)
        withdrawal = f.make_withdrawal(creator, "10.00", status="paid")
        return ("post", M + f"withdrawals/{withdrawal.pk}/reopen/", {"reason": "Не дошло"},
                "withdrawal.reopen", creator.pk)

    def case_level_edit(self):
        return ("patch", M + "levels/ambassador/", {"min_paying": 31, "reason": "Новые условия"},
                "level.edit", None)

    def case_creators_settings(self):
        return ("patch", M + "settings/", {"hold_days": 21}, "settings.edit", None)

    def case_kgs_rate(self):
        return ("patch", api.MANAGE + "settings/", {"currency_kgs_to_usd_rate": 0.0117},
                "settings.edit", None)

    def case_payment_mark_refunded(self):
        creator = f.make_creator()
        buyer = f.make_user()
        payment = f.make_payment(buyer)
        f.make_commission(creator, payment, buyer=buyer)
        return ("post", PAYMENTS + f"{payment.pk}/mark-refunded/",
                {"kind": "refund", "reason": "Вернули вручную"},
                "payment.mark_refunded", creator.pk)

    def case_refund_stars(self):
        creator = f.make_creator()
        buyer = f.make_user()
        payment = self.stars_payment(buyer)
        f.make_commission(creator, payment, buyer=buyer)
        return ("post", PAYMENTS + f"{payment.pk}/refund-stars/", {"reason": "просьба"},
                "payment.mark_refunded", creator.pk)


class OneRowPerActionTests(LogCoverageBase):
    def cases(self):
        return sorted(name for name in dir(self) if name.startswith("case_"))

    def test_each_mutating_route_writes_exactly_one_row(self):
        seen = set()
        for name in self.cases():
            with self.subTest(case=name):
                method, url, body, action, creator = getattr(self, name)()
                mark = self.mark()
                response = self.send(method, url, body)
                self.assertIn(response.status_code, (200, 201), response.data)
                rows = self.new_rows(mark)
                self.assertEqual([row.action for row in rows], [action])
                row = rows[0]
                self.assertEqual(row.actor_id, self.su_user.pk)
                expected = creator() if callable(creator) else creator
                self.assertEqual(row.creator_id, expected)
                self.assertIn(row.action, ADMIN_ACTIONS)
                seen.add(action)
        # Таблица покрывает все коды действий админки (кроме смены адреса
        # выплат — её делает сам креатор, см. ниже).
        self.assertEqual(seen, set(ADMIN_ACTIONS) - {"creator.payout_address_change"})

    def test_a_refused_mutation_writes_nothing(self):
        """Тот же запрос второй раз (или без обязательных полей) — отказ и пустой журнал."""
        for name in self.cases():
            with self.subTest(case=name):
                method, url, body, _action, _creator = getattr(self, name)()
                # Портим запрос: без причины, уровня, кода и суммы сервис откажет.
                mark = self.mark()
                response = self.send(method, url, {"reason": "", "level": "нет такого",
                                                   "code": "!", "amount": 0, "txid": "zz",
                                                   "kind": "нет", "user_id": 0,
                                                   "hold_days": 999, "min_paying": -1,
                                                   "currency_kgs_to_usd_rate": 5})
                if name in ("case_publication_approve", "case_publication_reject",
                            "case_application_reject", "case_application_block",
                            "case_creator_unblock", "case_commission_release",
                            "case_withdrawal_approve", "case_refund_stars"):
                    # Этим действиям тело не нужно — отказом будет повтор.
                    self.assertIn(response.status_code, (200, 201), response.data)
                    mark = self.mark()
                    response = self.send(method, url, body)
                self.assertGreaterEqual(response.status_code, 400, response.data)
                self.assertLess(response.status_code, 500, response.data)
                self.assertEqual(self.new_rows(mark), [])

    def test_creator_changing_own_payout_address_is_logged_with_creator_as_actor(self):
        creator = f.make_creator()
        mark = self.mark()
        response = self.client_for(creator.user).put(
            api.API + "me/payout-address/", {"address": f.VALID_TRC20}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        row, = self.new_rows(mark)
        self.assertEqual((row.action, row.actor_id, row.creator_id),
                         ("creator.payout_address_change", creator.user_id, creator.pk))
        # Тот же адрес ещё раз — ничего не изменилось, строки нет.
        mark = self.mark()
        self.client_for(creator.user).put(api.API + "me/payout-address/",
                                          {"address": f.VALID_TRC20}, format="json")
        self.assertEqual(self.new_rows(mark), [])

    def test_read_routes_write_nothing(self):
        creator = f.make_creator()
        mark = self.mark()
        for path in ("", f"{creator.pk}/", "applications/", "publications/", "referrals/",
                     "commissions/", "withdrawals/", "credits/", "levels/", "log/", "settings/"):
            self.assertEqual(self.su.get(M + path).status_code, 200, path)
        self.assertEqual(self.new_rows(mark), [])


class TwoRowCasesTests(LogCoverageBase):
    """Действия, которые по своей сути — два решения сразу."""

    def test_block_with_an_open_withdrawal(self):
        creator = f.make_creator()
        withdrawal = f.make_withdrawal(creator, "10.00")
        mark = self.mark()
        response = self.send("post", M + f"{creator.pk}/block/", {"reason": "Накрутка"})
        self.assertEqual(response.status_code, 200, response.data)
        rows = self.new_rows(mark)
        self.assertEqual([row.action for row in rows], ["creator.block", "withdrawal.reject"])
        self.assertEqual({row.creator_id for row in rows}, {creator.pk})
        self.assertEqual({row.actor_id for row in rows}, {self.su_user.pk})
        self.assertEqual(rows[1].target_id, str(withdrawal.pk))
        self.assertEqual(rows[1].after, {"status": "rejected", "via": "creator.block"})

    def test_restore_with_clear_admin_refund(self):
        creator = f.make_creator()
        payment = f.make_payment(f.make_user())
        payment.response = {"admin_refund": {"kind": "refund", "by_id": self.su_user.pk}}
        payment.save(update_fields=["response"])
        row = f.make_commission(creator, payment, status="reversed", reason="refund:admin")
        mark = self.mark()
        response = self.send("post", M + f"commissions/{row.pk}/restore/",
                             {"reason": "Отметка была ошибкой", "clear_admin_refund": True})
        self.assertEqual(response.status_code, 200, response.data)
        rows = self.new_rows(mark)
        self.assertEqual(sorted(r.action for r in rows),
                         ["commission.restore", "payment.mark_refunded"])
        self.assertEqual({r.creator_id for r in rows}, {creator.pk})
        cleared = next(r for r in rows if r.action == "payment.mark_refunded")
        self.assertEqual(cleared.after, {"cleared": True})

    def test_mark_refunded_follow_up(self):
        creator = f.make_creator()
        buyer = f.make_user()
        payment = f.make_payment(buyer)
        f.credit_purchase(payment)
        f.make_commission(creator, payment, buyer=buyer)
        url = PAYMENTS + f"{payment.pk}/mark-refunded/"
        mark = self.mark()
        self.assertEqual(self.send("post", url, {"kind": "refund",
                                                 "reason": "Вернули вручную"}).status_code, 200)
        self.assertEqual(self.send("post", url, {"kind": "refund", "reason": "Изъять кредиты",
                                                 "clawback_credits": True}).status_code, 200)
        rows = self.new_rows(mark)
        self.assertEqual([r.action for r in rows], ["payment.mark_refunded"] * 2)
        self.assertEqual([r.creator_id for r in rows], [creator.pk, creator.pk])
        self.assertTrue(rows[1].after["followup"])
        # Третий раз — отказ, журнал не растёт.
        self.assertEqual(self.send("post", url, {"kind": "refund", "reason": "Ещё",
                                                 "clawback_credits": True}).status_code, 409)
        self.assertEqual(len(self.new_rows(mark)), 2)

    def test_clear_suspect_with_release_logs_every_released_commission(self):
        creator = f.make_creator()
        buyer = f.make_user()
        referral = f.make_referral(creator, buyer, suspect=True)
        for _ in range(2):
            f.make_commission(creator, buyer=buyer, status="held", reason="referral_suspect")
        mark = self.mark()
        response = self.send("post", M + f"referrals/{referral.pk}/clear-suspect/",
                             {"reason": "Проверили", "release_held": True})
        self.assertEqual(response.status_code, 200, response.data)
        rows = self.new_rows(mark)
        self.assertEqual(sorted(r.action for r in rows),
                         ["commission.release", "commission.release", "referral.clear_suspect"])
        self.assertEqual({r.creator_id for r in rows}, {creator.pk})
        self.assertEqual(CreatorCommission.objects.filter(status="held").count(), 0)

    def test_failed_step_rolls_back_the_whole_action(self):
        """Отказ посреди действия откатывает и уже сделанное, и его строки журнала."""
        creator = f.make_creator()
        buyer = f.make_user()
        referral = f.make_referral(creator, buyer, suspect=True)
        refunded = f.make_payment(buyer)
        refunded.response = {"yookassa_refunded": True}
        refunded.save(update_fields=["response"])
        f.make_commission(creator, buyer=buyer, status="held", reason="referral_suspect")
        f.make_commission(creator, refunded, buyer=buyer, status="held",
                          reason="referral_suspect")
        mark = self.mark()
        response = self.send("post", M + f"referrals/{referral.pk}/clear-suspect/",
                             {"reason": "Проверили", "release_held": True})
        self.assertError(response, 409, "payment_refunded")
        self.assertEqual(self.new_rows(mark), [])
        referral.refresh_from_db()
        self.assertTrue(referral.suspect)
        self.assertEqual(CreatorCommission.objects.filter(status="held").count(), 2)

    def test_grant_is_logged_once_and_credits_arrive_once(self):
        creator = f.make_creator()
        credit_tokens(creator.user, 5, "purchase", meta={})
        mark = self.mark()
        body = {"amount": 100, "category": "start"}
        self.assertEqual(self.send("post", M + f"{creator.pk}/credits/", body).status_code, 200)
        self.assertEqual(self.send("post", M + f"{creator.pk}/credits/", body).status_code, 409)
        self.assertEqual([r.action for r in self.new_rows(mark)], ["credits.grant"])
        creator.user.refresh_from_db()
        self.assertEqual(creator.user.token_balance, 105)
        self.assertLessEqual(self.new_rows(mark)[0].created_at, timezone.now())
