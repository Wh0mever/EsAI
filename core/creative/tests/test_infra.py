"""Подключение Creative Studio: приложение, маршруты, лимиты, очереди, расписание, .env.example, nginx."""
from __future__ import annotations

import os

from django.conf import settings
from django.test import SimpleTestCase
from django.urls import resolve, reverse

REPO = os.path.abspath(os.path.join(settings.BASE_DIR, ".."))


class InfraTests(SimpleTestCase):
    def test_app_and_routes(self):
        self.assertIn("creative.apps.CreativeConfig", settings.INSTALLED_APPS)
        self.assertEqual(reverse("creative:run"), "/api/creative/run/")
        self.assertEqual(resolve("/api/creative/hook").url_name, "hook-noslash")
        self.assertEqual(resolve("/api/manage/creative/settings/").url_name, "settings")

    def test_throttle_scopes(self):
        rates = settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]
        for scope in ("creative_read", "creative_quote", "creative_run", "creative_upload",
                      "creative_poll", "creative_hook"):
            self.assertIn(scope, rates)
        self.assertEqual(rates["creative_run"], "20/min")

    def test_safe_defaults(self):
        self.assertIn(settings.CREATIVE_MODE, ("off", "staff", "on"))
        self.assertGreaterEqual(settings.CREATIVE_MAX_PARALLEL, 1)
        self.assertGreaterEqual(settings.CREATIVE_MAX_OPEN_PER_USER, 1)
        self.assertTrue(hasattr(settings, "HF_KEY"))
        self.assertTrue(hasattr(settings, "HF_WEBHOOK_SECRET"))

    def test_routes_and_beat(self):
        routes = settings.CELERY_TASK_ROUTES
        default = settings.CELERY_TASK_DEFAULT_QUEUE
        self.assertEqual(routes["creative.tasks.sweep_jobs"]["queue"], default)
        self.assertTrue(routes["creative.tasks.*"]["queue"])
        if not settings.CELERY_CREATIVE_QUEUE and settings.CELERY_VSTUDIO_QUEUE:
            self.assertEqual(routes["creative.tasks.*"]["queue"], settings.CELERY_VSTUDIO_QUEUE)
        beat = settings.CELERY_BEAT_SCHEDULE["creative:sweep_jobs"]
        self.assertEqual(beat["task"], "creative.tasks.sweep_jobs")
        self.assertEqual(beat["options"], {"expire_seconds": 50})

    def test_env_example_block(self):
        path = os.path.join(REPO, ".env.example")
        if not os.path.exists(path):
            self.skipTest(".env.example нет рядом")
        text = open(path, encoding="utf-8").read()
        for line in ("CREATIVE_MODE=staff", "\nHF_KEY=\n", "\nHF_WEBHOOK_SECRET=\n"):
            self.assertIn(line, text)

    def test_nginx_upload_location_in_both_files(self):
        for name in ("nginx.conf", "nginx-ssl.conf"):
            path = os.path.join(REPO, "nginx", name)
            if not os.path.exists(path):
                self.skipTest("nginx нет рядом")
            text = open(path, encoding="utf-8").read()
            self.assertIn("location = /api/creative/uploads/", text)
            # тело не больше того, что пропускает Cloudflare Free (100 МБ), как у склейки
            start = text.index("location = /api/creative/uploads/")
            block = text[start:text.index("}", start)]
            self.assertIn("client_max_body_size 95m;", block)
        self.assertLessEqual(settings.CREATIVE_VIDEO_MAX_MB, 90)

    def test_vendor_absent_from_browser_side_files(self):
        """Имя поставщика не должно попасть ни в сайт, ни в наши ответы (кроме реестра и клиента)."""
        allowed = {"registry.py", "hf.py", "catalog.py"}
        app = os.path.join(settings.BASE_DIR, "creative")
        for root, _dirs, files in os.walk(app):
            if "tests" in root or "migrations" in root or "__pycache__" in root:
                continue
            for name in files:
                if name.endswith(".py") and name not in allowed:
                    text = open(os.path.join(root, name), encoding="utf-8").read().lower()
                    self.assertNotIn("higgsfield", text, name)
