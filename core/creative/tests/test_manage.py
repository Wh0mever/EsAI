"""Админка /api/manage/creative/: наценки, рубильники, режим, журнал, сводка; каталоги."""
from __future__ import annotations

from decimal import Decimal

from audit.models import AdminActionLog
from creative import catalog
from creative.models import CreativeJob, CreativeTool

from .helpers import CreativeTestCase, make_user


class ManageTests(CreativeTestCase):
    def setUp(self):
        super().setUp()
        self.staff = make_user(is_staff=True)
        self.boss = make_user(is_staff=True, is_superuser=True)

    def test_settings_payload_has_our_names_only(self):
        r = self.client_for(self.staff).get("/api/manage/creative/settings/")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(len(data["tools"]), 15)
        self.assertEqual(data["markup_pct"], "40")
        portrait = next(t for t in data["tools"] if t["id"] == "portrait")
        self.assertEqual(portrait["name"], "Фотореалистичный портрет")
        self.assertEqual(portrait["example"]["credits"], 14)
        self.assertTrue(portrait["uses_global"])
        self.assert_no_vendor(data)

    def test_not_staff_forbidden(self):
        r = self.client_for(make_user()).get("/api/manage/creative/settings/")
        self.assertEqual(r.status_code, 403)

    def test_markup_needs_superuser(self):
        r = self.client_for(self.staff).patch("/api/manage/creative/settings/", {"markup_pct": 60},
                                              format="json")
        self.assertEqual(r.status_code, 403)
        r = self.client_for(self.staff).patch("/api/manage/creative/settings/",
                                              {"tools": [{"id": "portrait", "markup_pct": 10}]}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_superuser_changes_markup_and_tool_markup_logged(self):
        client = self.client_for(self.boss)
        r = client.patch("/api/manage/creative/settings/", {"markup_pct": "100"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        portrait = next(t for t in r.json()["tools"] if t["id"] == "portrait")
        # $0.094 × 2.00 / $0.01 = 18.8 → 19
        self.assertEqual(portrait["example"]["credits"], 19)
        r = client.patch("/api/manage/creative/settings/",
                         {"tools": [{"id": "portrait", "markup_pct": "0", "use_own_markup": True}]}, format="json")
        portrait = next(t for t in r.json()["tools"] if t["id"] == "portrait")
        # своя наценка 0 % ниже порога 25 % — цену держит порог: 0.094 × 1.25 / 0.01 = 11.75 → 12
        self.assertEqual(portrait["example"]["credits"], 12)
        self.assertEqual(portrait["effective_markup_pct"], "25")
        logs = self.client_for(self.staff).get("/api/manage/creative/log/").json()["items"]
        self.assertEqual(len(logs), 2)
        self.assertIn("tool:portrait", logs[0]["after"])
        self.assertEqual(AdminActionLog.objects.filter(action="settings.edit").count(), 2)

    def test_staff_toggles_tool_and_mode(self):
        client = self.client_for(self.staff)
        r = client.patch("/api/manage/creative/settings/",
                         {"mode": "off", "tools": [{"id": "restyle", "enabled": False}]}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["mode"], "off")
        self.assertFalse(CreativeTool.objects.get(slug="restyle").enabled)
        r = client.patch("/api/manage/creative/settings/", {"mode": "bogus"}, format="json")
        self.assertEqual(r.status_code, 400)
        r = client.patch("/api/manage/creative/settings/", {"mode": ""}, format="json")
        self.assertEqual(r.json()["mode"], "on")       # правка снята — как в окружении

    def test_summary(self):
        user = make_user(balance=100)
        CreativeJob.objects.create(user=user, tool_slug="portrait", kind="image", params={}, credits_quoted=14,
                                   credits_reserved=14, credits_charged=14, status="done",
                                   charge_state="charged", cost_usd=Decimal("0.094"))
        CreativeJob.objects.create(user=user, tool_slug="portrait", kind="image", params={}, credits_quoted=14,
                                   credits_reserved=14, status="failed", charge_state="released")
        r = self.client_for(self.staff).get("/api/manage/creative/summary/")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["jobs"]["total"], 2)
        self.assertEqual(data["jobs"]["done"], 1)
        self.assertEqual(data["credits_charged"], 14)
        self.assertEqual(data["revenue_usd"], "0.14")
        self.assertEqual(data["cost_usd"], "0.0940")
        self.assertEqual(data["margin_usd"], "0.05")
        self.assertEqual(self.client_for(self.staff).get("/api/manage/creative/summary/?from=bad").status_code, 400)
        self.assert_no_vendor(data)


class CatalogTests(CreativeTestCase):
    def setUp(self):
        super().setUp()
        cdn = "https://cdn.provider-files.test"
        self.fake.catalogs = {
            "/v1/text2image/soul-styles/v2": [
                {"id": "7ee16ff3-c0b0-4f5f-a0e1-e7fc46144230", "name": "Soul Y2K studio", "description": "",
                 "preview_url": f"{cdn}/s/1.webp"},
                {"id": "95151de0-e0e5-4e04-bd45-c58c8a4ac023", "name": "Higgsfield", "description": "",
                 "preview_url": f"{cdn}/s/2.webp"}],
            "/models/higgsfield/ai-influencer/options": {"config_revision": "x", "categories": [
                {"key": "gender", "label": "Gender", "tiers": ["normal", "freak"], "max": 1,
                 "options": [{"key": "female", "label": "Female", "img": f"{cdn}/o/f.webp", "color": None,
                              "tiers": ["normal"], "exclusive": False}]},
                {"key": "gender", "label": "Gender", "tiers": ["cats"], "max": 1, "options": []}]},
        }

    def test_public_catalog_strips_brand_and_hides_cdn(self):
        user = make_user()
        r = self.client_for(user).get("/api/creative/catalog/styles-v2/")
        self.assertEqual(r.status_code, 200, r.content)
        items = r.json()["items"]
        self.assertEqual(items[0]["name"], "Y2K studio")
        self.assertEqual(items[1]["name"], "Стиль 2")
        self.assertIsNone(items[0]["preview"])          # превью ещё не скопировано
        self.assert_no_vendor(r.json())
        # задача синхронизации копирует превью к себе
        self.assertEqual(catalog.sync("styles-v2"), 2)
        items = self.client_for(user).get("/api/creative/catalog/styles-v2/").json()["items"]
        self.assertTrue(items[0]["preview"].startswith("/media/creative/catalog/styles-v2/"))
        self.assertFalse(self.fake.auth_leaks)

    def test_influencer_only_normal_tier(self):
        data = self.client_for(make_user()).get("/api/creative/catalog/influencer/").json()
        self.assertEqual(len(data["categories"]), 1)
        self.assertEqual(data["categories"][0]["options"][0]["key"], "female")
        self.assert_no_vendor(data)

    def test_unknown_and_unavailable(self):
        client = self.client_for(make_user())
        self.assertEqual(client.get("/api/creative/catalog/nope/").status_code, 404)
        r = client.get("/api/creative/catalog/restyle/")
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.json()["error_code"], "catalog_unavailable")
