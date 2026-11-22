"""API /api/creative/: цена → запуск → конвейер → выдача, деньги, доступ, ответы без поставщика."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from decimal import Decimal

from django.core.files.storage import default_storage
from django.test import override_settings
from django.urls import reverse

from ai.models import GenerationLog
from creative.models import CreativeCharacter, CreativeJob, CreativeTool
from plans.models import TokenTransaction
from vstudio.reserve import total_reserved

from .helpers import CreativeTestCase, jpeg_bytes, make_user

# portrait 720p ×1: $0.094 × 1.40 / $0.01 = 13.16 → 14 кр
PORTRAIT = {"prompt": "портрет девушки в жёлтом худи", "resolution": "720p"}
PORTRAIT_CREDITS = 14


class ApiFlowTests(CreativeTestCase):
    def setUp(self):
        super().setUp()
        self.user = make_user(balance=100)
        self.client = self.client_for(self.user)

    def quote(self, tool="portrait", params=None):
        return self.client.post(reverse("creative:quote"), {"tool": tool, "params": params or PORTRAIT},
                                format="json")

    def run_job(self, tool="portrait", params=None, credits=PORTRAIT_CREDITS, cid="click-1"):
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(reverse("creative:run"),
                                    {"tool": tool, "params": params or PORTRAIT, "quoted_credits": credits,
                                     "client_request_id": cid}, format="json")

    def test_success_image_job_end_to_end(self):
        r = self.quote()
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["credits"], PORTRAIT_CREDITS)
        self.assertNotIn("cost_usd", r.json())
        self.assert_no_vendor(r.json())

        r = self.run_job()
        self.assertEqual(r.status_code, 201, r.content)
        self.assert_no_vendor(r.json())
        uid = r.json()["job"]["uid"]
        job = CreativeJob.objects.get(uid=uid)
        self.assertEqual(job.status, "queued")
        self.assertEqual(job.credits_reserved, PORTRAIT_CREDITS)
        self.assertEqual(total_reserved(self.user), PORTRAIT_CREDITS)
        self.assertIn(("submit_job", job.pk), self.enqueued)
        self.assertEqual(r.json()["balance"]["available"], 100 - PORTRAIT_CREDITS)

        results = self.drive(job)
        self.assertEqual(results, ["running", "saving", "done"])
        self.assertEqual(job.status, "done")
        self.assertEqual(job.charge_state, "charged")
        self.assertEqual(job.credits_charged, PORTRAIT_CREDITS)       # списано = цена на кнопке
        self.user.refresh_from_db()
        self.assertEqual(self.user.token_balance, 100 - PORTRAIT_CREDITS)
        tx = TokenTransaction.objects.get(user=self.user)
        self.assertEqual((tx.reason, tx.delta), ("creative_image", -PORTRAIT_CREDITS))
        # meta списания видит владелец (/api/plans/transactions/): себестоимости там нет
        self.assertNotIn("cost_usd", tx.meta)
        self.assertEqual(tx.meta["job"], job.uid)
        self.assertEqual(total_reserved(self.user), 0)

        # что ушло поставщику: ровно наши поля, ключ идемпотентности, без лишнего
        sub = self.fake.submits()
        self.assertEqual(len(sub), 1)
        self.assertEqual(sub[0]["body"], {"prompt": PORTRAIT["prompt"], "aspect_ratio": "3:4",
                                          "resolution": "720p", "batch_size": 1})
        self.assertEqual(sub[0]["idem"], job.idempotency_key)
        self.assertFalse(self.fake.auth_leaks)

        # файлы у нас, имена нейтральные
        self.assertEqual(len(job.result_files), 1)
        path = job.result_files[0]["path"]
        self.assertTrue(path.startswith(f"creative/{self.user.pk}/{job.uid}/1."))
        self.assertTrue(default_storage.exists(path))

        log = GenerationLog.objects.get(pk=job.genlog_id)
        self.assertEqual((log.source, log.provider, log.model, log.status),
                         ("creative", "cs", "creative/portrait", "delivered"))
        self.assertEqual(log.credits_charged, PORTRAIT_CREDITS)

        r = self.client.get(reverse("creative:job", args=[uid]))
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["status"], "done")
        self.assertTrue(data["results"][0]["url"].startswith("/media/creative/"))
        self.assert_no_vendor(data)
        r = self.client.get(reverse("creative:jobs"))
        self.assertEqual(r.json()["items"][0]["uid"], uid)
        self.assert_no_vendor(r.json())

    def test_same_client_request_id_creates_one_job(self):
        r1 = self.run_job(cid="dbl")
        r2 = self.run_job(cid="dbl")
        self.assertEqual(r1.status_code, 201)
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r1.json()["job"]["uid"], r2.json()["job"]["uid"])
        self.assertEqual(CreativeJob.objects.filter(user=self.user).count(), 1)
        self.assertEqual(total_reserved(self.user), PORTRAIT_CREDITS)

    def test_insufficient_credits_402_in_chat_format(self):
        poor = make_user(balance=5)
        client = self.client_for(poor)
        r = client.post(reverse("creative:run"), {"tool": "portrait", "params": PORTRAIT,
                                                  "quoted_credits": PORTRAIT_CREDITS,
                                                  "client_request_id": "x1"}, format="json")
        self.assertEqual(r.status_code, 402)
        body = r.json()
        self.assertEqual(body["error_code"], "insufficient_balance")
        self.assertEqual(body["balance_tokens"], 5)
        self.assertEqual(body["required_estimate"], PORTRAIT_CREDITS)
        self.assertFalse(CreativeJob.objects.filter(user=poor).exists())

    def test_reserve_counts_against_balance(self):
        user = make_user(balance=20)
        client = self.client_for(user)
        ok = client.post(reverse("creative:run"), {"tool": "portrait", "params": PORTRAIT,
                                                   "quoted_credits": PORTRAIT_CREDITS,
                                                   "client_request_id": "a"}, format="json")
        self.assertEqual(ok.status_code, 201)
        second = client.post(reverse("creative:run"), {"tool": "portrait", "params": PORTRAIT,
                                                       "quoted_credits": PORTRAIT_CREDITS,
                                                       "client_request_id": "b"}, format="json")
        self.assertEqual(second.status_code, 402)
        self.assertEqual(second.json()["reserved_credits"], PORTRAIT_CREDITS)

    def test_price_changed_409(self):
        r = self.client.post(reverse("creative:run"), {"tool": "portrait", "params": PORTRAIT,
                                                       "quoted_credits": PORTRAIT_CREDITS - 1,
                                                       "client_request_id": "pc"}, format="json")
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()["error_code"], "price_changed")
        self.assertEqual(r.json()["credits"], PORTRAIT_CREDITS)
        self.assertFalse(CreativeJob.objects.exists())

    def test_too_many_open(self):
        rich = make_user(balance=1000)
        client = self.client_for(rich)
        for n in range(3):
            r = client.post(reverse("creative:run"), {"tool": "portrait", "params": PORTRAIT,
                                                      "quoted_credits": PORTRAIT_CREDITS,
                                                      "client_request_id": f"o{n}"}, format="json")
            self.assertEqual(r.status_code, 201)
        r = client.post(reverse("creative:run"), {"tool": "portrait", "params": PORTRAIT,
                                                  "quoted_credits": PORTRAIT_CREDITS,
                                                  "client_request_id": "o4"}, format="json")
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()["error_code"], "too_many_open")

    def test_foreign_job_404(self):
        uid = self.run_job().json()["job"]["uid"]
        stranger = self.client_for(make_user(balance=10))
        for name, method in (("creative:job", "get"), ("creative:job-cancel", "post")):
            r = getattr(stranger, method)(reverse(name, args=[uid]))
            self.assertEqual(r.status_code, 404)
            self.assertEqual(r.json()["error_code"], "job_not_found")
        r = stranger.get(reverse("creative:job", args=["not-a-uid"]))
        self.assertEqual(r.status_code, 404)

    def test_validation_errors_422(self):
        r = self.client.post(reverse("creative:quote"),
                             {"tool": "motion-transfer", "params": {"resolution": "8k"}}, format="json")
        self.assertEqual(r.status_code, 422)
        body = r.json()
        self.assertEqual(body["error_code"], "bad_params")
        codes = {(e["field"], e["code"]) for e in body["errors"]}
        self.assertIn(("video", "required"), codes)
        self.assertIn(("resolution", "bad_value"), codes)
        self.assertIn(("consent", "consent_required"), codes)

        img = self.make_image(self.user)
        short = self.make_video(self.user, duration=2.5)
        r = self.client.post(reverse("creative:quote"),
                             {"tool": "motion-transfer", "params": {"video": short.uid, "image": img.uid,
                                                                    "consent": True}}, format="json")
        self.assertEqual(r.status_code, 422)
        self.assertIn(("video", "too_short"), {(e["field"], e["code"]) for e in r.json()["errors"]})

    def test_malformed_image_list_is_422_not_500(self):
        r = self.quote("ad-campaign", {"prompt": "p", "product_images": [{"a": 1}]})
        self.assertEqual(r.status_code, 422, r.content)
        self.assertEqual(r.json()["error_code"], "bad_params")
        self.assertIn({"field": "product_images", "code": "bad_type"},
                      [{"field": e["field"], "code": e["code"]} for e in r.json()["errors"]])

    def test_unknown_and_disabled_tool(self):
        r = self.quote(tool="nope")
        self.assertEqual(r.status_code, 404)
        CreativeTool.objects.create(slug="portrait", enabled=False)
        r = self.quote()
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json()["error_code"], "tool_disabled")

    def test_cancel_queued_releases(self):
        uid = self.run_job().json()["job"]["uid"]
        r = self.client.post(reverse("creative:job-cancel", args=[uid]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["job"]["status"], "canceled")
        self.assertEqual(total_reserved(self.user), 0)
        self.assertFalse(TokenTransaction.objects.exists())

    def test_cancel_refused_while_retry_may_have_reached_provider(self):
        """Таймаут после POST: задача ждёт повтора в нашей очереди, но поставщик мог её
        уже принять — отмена 409, резерв держится до повтора тем же ключом."""
        uid = self.run_job().json()["job"]["uid"]
        job = CreativeJob.objects.get(uid=uid)
        self.fake.submit_responses = [(504, {"detail": "gateway"})]
        self.assertEqual(self.drive(job, steps=("submit",)), ["retry"])
        self.assertEqual(job.status, "queued")
        r = self.client.post(reverse("creative:job-cancel", args=[uid]))
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()["error_code"], "already_submitted")
        job.refresh_from_db()
        self.assertEqual((job.status, job.charge_state), ("queued", "reserved"))
        self.assertEqual(self.drive(job, steps=("submit",)), ["running"])

    def test_cancel_running_in_provider_queue(self):
        uid = self.run_job().json()["job"]["uid"]
        job = CreativeJob.objects.get(uid=uid)
        self.drive(job, steps=("submit",))
        self.assertEqual(job.stage, "queued")
        r = self.client.post(reverse("creative:job-cancel", args=[uid]))
        self.assertEqual(r.status_code, 200)
        job.refresh_from_db()
        self.assertEqual((job.status, job.charge_state), ("canceled", "released"))
        # начатую у поставщика отменить нельзя
        uid2 = self.run_job(cid="c2").json()["job"]["uid"]
        job2 = CreativeJob.objects.get(uid=uid2)
        self.drive(job2, steps=("submit",))
        self.fake.cancel_status = 400
        r = self.client.post(reverse("creative:job-cancel", args=[uid2]))
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()["error_code"], "already_submitted")


class AccessTests(CreativeTestCase):
    @override_settings(CREATIVE_MODE="staff")
    def test_staff_mode(self):
        user = make_user(balance=50)
        r = self.client_for(user).post(reverse("creative:quote"), {"tool": "portrait", "params": PORTRAIT},
                                       format="json")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json()["error_code"], "creative_disabled")
        staff = make_user(balance=50, is_staff=True)
        r = self.client_for(staff).post(reverse("creative:quote"), {"tool": "portrait", "params": PORTRAIT},
                                        format="json")
        self.assertEqual(r.status_code, 200)

    @override_settings(CREATIVE_MODE="off")
    def test_tools_answers_in_any_mode(self):
        r = self.client.get(reverse("creative:tools"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["mode"], "off")
        self.assertFalse(r.json()["available"])
        self.assertEqual(len(r.json()["tools"]), 15)

    def test_tools_with_price_hints_and_no_vendor(self):
        user = make_user(balance=50)
        r = self.client_for(user).get(reverse("creative:tools"))
        data = r.json()
        self.assertTrue(data["available"])
        self.assertTrue(all(t["price_hint_credits"] for t in data["tools"]))
        self.assertEqual(data["balance"]["balance"], 50)
        self.assert_no_vendor(data)

    def test_runtime_mode_override(self):
        from adminapi.runtime import set_runtime

        set_runtime("creative_mode", "off")
        r = self.client_for(make_user(is_staff=True)).get(reverse("creative:characters"))
        self.assertEqual(r.status_code, 403)

    def test_guest_401(self):
        r = self.client.post(reverse("creative:quote"), {"tool": "portrait", "params": PORTRAIT}, format="json")
        self.assertEqual(r.status_code, 401)


class UploadApiTests(CreativeTestCase):
    def test_image_upload(self):
        user = make_user()
        from django.core.files.uploadedfile import SimpleUploadedFile

        f = SimpleUploadedFile("photo.jpg", jpeg_bytes(800, 600), content_type="image/jpeg")
        r = self.client_for(user).post(reverse("creative:uploads"), {"file": f, "kind": "image"},
                                       format="multipart")
        self.assertEqual(r.status_code, 201, r.content)
        data = r.json()
        self.assertEqual((data["kind"], data["w"], data["h"]), ("image", 800, 600))
        self.assertTrue(data["preview"].startswith("/media/creative/uploads/"))

    def test_image_bad_type(self):
        user = make_user()
        from django.core.files.uploadedfile import SimpleUploadedFile

        f = SimpleUploadedFile("doc.jpg", b"not an image at all", content_type="image/jpeg")
        r = self.client_for(user).post(reverse("creative:uploads"), {"file": f, "kind": "image"},
                                       format="multipart")
        self.assertEqual(r.status_code, 422)
        self.assertEqual(r.json()["error_code"], "unreadable")

    def test_video_upload_checks(self):
        from unittest import mock

        from django.core.files.uploadedfile import SimpleUploadedFile

        from merge.render import Probe

        user = make_user()
        head = b"\x00\x00\x00\x18ftypqt  " + b"\x00" * 200

        def probe(duration):
            return Probe(duration=duration, width=1280, height=720, audio=True, video=True, codec="h264",
                         video_streams=1, video_index=0, audio_index=1, frames=int(duration * 30))

        def fake_convert(src, dst, info, *, fmt):
            with open(dst, "wb") as fh:
                fh.write(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 300)
            return True

        def fake_poster(path, poster_path, info):
            with open(poster_path, "wb") as fh:
                fh.write(jpeg_bytes(32, 18))
            return True

        with mock.patch("creative.uploads.probe", return_value=probe(3.0)):
            f = SimpleUploadedFile("clip.mov", head, content_type="video/quicktime")
            r = self.client_for(user).post(reverse("creative:uploads"), {"file": f, "kind": "video"},
                                           format="multipart")
        self.assertEqual(r.status_code, 422)
        self.assertEqual(r.json()["error_code"], "too_short")
        self.assertEqual(default_storage.listdir(f"creative/uploads/{user.pk}")[1], [])

        with mock.patch("creative.uploads.probe", return_value=probe(6.0)), \
                mock.patch("creative.uploads.convert", side_effect=fake_convert), \
                mock.patch("creative.uploads.make_poster", side_effect=fake_poster):
            f = SimpleUploadedFile("clip.mov", head, content_type="video/quicktime")
            r = self.client_for(user).post(reverse("creative:uploads"), {"file": f, "kind": "video"},
                                           format="multipart")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["duration"], 6.0)
        files = default_storage.listdir(f"creative/uploads/{user.pk}")[1]
        self.assertTrue(any(n.endswith(".mp4") for n in files))
        self.assertFalse(any(".src." in n for n in files))      # исходник после перепаковки стёрт

        f = SimpleUploadedFile("clip.avi", head, content_type="video/x-msvideo")
        r = self.client_for(user).post(reverse("creative:uploads"), {"file": f, "kind": "video"},
                                       format="multipart")
        self.assertEqual(r.json()["error_code"], "bad_type")

    def _post_image(self, user):
        from django.core.files.uploadedfile import SimpleUploadedFile

        f = SimpleUploadedFile("photo.jpg", jpeg_bytes(80, 60), content_type="image/jpeg")
        return self.client_for(user).post(reverse("creative:uploads"), {"file": f, "kind": "image"},
                                          format="multipart")

    @override_settings(CREATIVE_UPLOAD_MAX_FILES=2, CREATIVE_UPLOAD_MAX_MB=2048)
    def test_upload_quota_per_user(self):
        user = make_user()
        self.assertEqual(self._post_image(user).status_code, 201)
        self.assertEqual(self._post_image(user).status_code, 201)
        r = self._post_image(user)
        self.assertEqual(r.status_code, 409, r.content)
        self.assertEqual((r.json()["error_code"], r.json()["max_files"], r.json()["files"]),
                         ("upload_quota", 2, 2))
        self.assertEqual(len(default_storage.listdir(f"creative/uploads/{user.pk}")[1]), 4)  # 2 фото + 2 превью
        # квота своя у каждого
        self.assertEqual(self._post_image(make_user()).status_code, 201)
        # загрузки старше срока хранения место не держат
        from datetime import timedelta

        from django.utils import timezone

        from creative.models import CreativeUpload

        CreativeUpload.objects.filter(user=user).update(created_at=timezone.now() - timedelta(days=8))
        self.assertEqual(self._post_image(user).status_code, 201)

    @override_settings(CREATIVE_UPLOAD_MAX_FILES=60, CREATIVE_UPLOAD_MAX_MB=1)
    def test_upload_quota_bytes(self):
        from creative.models import CreativeUpload

        user = make_user()
        CreativeUpload.objects.create(uid="f" * 32, user=user, kind="video", path="x.mp4", mime="video/mp4",
                                      bytes=1024 * 1024)
        r = self._post_image(user)
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()["error_code"], "upload_quota")

    def test_image_checks_free_disk(self):
        from unittest import mock

        user = make_user()
        with mock.patch("creative.uploads._room_for", return_value=False):
            r = self._post_image(user)
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.json()["error_code"], "storage_unavailable")

    @override_settings(CREATIVE_VIDEO_MAX_MB=200)
    def test_video_limit_capped_below_cloudflare(self):
        from creative import uploads

        self.assertEqual(uploads.video_max_bytes(), 90 * 1024 * 1024)

    def test_convert_does_not_wait_for_busy_slot(self):
        """Слот перекодирования занят — сразу upload_busy, поток не ждёт."""
        import time as _time
        from unittest import mock

        from creative import uploads
        from creative.errors import CreativeError
        from merge.render import Probe

        info = Probe(duration=6.0, width=1280, height=720, audio=False, video=True, codec="hevc",
                     video_streams=1, video_index=0, audio_index=None, frames=180)
        self.assertTrue(uploads._convert_slots.acquire(blocking=False))
        try:
            started = _time.monotonic()
            with mock.patch("creative.uploads._run") as run, self.assertRaises(CreativeError) as ctx:
                uploads.convert("/in.mov", "/out.mp4", info, fmt="mov")
            self.assertEqual(ctx.exception.code, "upload_busy")
            self.assertLess(_time.monotonic() - started, 2)
            run.assert_not_called()
        finally:
            uploads._convert_slots.release()

    def test_convert_timeout_is_bounded_and_refused(self):
        import subprocess
        from unittest import mock

        from creative import uploads
        from creative.errors import CreativeError
        from merge.render import Probe

        info = Probe(duration=30.0, width=3840, height=2160, audio=False, video=True, codec="hevc",
                     video_streams=1, video_index=0, audio_index=None, frames=900)
        timeout = subprocess.TimeoutExpired("ffmpeg", 75)
        with mock.patch("merge.render._run", side_effect=timeout) as run, \
                self.assertRaises(CreativeError) as ctx:
            uploads.convert("/in.mov", "/out.mp4", info, fmt="mov")
        self.assertEqual(ctx.exception.code, "too_heavy")
        self.assertLessEqual(run.call_args[0][1], uploads.CONVERT_BUDGET_S)
        self.assertLess(uploads.CONVERT_BUDGET_S, 100)
        # слот после отказа свободен
        self.assertTrue(uploads._convert_slots.acquire(blocking=False))
        uploads._convert_slots.release()

    def test_one_video_per_user_at_a_time(self):
        from django.core.cache import cache
        from django.core.files.uploadedfile import SimpleUploadedFile

        user = make_user()
        cache.add(f"creative:upload:video:{user.pk}", 1, 60)
        head = b"\x00\x00\x00\x18ftypqt  " + b"\x00" * 200
        f = SimpleUploadedFile("clip.mov", head, content_type="video/quicktime")
        r = self.client_for(user).post(reverse("creative:uploads"), {"file": f, "kind": "video"},
                                       format="multipart")
        self.assertEqual(r.status_code, 429)
        self.assertEqual(r.json()["error_code"], "upload_busy")

    def test_convert_command_is_strict_mp4(self):
        from creative.uploads import convert_cmd

        cmd = convert_cmd("/in.mov", "/out.mp4", fmt="mov", video_index=0, audio_index=1, remux=True)
        self.assertIn("-protocol_whitelist", cmd)
        self.assertEqual(cmd[cmd.index("-c:v") + 1], "copy")
        self.assertEqual(cmd[-3:], ["-f", "mp4", "/out.mp4"])
        self.assertIn("-map_metadata", cmd)
        cmd = convert_cmd("/in.webm", "/out.mp4", fmt="matroska", video_index=0, audio_index=None, remux=False)
        self.assertEqual(cmd[cmd.index("-c:v") + 1], "libx264")
        self.assertNotIn("-c:a", cmd)


class CharacterApiTests(CreativeTestCase):
    def test_soul_id_job_creates_character_and_is_usable(self):
        user = make_user(balance=1000)
        client = self.client_for(user)
        photos = [self.make_image(user) for _ in range(3)]
        params = {"name": "Айгуль", "photos": [p.uid for p in photos], "consent": True}
        q = client.post(reverse("creative:quote"), {"tool": "consistent-character", "params": params},
                        format="json").json()
        # $2.50 × 1.40 / $0.01 = 350 кр
        self.assertEqual(q["credits"], 350)
        with self.captureOnCommitCallbacks(execute=True):
            r = client.post(reverse("creative:run"), {"tool": "consistent-character", "params": params,
                                                      "quoted_credits": 350, "client_request_id": "sid"},
                            format="json")
        self.assertEqual(r.status_code, 201, r.content)
        job = CreativeJob.objects.get(uid=r.json()["job"]["uid"])
        ch = CreativeCharacter.objects.get(job=job)
        self.assertEqual((ch.status, ch.name), ("training", "Айгуль"))
        listed = client.get(reverse("creative:characters")).json()["items"]
        self.assertEqual(listed[0]["status"], "training")

        self.assertEqual(self.drive(job), ["running", "saving", "done"])
        ch.refresh_from_db()
        self.assertEqual(ch.status, "ready")
        self.assertTrue(ch.provider_id.startswith("char-"))
        self.assertTrue(ch.thumb_path.startswith(f"creative/{user.pk}/"))
        sent = [c for c in self.fake.calls if c["path"] == "/v1/custom-references"][0]["body"]
        self.assertEqual(sent["model_version"], "v2")
        self.assertNotIn("Айгуль", json.dumps(sent, ensure_ascii=False))
        self.assertEqual(len(sent["input_images"]), 3)
        self.assertTrue(all(i["image_url"].startswith("https://cdn.") for i in sent["input_images"]))
        tx = TokenTransaction.objects.get(user=user)
        self.assertEqual((tx.reason, tx.delta), ("creative_character", -350))
        listed = client.get(reverse("creative:characters")).json()
        self.assert_no_vendor(listed)

        # персонаж годится для «Создания по описанию»
        params = {"prompt": "в кафе", "character": ch.uid}
        credits = client.post(reverse("creative:quote"), {"tool": "text-to-image", "params": params},
                              format="json").json()["credits"]
        with self.captureOnCommitCallbacks(execute=True):
            r = client.post(reverse("creative:run"), {"tool": "text-to-image", "params": params,
                                                      "quoted_credits": credits, "client_request_id": "t2i"},
                            format="json")
        job2 = CreativeJob.objects.get(uid=r.json()["job"]["uid"])
        self.drive(job2, steps=("submit",))
        self.assertEqual(self.fake.submits()[-1]["body"]["custom_reference_id"], ch.provider_id)

        # скрыть — пропадает из списка
        r = client.post(reverse("creative:character-hide", args=[ch.uid]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(client.get(reverse("creative:characters")).json()["items"], [])


class HookTests(CreativeTestCase):
    SECRET = "whsec_" + base64.b64encode(b"0123456789abcdef0123456789abcdef").decode()

    def sign(self, raw: bytes, msg_id="msg_1", ts=None):
        ts = str(ts or int(time.time()))
        key = base64.b64decode(self.SECRET.removeprefix("whsec_"))
        sig = base64.b64encode(hmac.new(key, f"{msg_id}.{ts}.".encode() + raw, hashlib.sha256).digest()).decode()
        return {"HTTP_WEBHOOK_ID": msg_id, "HTTP_WEBHOOK_TIMESTAMP": ts, "HTTP_WEBHOOK_SIGNATURE": f"v1,{sig}"}

    def test_off_without_secret(self):
        r = self.client.post("/api/creative/hook/", data=b"{}", content_type="application/json")
        self.assertEqual(r.status_code, 404)

    def test_signed_event_pokes_running_job(self):
        user = make_user(balance=100)
        client = self.client_for(user)
        with self.captureOnCommitCallbacks(execute=True):
            uid = client.post(reverse("creative:run"), {"tool": "portrait", "params": PORTRAIT,
                                                        "quoted_credits": PORTRAIT_CREDITS,
                                                        "client_request_id": "h"}, format="json").json()["job"]["uid"]
        job = CreativeJob.objects.get(uid=uid)
        self.drive(job, steps=("submit",))
        raw = json.dumps({"request_id": job.provider_request_id, "status": "completed",
                          "payload": {"images": [{"url": "https://x/y.png"}]}}).encode()
        with override_settings(HF_WEBHOOK_SECRET=self.SECRET):
            r = self.client.post("/api/creative/hook/", data=raw, content_type="application/json",
                                 **self.sign(b"tampered"))
            self.assertEqual(r.status_code, 400)
            self.enqueued.clear()
            with self.captureOnCommitCallbacks(execute=True):
                r = self.client.post("/api/creative/hook/", data=raw, content_type="application/json",
                                     **self.sign(raw))
            self.assertEqual(r.status_code, 200)
            self.assertIn(("poll_job", job.pk), self.enqueued)
            r = self.client.post("/api/creative/hook", data=raw, content_type="application/json",
                                 **self.sign(raw))
            self.assertEqual(r.json()["status"], "duplicate")
            old = self.sign(raw, msg_id="msg_2", ts=int(time.time()) - 3600)
            r = self.client.post("/api/creative/hook/", data=raw, content_type="application/json", **old)
            self.assertEqual(r.status_code, 400)
