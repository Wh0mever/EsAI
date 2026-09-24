"""Серверный отчёт видеостудии (§11) и его эндпоинт в панели.

Отчёт читает только готовые строки, поэтому тесты собирают дубли фабриками в
нужных состояниях и двигают время прямым UPDATE (created_at — auto_now_add).
Цену кредита подменяем: настоящая идёт за курсом валют в сеть.
"""
import datetime as dt
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from ai.models import GenerationLog
from payments.models import FunnelEvent

from .. import reports
from ..models import Take
from . import factories as f

CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                      "LOCATION": "vstudio-reports"}}
VEO = "google/veo-3.1-fast"
CREDIT_USD = 0.01
LONG_PROMPT = " ".join(["слово"] * 200)   # Seedance понимает до ~150 слов


def _at(take, created, *, submitted=None, finished=None):
    """Сдвинуть время дубля (created_at ставится только при вставке)."""
    fields = {"created_at": created}
    if submitted is not None:
        fields["submitted_at"] = submitted
    if finished is not None:
        fields["finished_at"] = finished
    Take.objects.filter(pk=take.pk).update(**fields)
    return take


@override_settings(CACHES=CACHES)
class _ReportCase(TestCase):
    def setUp(self):
        for name, value in (("_credit_usd", CREDIT_USD), ("_min_margin", 0.4)):
            patcher = patch(f"vstudio.reports.{name}", return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.now = timezone.now()
        self.user = f.make_user()
        self.seedance = f.make_gpt_model(f.VIDEO_MODEL_REF, name="Seedance 2.0")
        self.veo = f.make_gpt_model(VEO, name="Veo 3.1 Fast")
        self.nano = f.make_gpt_model(f.IMAGE_MODEL_REF, name="Nano Banana")

    def shot(self, model=None, **kw):
        return f.make_shot(self.user, model=model or self.seedance, **kw)

    def report(self, days=30, **kw):
        return reports.build_report(days, now=self.now, **kw)


class HelpersTests(TestCase):
    def test_parse_days_clamps_and_defaults(self):
        self.assertEqual(reports.parse_days("7"), 7)
        self.assertEqual(reports.parse_days("0"), 1)
        self.assertEqual(reports.parse_days("100000"), reports.MAX_DAYS)
        self.assertEqual(reports.parse_days("abc"), reports.DEFAULT_DAYS)
        self.assertEqual(reports.parse_days(None), reports.DEFAULT_DAYS)

    def test_percentile_interpolates(self):
        self.assertIsNone(reports.percentile([], 0.5))
        self.assertEqual(reports.percentile([5], 0.9), 5.0)
        self.assertEqual(reports.percentile([4, 1, 3, 2], 0.5), 2.5)
        self.assertAlmostEqual(reports.percentile([1, 2, 3, 4], 0.9), 3.7)


class EmptyReportTests(_ReportCase):
    def test_every_day_present_and_shares_undefined(self):
        data = self.report(7)
        self.assertEqual(data["days"], 7)
        self.assertEqual(len(data["by_day"]), 7)
        self.assertEqual(data["by_day"][-1]["date"], timezone.localdate(self.now).isoformat())
        self.assertEqual([d["created"] for d in data["by_day"]], [0] * 7)
        totals = data["totals"]
        self.assertEqual(totals["created"], 0)
        # Деления на ноль нет: пустой период — «нет данных», а не 0%.
        self.assertIsNone(totals["success_rate"])
        self.assertIsNone(totals["share_refs"])
        self.assertIsNone(totals["prompt"]["share_over_soft"])
        self.assertEqual(totals["wait_s"], {"n": 0, "median": None, "p90": None})
        self.assertEqual(data["by_model"], [])
        self.assertEqual(data["journal"]["rows"], 0)
        self.assertEqual(data["credit_usd"], CREDIT_USD)


class OutcomeTests(_ReportCase):
    def setUp(self):
        super().setUp()
        today = self.now - dt.timedelta(minutes=30)
        # Выдано: 150 кр, себестоимость $0.5, 10 с очереди + 120 с у провайдера.
        self.done = f.make_take(self.shot(), status="done", credits=150,
                                provider_cost_usd=Decimal("0.5000"), genlog=True)
        _at(self.done, today, submitted=today + dt.timedelta(seconds=10),
            finished=today + dt.timedelta(seconds=130))
        # Частичное списание: резерв 150, взяли 100 — журнал needs_review.
        self.partial = f.make_take(self.shot(), status="done", credits=150, credits_charged=100,
                                   provider_cost_usd=Decimal("0.5000"),
                                   genlog={"needs_review": True})
        _at(self.partial, today, submitted=today + dt.timedelta(seconds=20),
            finished=today + dt.timedelta(seconds=320))
        # Не получилось: модерация ×2 и неверный параметр; без кода — unknown.
        for code in ("moderation", "moderation", "invalid_param", ""):
            _at(f.make_take(self.shot(), status="failed", error_code=code), today)
        # Потерян после отправки: провайдер взял $0.3, человек не платил.
        self.lost = f.make_take(self.shot(), status="lost", error_code="submit_unknown",
                                genlog={"provider_cost_usd": Decimal("0.3000")})
        _at(self.lost, today)
        # Довезён из lost бесплатно: done, но резерв снят и списано 0.
        self.redelivered = f.make_take(self.shot(), status="done", charge_state="released",
                                       credits_charged=0, provider_cost_usd=Decimal("0.2000"))
        _at(self.redelivered, today, submitted=today, finished=today + dt.timedelta(hours=5))
        # Отменён в очереди, ещё идёт и картинка — прочие модели и режимы.
        _at(f.make_take(self.shot(self.veo), status="canceled"), today)
        _at(f.make_take(self.shot(self.veo), status="running"), today)
        img_asset = f.make_asset(self.user)
        self.image = f.make_take(self.shot(self.nano, kind="image", inputs=[img_asset]),
                                 status="done", credits=3, provider_cost_usd=Decimal("0.0100"))
        _at(self.image, today, finished=today + dt.timedelta(seconds=20))
        # Вне окна отчёта — не считается.
        _at(f.make_take(self.shot(), status="done"), self.now - dt.timedelta(days=40))

    def test_statuses_and_codes(self):
        t = self.report()["totals"]
        self.assertEqual(t["created"], 11)
        self.assertEqual((t["done"], t["failed"], t["canceled"], t["lost"], t["open"]),
                         (4, 4, 1, 1, 1))
        self.assertEqual(t["redelivered"], 1)
        self.assertEqual(t["failed_by_code"], {"moderation": 2, "invalid_param": 1, "unknown": 1})
        self.assertEqual(t["lost_by_code"], {"submit_unknown": 1})
        self.assertEqual(t["statuses"]["running"], 1)
        # needs_review из журнала: частичное списание и потерянный.
        self.assertEqual(t["needs_review"], 2)
        # Отмена — не исход генерации: 4 выдано из 9 завершённых.
        self.assertEqual(t["success_rate"], round(4 / 9, 4))

    def test_money_partial_cost_and_margin(self):
        t = self.report()["totals"]
        self.assertEqual(t["credits"]["charged"], 150 + 100 + 3)
        self.assertEqual(t["partial"], 1)
        self.assertEqual(t["partial_shortfall"], 50)
        # Себестоимость — и с дубля, и из журнала (у потерянного).
        self.assertAlmostEqual(t["cost_usd"], 1.51)
        self.assertAlmostEqual(t["cost_unpaid_usd"], 0.5)   # потерянный + довоз
        revenue = 253 * CREDIT_USD
        self.assertAlmostEqual(t["revenue_usd"], revenue)
        self.assertAlmostEqual(t["margin_usd"], round(revenue - 1.51, 4))
        self.assertAlmostEqual(t["margin_share"], round((revenue - 1.51) / revenue, 4))
        # По выдачам с известной ценой: 2.53 выручки против 1.01 себестоимости.
        self.assertAlmostEqual(t["margin_share_costed"], round((2.53 - 1.01) / 2.53, 4))
        # 100 кр × $0.01 × 0.6 = $0.6 > $0.5 — маржа в норме; 3 кр картинки: $0.018 > $0.01.
        self.assertEqual(t["low_margin"], 0)

    def test_low_margin_flagged_like_delivery_check(self):
        Take.objects.filter(pk=self.done.pk).update(provider_cost_usd=Decimal("1.2000"))
        # 150 × 0.01 × (1 − 0.4) = 0.9 < 1.2.
        self.assertEqual(self.report()["totals"]["low_margin"], 1)

    def test_money_in_usd_unknown_without_credit_price(self):
        with patch("vstudio.reports._credit_usd", return_value=None):
            t = self.report()["totals"]
        self.assertIsNone(t["revenue_usd"])
        self.assertIsNone(t["margin_share"])
        self.assertIsNone(t["low_margin"])
        self.assertEqual(t["credits"]["charged"], 253)   # кредиты видны всё равно

    def test_timing_excludes_free_redelivery(self):
        t = self.report()["totals"]
        # Выдачи: 130 с, 320 с, 20 с (картинка); довоз через 5 ч не в счёт.
        self.assertEqual(t["wait_s"]["n"], 3)
        self.assertEqual(t["wait_s"]["median"], 130.0)
        self.assertEqual(t["wait_s"]["p90"], round(reports.percentile([20, 130, 320], 0.9), 1))
        # submitted→finished только у тех, у кого есть submitted_at.
        self.assertEqual(t["render_s"]["n"], 2)
        self.assertEqual(t["render_s"]["median"], 210.0)

    def test_by_model_rows_and_names(self):
        rows = {r["model"]: r for r in self.report()["by_model"]}
        self.assertEqual(set(rows), {f.VIDEO_MODEL_REF, VEO, f.IMAGE_MODEL_REF})
        seed = rows[f.VIDEO_MODEL_REF]
        self.assertEqual(seed["name"], "Seedance 2.0")
        self.assertEqual(seed["kind"], "video")
        self.assertEqual(seed["soft_words"], 150)
        self.assertEqual(seed["created"], 8)
        self.assertEqual(rows[VEO]["canceled"], 1)
        self.assertIsNone(rows[f.IMAGE_MODEL_REF]["soft_words"])
        self.assertEqual(rows[f.IMAGE_MODEL_REF]["modes"], {"i2i": 1})
        # Самая загруженная модель — первой.
        self.assertEqual(self.report()["by_model"][0]["model"], f.VIDEO_MODEL_REF)

    def test_filters(self):
        data = self.report(model=VEO)
        self.assertEqual(data["totals"]["created"], 2)
        self.assertEqual([r["model"] for r in data["by_model"]], [VEO])
        self.assertEqual(self.report(kind="image")["totals"]["created"], 1)
        with self.assertRaises(ValueError):
            self.report(kind="audio")


class ShapeTests(_ReportCase):
    def test_refs_frames_and_prompt_length(self):
        a, b = f.make_asset(self.user), f.make_asset(self.user)
        f.make_take(self.shot(inputs=[a]))                                   # r2v
        f.make_take(self.shot(inputs=[(b, "first_frame")]))                  # i2v
        f.make_take(self.shot(inputs=[a]), mode="r2v_pin")                   # оба
        long_take = f.make_take(self.shot(prompt=LONG_PROMPT),
                                warnings=[{"code": "prompt_long", "params": {}},
                                          {"code": "looks_like_script", "params": {}}])
        # Предупреждения не сохранились — «выше лимита» считается по словам.
        f.make_take(self.shot(), serialized_prompt=LONG_PROMPT, warnings=[])
        # У картинок мягкого лимита нет: в долю не входят вовсе.
        f.make_take(self.shot(self.nano, kind="image", prompt=LONG_PROMPT),
                    serialized_prompt=LONG_PROMPT)
        t = self.report()["totals"]
        self.assertEqual(t["created"], 6)
        self.assertEqual((t["with_refs"], t["with_frames"]), (2, 2))
        self.assertEqual(t["share_refs"], round(2 / 6, 4))
        p = t["prompt"]
        self.assertEqual(p["with_soft_limit"], 5)
        self.assertEqual(p["over_soft"], 2)
        self.assertEqual(p["share_over_soft"], 0.4)
        self.assertEqual(p["script_like"], 1)
        self.assertEqual(p["chars_max"], len(long_take.serialized_prompt))
        self.assertGreater(p["words_avg"], 0)

    def test_days_follow_site_timezone(self):
        # Asia/Bishkek = UTC+6: 20:00 UTC 23-го — это уже 24-е по времени сайта.
        now = timezone.make_aware(dt.datetime(2026, 9, 24, 12, 0))
        utc = dt.timezone.utc
        late = f.make_take(self.shot(), status="done")
        _at(late, dt.datetime(2026, 9, 23, 20, 0, tzinfo=utc))
        early = f.make_take(self.shot(), status="failed", error_code="x")
        _at(early, dt.datetime(2026, 9, 23, 17, 0, tzinfo=utc))
        with override_settings(TIME_ZONE="Asia/Bishkek"):
            data = reports.build_report(2, now=now)
        days = {d["date"]: d for d in data["by_day"]}
        self.assertEqual(list(days), ["2026-09-23", "2026-09-24"])
        self.assertEqual((days["2026-09-24"]["done"], days["2026-09-24"]["failed"]), (1, 0))
        self.assertEqual((days["2026-09-23"]["done"], days["2026-09-23"]["failed"]), (0, 1))
        cells = {(c["date"], c["model"]) for c in data["by_day_model"]}
        self.assertEqual(cells, {("2026-09-23", f.VIDEO_MODEL_REF),
                                 ("2026-09-24", f.VIDEO_MODEL_REF)})

    def test_condense_usage_from_funnel(self):
        f.make_take(self.shot())
        FunnelEvent.objects.create(name="vstudio_condense", user=self.user, meta={"accepted": True})
        FunnelEvent.objects.create(name="vstudio_condense", user=self.user, meta={"accepted": False})
        FunnelEvent.objects.create(name="vstudio_condense", device_key="dev-1",
                                   meta={"accepted": True, "model": f.VIDEO_MODEL_REF})
        FunnelEvent.objects.create(name="vstudio_run_click", user=self.user, meta={})
        old = FunnelEvent.objects.create(name="vstudio_condense", user=self.user,
                                         meta={"accepted": True})
        FunnelEvent.objects.filter(pk=old.pk).update(created_at=self.now - dt.timedelta(days=60))
        data = self.report()
        t = data["totals"]
        self.assertEqual((t["condense"], t["condense_accepted"]), (3, 2))
        self.assertEqual(t["condense_users"], 2)
        self.assertEqual(t["condense_without_model"], 2)
        self.assertEqual(data["condense_by_model"], {f.VIDEO_MODEL_REF: 1})
        self.assertEqual(data["by_day"][-1]["condense"], 3)
        self.assertEqual(data["by_model"][0]["condense"], 1)
        # С фильтром — только шаги, где модель известна и подходит.
        self.assertEqual(self.report(kind="video")["totals"]["condense"], 1)
        self.assertEqual(self.report(kind="image")["totals"]["condense"], 0)
        self.assertEqual(self.report(model=VEO)["totals"]["condense"], 0)

    def test_journal_consistency(self):
        f.make_take(self.shot(), status="done", genlog=True)
        # Журнал «в работе», а дубль уже закрыт — работа для sweep.
        f.make_take(self.shot(), status="failed", genlog={"status": GenerationLog.STATUS_SUBMITTED})
        # Запись без дубля и чужой источник.
        GenerationLog.objects.create(user=self.user, kind="video", model=f.VIDEO_MODEL_REF,
                                     source=GenerationLog.SOURCE_VSTUDIO, needs_review=True,
                                     status=GenerationLog.STATUS_LOST)
        GenerationLog.objects.create(user=self.user, kind="video", model=f.VIDEO_MODEL_REF,
                                     source=GenerationLog.SOURCE_CHAT)
        j = self.report()["journal"]
        self.assertEqual(j["rows"], 3)
        self.assertEqual(j["by_status"]["delivered"], 1)
        self.assertEqual(j["by_status"]["lost"], 1)
        self.assertEqual(j["orphans"], 1)
        self.assertEqual(j["open_but_take_closed"], 1)
        self.assertEqual(j["needs_review"], 1)

    def test_labels_for_ui(self):
        labels = self.report()["labels"]
        self.assertEqual(labels["status"]["lost"], "Потерян")
        self.assertIn("r2v_pin", labels["mode"])


@override_settings(CACHES=CACHES)
class ReportEndpointTests(TestCase):
    url = "/api/manage/vstudio/report/"

    def setUp(self):
        patcher = patch("vstudio.reports._credit_usd", return_value=CREDIT_USD)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = APIClient()
        self.staff = f.make_user(is_staff=True)
        self.user = f.make_user()

    def test_route_name(self):
        self.assertEqual(reverse("adminapi:vstudio-report"), self.url)

    def test_staff_only(self):
        self.assertEqual(self.client.get(self.url).status_code, 401)
        self.client.force_authenticate(self.user)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_staff_gets_report(self):
        f.make_take(f.make_shot(self.user), status="done")
        self.client.force_authenticate(self.staff)
        res = self.client.get(self.url, {"days": "7"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["days"], 7)
        self.assertEqual(res.data["totals"]["done"], 1)
        # Мусор в days — значение по умолчанию, а не 500.
        self.assertEqual(self.client.get(self.url, {"days": "x"}).data["days"], 30)

    def test_filters_validated(self):
        self.client.force_authenticate(self.staff)
        res = self.client.get(self.url, {"kind": "audio"})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.data["error_code"], "bad_request")
        self.assertEqual(self.client.get(self.url, {"model": "x" * 200}).status_code, 400)
        ok = self.client.get(self.url, {"kind": "video", "model": f.VIDEO_MODEL_REF})
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.data["filters"], {"model": f.VIDEO_MODEL_REF, "kind": "video"})

    def test_disabled_without_app(self):
        self.client.force_authenticate(self.staff)
        with patch("adminapi.vstudio.apps.is_installed", return_value=False):
            res = self.client.get(self.url)
        self.assertEqual(res.status_code, 503)
        self.assertEqual(res.data["error_code"], "vstudio_disabled")
