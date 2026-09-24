# -*- coding: utf-8 -*-
"""BE-1: списания видеостудии видны в метриках дашборда."""
from django.contrib.auth import get_user_model
from django.test import TestCase

from audit.metrics import collect_dashboard_metrics
from plans.models import TokenTransaction, TokenTransactionReason, VSTUDIO_SPEND_REASONS


class VstudioSpendMetricsTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(email="u@example.com", password="x-12345678")

    def _tx(self, reason, delta):
        TokenTransaction.objects.create(user=self.user, delta=delta, reason=reason, balance_after=0)

    def test_reasons_fit_field(self):
        field = TokenTransaction._meta.get_field("reason")
        for reason in VSTUDIO_SPEND_REASONS:
            self.assertLessEqual(len(reason), field.max_length)
            self.assertIn(reason, dict(field.choices))
        self.assertEqual(TokenTransactionReason.VSTUDIO_VIDEO.label, "Видеостудия: видео")
        self.assertEqual(TokenTransactionReason.VSTUDIO_IMAGE.label, "Видеостудия: картинка")

    def test_tokens_spent_includes_vstudio(self):
        self._tx("chat", -10)
        self._tx("vstudio_video", -40)
        self._tx("vstudio_image", -2)
        self._tx("cartoon_scene", -100)
        self._tx("purchase", 500)
        data = collect_dashboard_metrics()
        self.assertEqual(data["tokens_spent_chat"], 10)
        self.assertEqual(data["tokens_spent_vstudio"], 42)
        self.assertEqual(data["tokens_spent"], 52)
        self.assertEqual(data["tokens_purchased"], 500)
