# -*- coding: utf-8 -*-
"""Инфраструктура видеостудии (BE-8): приложение, маршруты, очереди, beat,
троттлинг и воркер в compose.

Запуск: python manage.py test core.tests_vstudio_infra --settings=core.settings_sqlitetest --noinput

Разбор env проверяется в отдельном процессе: settings.py читается один раз при
старте, а переменные окружения и .env разработчика не должны влиять на ответ.
"""
import json
import os
import subprocess
import sys
import tempfile
import uuid
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import skipUnless

from celery.app.routes import MapRoute
from celery.schedules import crontab
from django.apps import apps
from django.conf import settings
from django.test import SimpleTestCase, TestCase
from django.urls import URLResolver, get_resolver
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory, force_authenticate
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

try:
    import yaml
except ImportError:  # в образе без PyYAML проверка compose просто пропускается
    yaml = None

BASE_DIR = Path(settings.BASE_DIR)
REPO_ROOT = BASE_DIR.parent
COMPOSE = REPO_ROOT / "compose.yaml"
ENV_EXAMPLE = REPO_ROOT / ".env.example"

PIPELINE_TASKS = ("submit_take", "poll_take", "finalize_take", "run_image_take")
SAFETY_TASKS = ("sweep_takes", "purge_assets")
# Не конвейер: сборка лёгкой копии для витрины не занимает слот воркера студии.
SIDE_TASKS = ("build_showcase_clip",)
SCOPES = {
    "vstudio_read": "120/min",
    "vstudio_write": "30/min",
    "vstudio_quote": "90/min",
    "vstudio_run": "20/min",
    "vstudio_poll": "60/min",
    "vstudio_upload": "40/min",
    "vstudio_assist": "20/hour",
}

# Без этих переменных settings.py не импортируется; значения фиктивные.
_REQUIRED_ENV = {
    "DJANGO_SECRET_KEY": "infra-test",
    "POSTGRES_DB": "x",
    "POSTGRES_USER": "x",
    "POSTGRES_PASSWORD": "x",
    "EMAIL_HOST_PASSWORD": "x",
    "EXCHANGE_API_KEY": "x",
}
_OWN_ENV_PREFIXES = ("VSTUDIO_", "DRF_THROTTLE_VSTUDIO_")
_OWN_ENV_NAMES = ("CELERY_VSTUDIO_QUEUE", "CELERY_MEDIA_QUEUE")

_PROBE = r"""
import json, sys
import environ
# .env разработчика не должен подменять проверяемые значения по умолчанию.
environ.Env.read_env = staticmethod(lambda *a, **k: None)
import core.settings as s
json.dump({
    "mode": s.VSTUDIO_MODE,
    "max_open_video": s.VSTUDIO_MAX_OPEN_VIDEO,
    "max_open_image": s.VSTUDIO_MAX_OPEN_IMAGE,
    "give_up_hours": s.VSTUDIO_GIVE_UP_HOURS,
    "inline_refs": s.VSTUDIO_INLINE_REFS,
    "min_provider_usd": s.VSTUDIO_MIN_PROVIDER_USD,
    "assist_model": s.VSTUDIO_ASSIST_MODEL,
    "purge_days": s.VSTUDIO_PURGE_DAYS,
    "vstudio_queue": s.CELERY_VSTUDIO_QUEUE,
    "media_queue": s.CELERY_MEDIA_QUEUE,
    "default_queue": s.CELERY_TASK_DEFAULT_QUEUE,
    "routes": s.CELERY_TASK_ROUTES,
    "rates": {k: v for k, v in s.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"].items()
              if k.startswith("vstudio_")},
    "apps": [a for a in s.INSTALLED_APPS if a.startswith("vstudio")],
}, sys.stdout)
"""


def load_settings(**overrides):
    """Импортирует core.settings в чистом процессе с заданным окружением."""
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(_OWN_ENV_PREFIXES) and k not in _OWN_ENV_NAMES}
    env.update(_REQUIRED_ENV)
    env["PYTHONPATH"] = str(BASE_DIR)
    env["PYTHONIOENCODING"] = "utf-8"
    with tempfile.TemporaryDirectory() as log_dir:
        env["APP_LOG_DIR"] = log_dir
        env.update({k: str(v) for k, v in overrides.items()})
        proc = subprocess.run(
            [sys.executable, "-c", _PROBE], cwd=str(BASE_DIR), env=env,
            capture_output=True, text=True, encoding="utf-8", timeout=120)
    if proc.returncode:
        raise AssertionError("settings.py не загрузился:\n" + proc.stderr[-3000:])
    return json.loads(proc.stdout)


