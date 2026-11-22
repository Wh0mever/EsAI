"""Общее для тестов Creative Studio: поддельный поставщик, фабрики, база тестов.

Настоящих сетевых вызовов нет: creative.hf ходит через httpx.MockTransport
(FakeProvider.handler). Любой запрос мимо подделки падает (DenyTransport).
Постановка задач Celery записывается, а не исполняется — шаги конвейера тесты
вызывают сами (как vstudio/tests/test_pipeline.py).
"""
from __future__ import annotations

import io
import itertools
import json
from decimal import Decimal
from unittest import mock

import httpx
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from ai.pricing import CreditBasis
from creative import hf
from creative.models import CreativeCharacter, CreativeJob, CreativeUpload
from vstudio.tests.factories import make_user, media_root  # noqa: F401 — реэкспорт для тестов

API_HOST = hf.ALLOWED_HOST
CDN = "https://cdn.provider-files.test"
UPLOAD = "https://upload.provider-files.test"
FAKE_KEY = "test-key-id:test-key-secret-0123456789"
# Слова, которых не должно быть ни в одном ответе сайта.
VENDOR_WORDS = ("higgsfield", "soul", "genjutsu", "cinema-studio", "cinema studio",
                "marketing-studio", "marketing studio", "ads-studio", "ads studio", "flare",
                "sunburst", "ai-influencer", "provider-files.test", FAKE_KEY)

_seq = itertools.count(1)


class _DenyAll(httpx.BaseTransport):
    def handle_request(self, request):
        raise AssertionError(f"неожиданный сетевой запрос в тесте: {request.method} {request.url.host}")


# С первого импорта тестов: ни один запрос к поставщику не уйдёт в настоящую сеть.
hf.set_transport(_DenyAll())


def png_bytes(w=64, h=48, color=(10, 120, 200)) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, format="PNG")
    return buf.getvalue()


def jpeg_bytes(w=640, h=480) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (w, h), (200, 100, 50)).save(buf, format="JPEG")
    return buf.getvalue()


class DenyTransport(httpx.BaseTransport):
    def handle_request(self, request):
        raise AssertionError(f"неожиданный сетевой запрос в тесте: {request.method} {request.url.host}")


class FakeProvider:
    """Поддельный API поставщика: запоминает запросы, отвечает по сценарию."""

    def __init__(self):
        self.calls: list[dict] = []
        self.auth_leaks: list[str] = []
        self.submit_responses: list = []      # очередь ответов на POST модели: (status, json)
        self.states: dict = {}                # request_id → статус ("completed" по умолчанию)
        self.outputs: dict = {}               # request_id → число картинок / "video"
        self.cancel_status = 202
        self.char_state = "completed"
        self.catalogs: dict = {}
        self._n = itertools.count(1)

    # --- маршрутизатор
    def handler(self, request: httpx.Request) -> httpx.Response:
        url = request.url
        host = url.host
        auth = request.headers.get("authorization")
        if host != API_HOST and auth:
            self.auth_leaks.append(str(url))
        body = None
        if request.method in ("POST", "PUT") and request.headers.get("content-type", "").startswith(
                "application/json"):
            try:
                body = json.loads(request.content or b"{}")
            except ValueError:
                body = None
        self.calls.append({"method": request.method, "host": host, "path": url.path,
                           "query": str(url.query, "utf-8") if isinstance(url.query, bytes) else str(url.query),
                           "body": body, "idem": request.headers.get("idempotency-key"),
                           "auth": bool(auth)})
        if host == API_HOST:
            if auth != f"Key {FAKE_KEY}":
                return httpx.Response(401, json={"detail": "Invalid credentials"})
            return self._api(request, url.path, body)
        if url.host == httpx.URL(UPLOAD).host:
            return httpx.Response(200)
        if url.host == httpx.URL(CDN).host:
            if url.path.endswith(".mp4"):
                return httpx.Response(200, content=b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 2000)
            return httpx.Response(200, content=png_bytes())
        return httpx.Response(404)

    def _api(self, request, path: str, body) -> httpx.Response:
        if path == "/files/generate-upload-url":
            n = next(self._n)
            ct = (body or {}).get("content_type", "image/jpeg")
            return httpx.Response(200, json={"public_url": f"{CDN}/in/{n}", "upload_url": f"{UPLOAD}/put/{n}",
                                             "content_type": ct,
                                             "upload_headers": {"Content-Type": ct,
                                                                "x-amz-tagging": "retention=temporary"}})
        if path == "/v1/custom-references" and request.method == "POST":
            cid = f"char-{next(self._n)}"
            return httpx.Response(200, json={"id": cid, "status": "queued", "thumbnail_url": None})
        if path.startswith("/v1/custom-references/"):
            cid = path.rsplit("/", 1)[-1]
            return httpx.Response(200, json={"id": cid, "status": self.char_state,
                                             "thumbnail_url": f"{CDN}/thumb/{cid}.png"})
        if path.startswith("/requests/") and path.endswith("/status"):
            rid = path.split("/")[2]
            state = self.states.get(rid, "completed")
            data = {"status": state, "request_id": rid, "error": None}
            if state == "completed":
                out = self.outputs.get(rid, 1)
                if out == "video":
                    data["video"] = {"url": f"{CDN}/r/{rid}/v.mp4"}
                else:
                    data["images"] = [{"url": f"{CDN}/r/{rid}/{i}.png"} for i in range(int(out))]
            return httpx.Response(200, json=data)
        if path.startswith("/requests/") and path.endswith("/cancel"):
            return httpx.Response(self.cancel_status)
        if path.startswith("/v1/text2image/soul-styles") or path.startswith("/models/") \
                or path.startswith("/marketing-studio/image/presets"):
            data = self.catalogs.get(path)
            if data is None:
                return httpx.Response(404, json={"detail": "nope"})
            return httpx.Response(200, json=data)
        # POST модели
        if request.method == "POST":
            if self.submit_responses:
                status, payload = self.submit_responses.pop(0)
                return httpx.Response(status, json=payload)
            rid = f"req-{next(self._n)}"
            return httpx.Response(200, json={"status": "queued", "request_id": rid,
                                             "status_url": f"https://{API_HOST}/requests/{rid}/status",
                                             "cancel_url": f"https://{API_HOST}/requests/{rid}/cancel"})
        return httpx.Response(404, json={"detail": "model_not_found"})

    # --- выборки
    def submits(self) -> list[dict]:
        return [c for c in self.calls if c["host"] == API_HOST and c["method"] == "POST"
                and not c["path"].startswith(("/files/", "/requests/", "/estimate/"))]


