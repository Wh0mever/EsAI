"""Команда creators_chain_check: цепочка «заявка -> … -> вывод USDT» на подставных платежах.

[gate] Команде нужны сервисы всех частей программы (заявки, коды, привязка),
поэтому без них тесты пропускаются — их запускают на общей сборке.

Внутри TestCase работает только режим --rollback: временную базу нельзя
создать посреди открытой транзакции теста.
"""
import importlib.util
import io
import json
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command

from adminapi.runtime import get_runtime, set_runtime
from audit.models import AdminActionLog
from payments.models import CryptoInvoice, GoPayInvoice, Payment, StarInvoice
from plans.models import TokenTransaction

from ..models import (
    Creator,
    CreatorApplication,
    CreatorCode,
    CreatorCommission,
    CreatorReferral,
    CreatorWithdrawal,
)
from . import factories as f

OTHER_TRACKS = ("creators.program", "creators.codes", "creators.attribution")
ASSEMBLED = all(importlib.util.find_spec(name) is not None for name in OTHER_TRACKS)

TABLES = (Creator, CreatorApplication, CreatorCode, CreatorCommission, CreatorReferral,
          CreatorWithdrawal, Payment, CryptoInvoice, StarInvoice, GoPayInvoice,
          TokenTransaction, AdminActionLog)


@skipUnless(ASSEMBLED, "[gate] нужны все части программы Creators")
class ChainCheckTests(f.CreatorsTestCase):
    def run_chain(self, *args):
        out = io.StringIO()
        try:
            call_command("creators_chain_check", "--rollback", *args, stdout=out)
            code = 0
        except SystemExit as exc:
            code = exc.code
        return code, out.getvalue()

    def counts(self):
        return [model.objects.count() for model in TABLES] + [get_user_model().objects.count()]

    def test_rollback_run_passes_and_leaves_nothing_behind(self):
        before = self.counts()
        code, output = self.run_chain()
        lines = output.strip().splitlines()
        self.assertEqual(code, 0, output)
        self.assertEqual(lines[0], "step | provider | expected | actual | PASS/FAIL")
        rows = lines[1:-1]
        self.assertTrue(all(line.endswith("| PASS") for line in rows), output)
        # Все шаги на месте: от заявки до сверки.
        steps = {line.split(" | ")[0] for line in rows}
        self.assertEqual(steps, {f"S{n:02d}" for n in range(1, 23)})
        self.assertIn("0 FAIL", lines[-1])
        # Всё, что прогон создал, откатилось.
        self.assertEqual(self.counts(), before)
        self.assertEqual(Creator.objects.count(), 0)
        self.assertEqual(CreatorCommission.objects.count(), 0)

    def test_every_provider_path_is_in_the_table(self):
        code, output = self.run_chain("--json")
        data = json.loads(output)
        self.assertEqual((code, data["ok"]), (0, True))
        providers = {row["provider"] for row in data["rows"]}
        for name in ("freedompay (постбэк)", "freedompay (сверка)", "yookassa",
                     "crypto_nowpayments", "telegram_stars", "telegram_stars (без пользователя)",
                     "freedompay (сигнал возврата)", "freedompay (возврат в кабинете)",
                     "freedompay (изъятие упало)", "freedompay (отметка администратора)",
                     "freedompay (обычная рефералка)",
                     "gopay (вебхук и сверка)", "gopay (тестовый платёж)",
                     "gopay (отметка администратора)"):
            self.assertIn(name, providers)
        self.assertTrue(all(row["expected"] == row["actual"] for row in data["rows"]))
        # S02 проверяет общее пространство имён в обе стороны.
        s02 = [row["actual"] for row in data["rows"] if row["step"] == "S02"]
        self.assertIn("код = чужой referral_uid: code_taken", s02)
        self.assertIn("код = обычный промокод: code_taken", s02)

    def test_mode_is_patched_not_read(self):
        # Программа выключена в админке — проверка цепочки всё равно идёт в режиме «on»
        # и ничего не меняет в настройках.
        set_runtime("creators_mode", "off")
        code, output = self.run_chain()
        self.assertEqual(code, 0, output)
        self.assertEqual(get_runtime("creators_mode", "staff"), "off")

    def test_existing_data_is_untouched(self):
        creator = f.make_creator(code="KEEPME")
        buyer = f.make_user()
        f.make_referral(creator, buyer)
        row = f.make_commission(creator, f.make_payment(buyer), buyer=buyer)
        before = self.counts()
        code, output = self.run_chain()
        self.assertEqual(code, 0, output)
        self.assertEqual(self.counts(), before)
        row.refresh_from_db()
        self.assertEqual(row.status, "accrued")

    def test_broken_accrual_is_reported(self):
        # Проверка не формальная: если начисление не работает, цепочка это показывает.
        with patch("creators.commission.accrue", return_value=None):
            code, output = self.run_chain("--json")
        data = json.loads(output)
        self.assertEqual((code, data["ok"]), (1, False))
        failed = {row["step"] for row in data["rows"] if row["result"] == "FAIL"}
        self.assertTrue({"S06", "S07", "S08", "S09", "S10", "S12"} <= failed, failed)
        self.assertEqual(Creator.objects.count(), 0)

    def test_broken_reversal_is_reported(self):
        with patch("creators.commission.reverse_for_payment", return_value=0):
            code, output = self.run_chain("--json")
        data = json.loads(output)
        self.assertEqual(code, 1)
        failed = {row["step"] for row in data["rows"] if row["result"] == "FAIL"}
        self.assertTrue({"S15", "S16", "S17", "S18", "S19", "S22"} <= failed, failed)

    def test_paying_both_programs_is_reported(self):
        # «Двух программ сразу не бывает»: если вместе с комиссией уйдёт и доля
        # кредитами, шаги оплаты и сверка (I3) это ловят.
        from payments import referral

        real = referral.settle_referral

        def both(payment, order_id, credited, *, idem=""):
            result = real(payment, order_id, credited, idem=idem)
            from plans.wallet import credit_tokens

            if result == "commission":
                credit_tokens(payment.user, 1, "referral", meta={"order_id": order_id})
            return result

        with patch("payments.referral.settle_referral", side_effect=both):
            code, output = self.run_chain("--json")
        data = json.loads(output)
        self.assertEqual(code, 1)
        failed = {row["step"] for row in data["rows"] if row["result"] == "FAIL"}
        self.assertTrue({"S06", "S22"} <= failed, failed)