def queue_of(routes, task_name):
    """Очередь, которую выберет Celery по словарю маршрутов (None — общая)."""
    route = MapRoute(routes)(task_name)
    return route["queue"] if route else None


class VstudioAppWiringTests(SimpleTestCase):
    def test_app_installed(self):
        from vstudio.apps import VstudioConfig

        self.assertIn("vstudio.apps.VstudioConfig", settings.INSTALLED_APPS)
        config = apps.get_app_config("vstudio")
        self.assertIsInstance(config, VstudioConfig)
        # Модели BE-2 зарегистрированы — значит, миграции и админка их видят.
        for name in ("Project", "Asset", "Shot", "ShotInput", "Take"):
            self.assertIsNotNone(apps.get_model("vstudio", name))

    def test_api_prefix_mounted_once(self):
        mounted = [p for p in get_resolver().url_patterns
                   if isinstance(p, URLResolver) and str(p.pattern) == "api/vstudio/"]
        self.assertEqual(len(mounted), 1)
        self.assertEqual(mounted[0].urlconf_module.__name__, "vstudio.urls")


class CeleryRoutingTests(SimpleTestCase):
    """Маршруты текущих настроек через настоящий Router приложения Celery."""

    def queue(self, task_name):
        from core.celery import app

        return app.amqp.router.route({}, task_name)["queue"].name

    def test_routes_always_a_dict(self):
        self.assertIsInstance(settings.CELERY_TASK_ROUTES, dict)

    def test_pipeline_tasks_go_to_studio_queue(self):
        expected = (settings.CELERY_VSTUDIO_QUEUE or settings.CELERY_MEDIA_QUEUE
                    or settings.CELERY_TASK_DEFAULT_QUEUE)
        for name in PIPELINE_TASKS:
            with self.subTest(task=name):
                self.assertEqual(self.queue(f"vstudio.tasks.{name}"), expected)

    def test_safety_net_goes_to_general_queue(self):
        # Точное имя важнее шаблона vstudio.tasks.*: sweep не должен зависеть
        # от воркера студии.
        for name in SAFETY_TASKS + SIDE_TASKS:
            with self.subTest(task=name):
                self.assertEqual(self.queue(f"vstudio.tasks.{name}"), "celery")

    def test_other_tasks_unchanged(self):
        self.assertEqual(self.queue("mails.tasks.send_mail_task"), "celery")
        self.assertEqual(self.queue("ai.tasks.recover_generations"), "celery")
        self.assertEqual(self.queue("ai.tasks.run_generation_job"),
                         settings.CELERY_MEDIA_QUEUE or "celery")
        self.assertEqual(self.queue("cartoon.tasks.render_scene"),
                         settings.CELERY_MEDIA_QUEUE or "celery")