BASIS = CreditBasis(numer=Decimal("1"), denom=Decimal("100"), package_name="test", currency="USD",
                    price=Decimal("1"), credits=100, kgs_per_usd=None, rate_source="")


@override_settings(HF_KEY=FAKE_KEY, HF_WEBHOOK_SECRET="", CREATIVE_MODE="on", SITE_BASE_URL="https://esai.test",
                   CREATIVE_MEDIA_EXTRA_HOSTS=["cdn.provider-files.test", "f", "x"],
                   CREATIVE_MAX_PARALLEL=4, CREATIVE_MAX_OPEN_PER_USER=3)
class CreativeTestCase(TestCase):
    """База: временный MEDIA_ROOT, подделка поставщика, цена кредита $0.01, без пушей."""

    def setUp(self):
        super().setUp()
        cache.clear()
        self._media = media_root()
        self.media_path = self._media.__enter__()
        self.addCleanup(self._media.__exit__, None, None, None)
        self.fake = FakeProvider()
        hf.set_transport(httpx.MockTransport(self.fake.handler))
        self.addCleanup(hf.set_transport, DenyTransport())
        self.enqueued: list[tuple] = []
        patches = [
            mock.patch("creative.pipeline._enqueue", side_effect=self._record),
            mock.patch("ai.pricing.credit_basis", return_value=BASIS),
            mock.patch("vstudio.storage_check._free_bytes", return_value=50 * 1024 ** 3),
            mock.patch("users.webpush.notify_user", return_value=None),
            mock.patch("creative.uploads._room_for", return_value=True),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def _record(self, task_name, job_id, *, countdown=None):
        self.enqueued.append((task_name, job_id))
        return True

    # --- фабрики
    def client_for(self, user) -> APIClient:
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def make_image(self, user, *, w=1024, h=1024) -> CreativeUpload:
        uid = f"{next(_seq):032x}"
        path = default_storage.save(f"creative/uploads/{user.pk}/{uid}.jpg", ContentFile(jpeg_bytes(64, 64)))
        return CreativeUpload.objects.create(uid=uid, user=user, kind="image", path=path, mime="image/jpeg",
                                             bytes=100, w=w, h=h)

    def make_video(self, user, *, duration=4.0, w=854, h=480) -> CreativeUpload:
        uid = f"{next(_seq):032x}"
        path = default_storage.save(f"creative/uploads/{user.pk}/{uid}.mp4",
                                    ContentFile(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 100))
        return CreativeUpload.objects.create(uid=uid, user=user, kind="video", path=path, mime="video/mp4",
                                             bytes=120, w=w, h=h, duration_s=duration)

    def make_character(self, user, *, status="ready", provider_id="char-ready-1") -> CreativeCharacter:
        return CreativeCharacter.objects.create(user=user, name="Герой", status=status, provider_id=provider_id)

    # --- шаги конвейера
    def due(self, job):
        CreativeJob.objects.filter(pk=job.pk).update(next_poll_at=None, lease_until=None)

    def drive(self, job, *, steps=("submit", "poll", "finalize")):
        from creative import pipeline

        out = []
        for step in steps:
            self.due(job)
            out.append(getattr(pipeline, step)(job.pk))
        job.refresh_from_db()
        return out

    def assert_no_vendor(self, payload):
        text = json.dumps(payload, ensure_ascii=False).lower()
        for word in VENDOR_WORDS:
            self.assertNotIn(word.lower(), text, f"в ответе нашлось «{word}»")