class SettingsEnvTests(SimpleTestCase):
    """Разбор env в отдельном процессе: значения по умолчанию, переопределения,
    очереди при пустых переменных."""

    def test_defaults(self):
        s = load_settings()
        self.assertEqual(s["apps"], ["vstudio.apps.VstudioConfig"])
        self.assertEqual(s["mode"], "staff")
        self.assertEqual((s["max_open_video"], s["max_open_image"]), (2, 4))
        self.assertEqual(s["give_up_hours"], 6)
        self.assertIs(s["inline_refs"], False)
        self.assertEqual(s["min_provider_usd"], 2.0)
        self.assertEqual(s["assist_model"], "google/gemini-2.5-flash")
        self.assertEqual(s["purge_days"], 30)
        self.assertEqual(s["rates"], SCOPES)
        self.assertEqual((s["vstudio_queue"], s["media_queue"], s["default_queue"]),
                         ("vstudio", "media", "celery"))
        routes = s["routes"]
        for name in PIPELINE_TASKS:
            self.assertEqual(queue_of(routes, f"vstudio.tasks.{name}"), "vstudio")
        for name in SAFETY_TASKS + SIDE_TASKS:
            self.assertEqual(queue_of(routes, f"vstudio.tasks.{name}"), "celery")
        self.assertEqual(queue_of(routes, "ai.tasks.run_generation_job"), "media")
        self.assertIsNone(queue_of(routes, "mails.tasks.send_mail_task"))

    def test_overrides_and_bounds(self):
        s = load_settings(
            VSTUDIO_MODE=" ON ",
            VSTUDIO_MAX_OPEN_VIDEO=3,
            VSTUDIO_MAX_OPEN_IMAGE=-1,
            VSTUDIO_GIVE_UP_HOURS=0,
            VSTUDIO_INLINE_REFS=1,
            VSTUDIO_MIN_PROVIDER_USD="5.5",
            VSTUDIO_ASSIST_MODEL="openai/gpt-5.4-mini",
            VSTUDIO_PURGE_DAYS=0,
            DRF_THROTTLE_VSTUDIO_POLL="5/min",
            DRF_THROTTLE_VSTUDIO_ASSIST="3/hour",
            CELERY_VSTUDIO_QUEUE=" studio2 ",
        )
        self.assertEqual(s["mode"], "on")
        self.assertEqual((s["max_open_video"], s["max_open_image"]), (3, 0))
        # Ноль часов сдал бы в lost все ролики в работе, ноль дней стёр бы
        # удалённое сразу — нижние границы держат это.
        self.assertEqual(s["give_up_hours"], 1)
        self.assertEqual(s["purge_days"], 1)
        self.assertIs(s["inline_refs"], True)
        self.assertEqual(s["min_provider_usd"], 5.5)
        self.assertEqual(s["assist_model"], "openai/gpt-5.4-mini")
        self.assertEqual(s["rates"]["vstudio_poll"], "5/min")
        self.assertEqual(s["rates"]["vstudio_assist"], "3/hour")
        self.assertEqual(s["rates"]["vstudio_run"], "20/min")
        self.assertEqual(queue_of(s["routes"], "vstudio.tasks.poll_take"), "studio2")

    def test_unknown_mode_is_staff(self):
        for raw in ("yes", ""):
            with self.subTest(raw=raw):
                self.assertEqual(load_settings(VSTUDIO_MODE=raw)["mode"], "staff")
        self.assertEqual(load_settings(VSTUDIO_MODE="Off")["mode"], "off")

    def test_empty_studio_queue_falls_back_to_media(self):
        s = load_settings(CELERY_VSTUDIO_QUEUE="")
        for name in PIPELINE_TASKS:
            self.assertEqual(queue_of(s["routes"], f"vstudio.tasks.{name}"), "media")
        for name in SAFETY_TASKS + SIDE_TASKS:
            self.assertEqual(queue_of(s["routes"], f"vstudio.tasks.{name}"), "celery")

    def test_studio_routes_exist_without_media_queue(self):
        # Раньше словарь маршрутов жил только внутри «if media»: без media
        # маршруты студии пропали бы вместе с ним.
        s = load_settings(CELERY_MEDIA_QUEUE="")
        self.assertIsInstance(s["routes"], dict)
        self.assertEqual(queue_of(s["routes"], "vstudio.tasks.submit_take"), "vstudio")
        self.assertIsNone(queue_of(s["routes"], "ai.tasks.run_generation_job"))

    def test_local_stand_everything_in_general_queue(self):
        s = load_settings(CELERY_VSTUDIO_QUEUE="", CELERY_MEDIA_QUEUE="")
        for name in PIPELINE_TASKS + SAFETY_TASKS:
            self.assertEqual(queue_of(s["routes"], f"vstudio.tasks.{name}"), "celery")
        self.assertIsNone(queue_of(s["routes"], "cartoon.tasks.render_scene"))


class ThrottleScopeTests(SimpleTestCase):
    def test_scopes_registered_and_parse(self):
        rates = settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]
        throttle = ScopedRateThrottle()
        for scope in SCOPES:
            with self.subTest(scope=scope):
                num, duration = throttle.parse_rate(rates[scope])
                self.assertGreater(num, 0)
                self.assertGreater(duration, 0)

    def test_assist_scope_enforced(self):
        """Представление со scope vstudio_assist пускает ровно столько раз,
        сколько сказано в настройках, и не трогает общий лимит пользователя."""

        class AssistProbe(APIView):
            permission_classes = [AllowAny]
            throttle_classes = [ScopedRateThrottle]
            throttle_scope = "vstudio_assist"

            def post(self, request):
                return Response({"ok": True})

        limit, _ = ScopedRateThrottle().parse_rate(
            settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["vstudio_assist"])
        view = AssistProbe.as_view()
        user = SimpleNamespace(is_authenticated=True, pk=uuid.uuid4().int % 10**12)
        factory = APIRequestFactory()
        codes = []
        for _ in range(limit + 1):
            request = factory.post("/api/vstudio/assist/condense/", {}, format="json")
            force_authenticate(request, user=user)
            codes.append(view(request).status_code)
        self.assertEqual(codes[:limit], [200] * limit)
        self.assertEqual(codes[-1], 429)


class BeatScheduleTests(TestCase):
    def test_entries(self):
        schedule = settings.CELERY_BEAT_SCHEDULE
        sweep = schedule["vstudio:sweep_takes"]
        self.assertEqual(sweep["task"], "vstudio.tasks.sweep_takes")
        self.assertEqual(sweep["schedule"], timedelta(seconds=60))
        purge = schedule["vstudio:purge_assets"]
        self.assertEqual(purge["task"], "vstudio.tasks.purge_assets")
        self.assertIsInstance(purge["schedule"], crontab)
        self.assertEqual(purge["schedule"].hour, {4})
        self.assertEqual(purge["schedule"].minute, {30})

    def test_database_scheduler_accepts_entries(self):
        """Бой запускает beat с DatabaseScheduler: записи должны лечь в
        PeriodicTask ровно с нашим интервалом, временем и сроком годности."""
        from django_celery_beat.models import PeriodicTask
        from django_celery_beat.schedulers import ModelEntry

        from core.celery import app

        for name in ("vstudio:sweep_takes", "vstudio:purge_assets"):
            ModelEntry.from_entry(name, app=app, **settings.CELERY_BEAT_SCHEDULE[name])

        sweep = PeriodicTask.objects.get(name="vstudio:sweep_takes")
        self.assertEqual(sweep.task, "vstudio.tasks.sweep_takes")
        self.assertEqual((sweep.interval.every, sweep.interval.period), (60, "seconds"))
        self.assertEqual(sweep.expire_seconds, 50)
        self.assertEqual(ModelEntry(sweep, app=app).options.get("expires"), 50)

        purge = PeriodicTask.objects.get(name="vstudio:purge_assets")
        self.assertEqual(purge.task, "vstudio.tasks.purge_assets")
        self.assertEqual((purge.crontab.hour, purge.crontab.minute), ("4", "30"))


@skipUnless(yaml is not None and COMPOSE.exists(), "нет compose.yaml или PyYAML")
class ComposeWorkerTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with open(COMPOSE, encoding="utf-8") as fh:
            cls.services = yaml.safe_load(fh)["services"]

    @staticmethod
    def command(service):
        return " ".join(str(service["command"]).split())

    def test_celery_vstudio_service(self):
        svc = self.services["celery_vstudio"]
        cmd = self.command(svc)
        for part in ("celery -A core worker",
                     "-Q ${CELERY_VSTUDIO_QUEUE:-vstudio}",
                     "--pool=prefork",
                     "--concurrency=${CELERY_VSTUDIO_CONCURRENCY:-4}",
                     "--logfile=/app/logs/celery_vstudio.log",
                     "--pidfile=/tmp/celery_vstudio.pid"):
            with self.subTest(part=part):
                self.assertIn(part, cmd)
        self.assertEqual(svc["stop_grace_period"], "5m")
        self.assertEqual(svc["environment"]["RUN_MIGRATIONS"], "0")
        self.assertIn("celery_vstudio.pid", " ".join(svc["healthcheck"]["test"]))
        # Те же тома, что у celery_media: код, медиа и логи с диска.
        self.assertEqual(sorted(svc["volumes"]),
                         sorted(self.services["celery_media"]["volumes"]))

    def test_own_pid_and_log(self):
        media = self.command(self.services["celery_media"])
        self.assertNotIn("celery_vstudio", media)
        self.assertNotIn("celery_media", self.command(self.services["celery_vstudio"]))

    def test_general_worker_consumes_default_queue(self):
        # sweep_takes и purge_assets идут в очередь celery: её слушает воркер
        # celery без -Q.
        self.assertNotIn("-Q", self.command(self.services["celery"]))

    def test_next_build_arg_for_nav(self):
        args = self.services["next"]["build"]["args"]
        self.assertIn("NEXT_PUBLIC_VSTUDIO_NAV", args)


@skipUnless(ENV_EXAMPLE.exists(), "нет .env.example")
class EnvExampleTests(SimpleTestCase):
    def test_documents_studio_variables(self):
        text = ENV_EXAMPLE.read_text(encoding="utf-8")
        names = ["VSTUDIO_MODE", "CELERY_VSTUDIO_QUEUE", "CELERY_VSTUDIO_CONCURRENCY",
                 "VSTUDIO_MAX_OPEN_VIDEO", "VSTUDIO_MAX_OPEN_IMAGE", "VSTUDIO_GIVE_UP_HOURS",
                 "VSTUDIO_INLINE_REFS", "VSTUDIO_MIN_PROVIDER_USD", "VSTUDIO_ASSIST_MODEL",
                 "VSTUDIO_PURGE_DAYS", "NEXT_PUBLIC_VSTUDIO_NAV"]
        names += [f"DRF_THROTTLE_{scope.upper()}" for scope in SCOPES]
        for name in names:
            with self.subTest(name=name):
                self.assertIn(name, text)
