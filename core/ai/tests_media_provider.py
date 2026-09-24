# -*- coding: utf-8 -*-
"""HTTP-клиент OpenRouter для медиа (ai.media_provider): провайдер подменён.

Главное здесь — три исхода отправки видео. «Нет ответа» и 5xx — это не отказ,
а неизвестный исход: провайдер мог принять и взять деньги (21.09.2026).
"""
import base64
import inspect
import os
import shutil
import tempfile
from unittest.mock import MagicMock, patch

import requests
from django.test import SimpleTestCase

from . import generation, media_provider, recovery
from .media_provider import (
    DownloadError,
    ImageItem,
    download_to_file,
    generate_image,
    poll_video,
    submit_video,
)
from .provider_errors import explain_image_error, explain_video_error

CFG = {"api_key": "sk-test", "base_url": "http://provider/api/v1/",
       "referer": "https://esai.kg", "title": "ESAI"}
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
SVG = b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg"><script>x</script></svg>'


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


def _resp(status=200, payload=None, *, text=None, chunks=None, headers=None, json_error=False):
    r = MagicMock()
    r.status_code = status
    r.text = text if text is not None else str(payload if payload is not None else "")
    if json_error:
        r.json.side_effect = ValueError("not json")
    else:
        r.json.return_value = payload
    r.headers = headers or {}
    r.iter_content = lambda chunk_size=0: iter(chunks or [])
    return r


class _CfgMixin:
    def setUp(self):
        super().setUp()
        p = patch("ai.handlers._openrouter_config", return_value=dict(CFG))
        self.cfg = p.start()
        self.addCleanup(p.stop)


class SubmitVideoTests(_CfgMixin, SimpleTestCase):
    BODY = {"model": "bytedance/seedance-2.0", "prompt": "кот идёт по крыше", "duration": 5,
            "resolution": "480p",
            "input_references": [{"type": "image_url", "image_url": {"url": "https://x/a.jpg"}}]}

    def test_accepted_with_polling_url(self):
        body = {k: v for k, v in self.BODY.items()}
        with patch("requests.post", return_value=_resp(202, {
                "id": "gen-vid-1", "polling_url": "http://provider/api/v1/videos/gen-vid-1",
                "status": "pending"})) as post:
            res = submit_video(body)
        self.assertEqual(res.state, "accepted")
        self.assertTrue(res.accepted)
        self.assertEqual(res.job_id, "gen-vid-1")
        self.assertEqual(res.polling_url, "http://provider/api/v1/videos/gen-vid-1")
        self.assertEqual(res.status_code, 202)
        args, kwargs = post.call_args
        self.assertEqual(args[0], "http://provider/api/v1/videos")
        self.assertEqual(kwargs["json"], self.BODY)
        self.assertEqual(kwargs["timeout"], (10, 150))
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer sk-test")
        self.assertEqual(kwargs["headers"]["HTTP-Referer"], "https://esai.kg")
        # Тело не меняется: вызывающий хранит его как request_body дубля.
        self.assertEqual(body, self.BODY)

    def test_polling_url_is_built_from_id(self):
        with patch("requests.post", return_value=_resp(200, {"id": "gen-7"})):
            res = submit_video(self.BODY)
        self.assertEqual(res.state, "accepted")
        self.assertEqual(res.polling_url, "http://provider/api/v1/videos/gen-7")

    def test_generation_id_is_accepted_as_id(self):
        with patch("requests.post", return_value=_resp(200, {"generation_id": "gen-8"})):
            res = submit_video(self.BODY)
        self.assertEqual(res.job_id, "gen-8")
        self.assertEqual(res.polling_url, "http://provider/api/v1/videos/gen-8")

    def test_polling_url_without_id_is_still_accepted(self):
        with patch("requests.post", return_value=_resp(202, {"polling_url": "http://provider/p/9"})):
            res = submit_video(self.BODY)
        self.assertEqual(res.state, "accepted")
        self.assertEqual(res.job_id, "")
        self.assertEqual(res.polling_url, "http://provider/p/9")

    def test_custom_timeout_is_passed(self):
        with patch("requests.post", return_value=_resp(200, {"id": "g"})) as post:
            submit_video(self.BODY, timeout=(3, 30))
        self.assertEqual(post.call_args.kwargs["timeout"], (3, 30))

    def test_4xx_is_rejected_with_provider_text(self):
        raw = ('{"error":{"code":"InputImageSensitiveContentDetected.PrivacyInformation",'
               '"message":"may contain real person"}}')
        with patch("requests.post", return_value=_resp(400, text=raw)):
            res = submit_video(self.BODY)
        self.assertEqual(res.state, "rejected")
        self.assertFalse(res.accepted)
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.text, raw)
        # Текст годится для разбора ошибки как есть.
        self.assertEqual(explain_video_error(res.text)[1], "image_real_person")

    def test_402_and_429_are_rejected(self):
        for code in (402, 429):
            with patch("requests.post", return_value=_resp(code, text=f'{{"code":{code}}}')):
                res = submit_video(self.BODY)
            self.assertEqual(res.state, "rejected", code)
            self.assertEqual(res.status_code, code)

    def test_5xx_is_unknown_not_rejected(self):
        for code in (500, 502, 504, 524):
            with patch("requests.post", return_value=_resp(code, text="gateway timeout")):
                res = submit_video(self.BODY)
            self.assertEqual(res.state, "unknown", code)
            self.assertEqual(res.status_code, code)
            self.assertEqual(res.text, "gateway timeout")

    def test_timeout_is_unknown(self):
        with patch("requests.post", side_effect=requests.ReadTimeout("read timed out")):
            res = submit_video(self.BODY)
        self.assertEqual(res.state, "unknown")
        self.assertIsNone(res.status_code)
        self.assertIn("ReadTimeout", res.text)

    def test_connection_error_is_unknown(self):
        with patch("requests.post", side_effect=requests.ConnectionError("reset")):
            res = submit_video(self.BODY)
        self.assertEqual(res.state, "unknown")

    def test_2xx_without_id_is_unknown(self):
        with patch("requests.post", return_value=_resp(200, {"status": "pending"})):
            res = submit_video(self.BODY)
        self.assertEqual(res.state, "unknown")
        self.assertEqual(res.status_code, 200)

    def test_2xx_not_json_is_unknown(self):
        with patch("requests.post", return_value=_resp(200, text="<html>", json_error=True)):
            res = submit_video(self.BODY)
        self.assertEqual(res.state, "unknown")
        self.assertEqual(res.text, "<html>")

    def test_2xx_json_list_is_unknown(self):
        with patch("requests.post", return_value=_resp(200, ["gen-1"])):
            res = submit_video(self.BODY)
        self.assertEqual(res.state, "unknown")

    def test_no_api_key_sends_nothing(self):
        self.cfg.return_value = {**CFG, "api_key": ""}
        with patch("requests.post") as post:
            res = submit_video(self.BODY)
        post.assert_not_called()
        self.assertEqual(res.state, "rejected")
        self.assertIsNone(res.status_code)

    def test_long_provider_text_is_capped(self):
        with patch("requests.post", return_value=_resp(400, text="x" * 50000)):
            res = submit_video(self.BODY)
        self.assertEqual(len(res.text), media_provider.MAX_TEXT)

    def test_accepted_is_logged_before_caller_writes_db(self):
        with patch("requests.post", return_value=_resp(200, {"id": "gen-log"})), \
                self.assertLogs("ai.media_provider", level="INFO") as logs:
            submit_video(self.BODY)
        self.assertTrue(any("gen-log" in line for line in logs.output))


class PollVideoTests(_CfgMixin, SimpleTestCase):
    URL = "http://provider/api/v1/videos/gen-1"

    def test_completed_with_urls_and_cost(self):
        payload = {"status": "completed", "usage": {"cost": 0.42},
                   "unsigned_urls": ["http://provider/api/v1/videos/gen-1/content?index=0"]}
        with patch("requests.get", return_value=_resp(200, payload)) as get:
            res = poll_video(self.URL)
        self.assertEqual(res.status, "completed")
        self.assertTrue(res.is_ready)
        self.assertFalse(res.is_failed)
        self.assertFalse(res.transient)
        self.assertEqual(res.urls, payload["unsigned_urls"])
        self.assertEqual(res.cost, 0.42)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(get.call_args.kwargs["timeout"], (5, 20))
        self.assertEqual(get.call_args.kwargs["headers"], {"Authorization": "Bearer sk-test"})

    def test_in_progress(self):
        with patch("requests.get", return_value=_resp(200, {"status": "IN_PROGRESS"})):
            res = poll_video(self.URL)
        self.assertEqual(res.status, "in_progress")
        self.assertFalse(res.is_ready)
        self.assertFalse(res.is_failed)
        self.assertFalse(res.transient)
        self.assertIsNone(res.cost)

    def test_completed_without_urls_is_not_ready(self):
        with patch("requests.get", return_value=_resp(200, {"status": "completed"})):
            res = poll_video(self.URL)
        self.assertEqual(res.status, "completed")
        self.assertFalse(res.is_ready)

    def test_non_http_urls_are_dropped(self):
        payload = {"status": "completed", "unsigned_urls": ["file:///etc/passwd", 7, "https://ok/v"]}
        with patch("requests.get", return_value=_resp(200, payload)):
            res = poll_video(self.URL)
        self.assertEqual(res.urls, ["https://ok/v"])

    def test_failed_states(self):
        for status in ("failed", "cancelled", "canceled", "expired", "error"):
            with patch("requests.get", return_value=_resp(200, {"status": status})):
                res = poll_video(self.URL)
            self.assertTrue(res.is_failed, status)
            self.assertFalse(res.transient, status)

    def test_error_object_becomes_text(self):
        payload = {"status": "failed",
                   "error": {"message": "may contain real person", "code": "PrivacyInformation"}}
        with patch("requests.get", return_value=_resp(200, payload)):
            res = poll_video(self.URL)
        self.assertIn("may contain real person", res.error)
        self.assertIn("PrivacyInformation", res.error)
        self.assertEqual(explain_video_error(res.error)[1], "image_real_person")

    def test_error_string_is_kept(self):
        with patch("requests.get", return_value=_resp(200, {"status": "failed", "error": "boom"})):
            res = poll_video(self.URL)
        self.assertEqual(res.error, "boom")

    def test_network_error_is_transient(self):
        with patch("requests.get", side_effect=requests.ConnectionError("dns")):
            res = poll_video(self.URL)
        self.assertTrue(res.transient)
        self.assertEqual(res.status, "")
        self.assertFalse(res.is_failed)
        self.assertIsNone(res.status_code)

    def test_http_errors_are_transient_not_failed(self):
        for code in (401, 404, 429, 500, 502):
            with patch("requests.get", return_value=_resp(code, {"status": "failed"},
                                                          text="err")):
                res = poll_video(self.URL)
            self.assertTrue(res.transient, code)
            self.assertFalse(res.is_failed, code)
            self.assertEqual(res.status_code, code)

    def test_not_json_is_transient(self):
        with patch("requests.get", return_value=_resp(200, text="<html>", json_error=True)):
            res = poll_video(self.URL)
        self.assertTrue(res.transient)

    def test_cost_garbage_is_none(self):
        for usage in ({"cost": "abc"}, {"cost": None}, "0.5", None):
            with patch("requests.get", return_value=_resp(200, {"status": "completed",
                                                                "usage": usage})):
                self.assertIsNone(poll_video(self.URL).cost, usage)
        with patch("requests.get", return_value=_resp(200, {"usage": {"cost": "0.5"}})):
            self.assertEqual(poll_video(self.URL).cost, 0.5)

    def test_bad_url_makes_no_request(self):
        with patch("requests.get") as get:
            res = poll_video("javascript:alert(1)")
        get.assert_not_called()
        self.assertTrue(res.transient)

    def test_key_goes_only_to_openrouter(self):
        with patch("requests.get", return_value=_resp(200, {"status": "pending"})) as get:
            poll_video("https://evil.example/videos/1")
        self.assertEqual(get.call_args.kwargs["headers"], {})
        with patch("requests.get", return_value=_resp(200, {"status": "pending"})) as get:
            poll_video("https://openrouter.ai/api/v1/videos/1")
        self.assertEqual(get.call_args.kwargs["headers"], {"Authorization": "Bearer sk-test"})
        with patch("requests.get", return_value=_resp(200, {"status": "pending"})) as get:
            poll_video("https://openrouter.ai.evil.example/videos/1")
        self.assertEqual(get.call_args.kwargs["headers"], {})


class DownloadToFileTests(_CfgMixin, SimpleTestCase):
    URL = "http://provider/api/v1/videos/gen-1/content?index=0"

    def setUp(self):
        super().setUp()
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.dest = os.path.join(self.dir, "out.mp4")

    def test_streams_to_file_with_bearer(self):
        chunks = [b"a" * 10, b"", b"b" * 5]
        with patch("requests.get", return_value=_resp(200, chunks=chunks)) as get:
            n = download_to_file(self.URL, self.dest, max_bytes=100, wall_s=180)
        self.assertEqual(n, 15)
        with open(self.dest, "rb") as fh:
            self.assertEqual(fh.read(), b"a" * 10 + b"b" * 5)
        kwargs = get.call_args.kwargs
        self.assertTrue(kwargs["stream"])
        self.assertEqual(kwargs["headers"], {"Authorization": "Bearer sk-test"})
        self.assertEqual(kwargs["timeout"], (10, 60))

    def test_short_wall_limits_read_timeout(self):
        with patch("requests.get", return_value=_resp(200, chunks=[b"x"])) as get:
            download_to_file(self.URL, self.dest, max_bytes=100, wall_s=20)
        self.assertEqual(get.call_args.kwargs["timeout"], (10, 20.0))

    def test_http_error(self):
        with patch("requests.get", return_value=_resp(401, chunks=[b"nope"])):
            with self.assertRaises(DownloadError) as ctx:
                download_to_file(self.URL, self.dest, max_bytes=100, wall_s=180)
        self.assertEqual(ctx.exception.reason, "http")
        self.assertEqual(ctx.exception.status_code, 401)
        self.assertFalse(os.path.exists(self.dest))

    def test_declared_size_over_limit_is_refused_before_reading(self):
        resp = _resp(200, chunks=[b"x"], headers={"Content-Length": "1000"})
        with patch("requests.get", return_value=resp):
            with self.assertRaises(DownloadError) as ctx:
                download_to_file(self.URL, self.dest, max_bytes=100, wall_s=180)
        self.assertEqual(ctx.exception.reason, "too_large")
        self.assertFalse(os.path.exists(self.dest))

    def test_stream_over_limit_removes_partial_file(self):
        with patch("requests.get", return_value=_resp(200, chunks=[b"x" * 60, b"y" * 60])):
            with self.assertRaises(DownloadError) as ctx:
                download_to_file(self.URL, self.dest, max_bytes=100, wall_s=180)
        self.assertEqual(ctx.exception.reason, "too_large")
        self.assertFalse(os.path.exists(self.dest))

    def test_wall_clock_limit(self):
        clock = MagicMock()
        clock.monotonic.side_effect = [0.0, 1.0, 50.0]
        with patch("requests.get", return_value=_resp(200, chunks=[b"a", b"b", b"c"])), \
                patch("ai.media_provider.time", clock):
            with self.assertRaises(DownloadError) as ctx:
                download_to_file(self.URL, self.dest, max_bytes=100, wall_s=30)
        self.assertEqual(ctx.exception.reason, "timeout")
        self.assertFalse(os.path.exists(self.dest))

    def test_empty_body(self):
        with patch("requests.get", return_value=_resp(200, chunks=[])):
            with self.assertRaises(DownloadError) as ctx:
                download_to_file(self.URL, self.dest, max_bytes=100, wall_s=180)
        self.assertEqual(ctx.exception.reason, "empty")
        self.assertFalse(os.path.exists(self.dest))

    def test_network_error_on_connect(self):
        with open(self.dest, "wb") as fh:
            fh.write(b"caller's file")
        with patch("requests.get", side_effect=requests.ConnectTimeout("slow")):
            with self.assertRaises(DownloadError) as ctx:
                download_to_file(self.URL, self.dest, max_bytes=100, wall_s=180)
        self.assertEqual(ctx.exception.reason, "network")
        # Не наш файл — не трогаем: писать в него мы так и не начали.
        self.assertTrue(os.path.exists(self.dest))

    def test_broken_stream_is_network_error(self):
        def broken(chunk_size=0):
            yield b"a" * 10
            raise requests.exceptions.ChunkedEncodingError("reset")

        resp = _resp(200)
        resp.iter_content = broken
        with patch("requests.get", return_value=resp):
            with self.assertRaises(DownloadError) as ctx:
                download_to_file(self.URL, self.dest, max_bytes=100, wall_s=180)
        self.assertEqual(ctx.exception.reason, "network")
        self.assertFalse(os.path.exists(self.dest))

    def test_bad_scheme_makes_no_request(self):
        with patch("requests.get") as get:
            with self.assertRaises(DownloadError) as ctx:
                download_to_file("file:///etc/passwd", self.dest, max_bytes=100, wall_s=10)
        get.assert_not_called()
        self.assertEqual(ctx.exception.reason, "bad_url")

    def test_foreign_host_gets_no_key(self):
        with patch("requests.get", return_value=_resp(200, chunks=[b"x"])) as get:
            download_to_file("https://cdn.example/v.mp4", self.dest, max_bytes=100, wall_s=10)
        self.assertEqual(get.call_args.kwargs["headers"], {})


class GenerateImageTests(_CfgMixin, SimpleTestCase):
    BODY = {"model": "google/gemini-2.5-flash-image", "prompt": "кот", "aspect_ratio": "9:16"}

    def test_success(self):
        payload = {"data": [{"b64_json": _b64(PNG), "media_type": "image/png"}],
                   "usage": {"cost": 0.039}}
        body = dict(self.BODY)
        with patch("requests.post", return_value=_resp(200, payload)) as post:
            res = generate_image(body)
        self.assertTrue(res.ok)
        self.assertEqual(res.error, "")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.cost, 0.039)
        self.assertEqual(len(res.items), 1)
        self.assertEqual(res.items[0].media_type, "image/png")
        self.assertEqual(res.items[0].decode(), PNG)
        args, kwargs = post.call_args
        self.assertEqual(args[0], "http://provider/api/v1/images")
        self.assertEqual(kwargs["json"], self.BODY)
        self.assertEqual(kwargs["timeout"], (10, 180))
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer sk-test")
        self.assertEqual(body, self.BODY)

    def test_media_type_is_normalized(self):
        payload = {"data": [{"b64_json": _b64(JPEG), "media_type": "IMAGE/JPG; q=1"},
                            {"b64": _b64(PNG)}]}
        with patch("requests.post", return_value=_resp(200, payload)):
            res = generate_image(self.BODY)
        self.assertEqual([i.media_type for i in res.items], ["image/jpeg", "image/png"])

    def test_data_url_payload(self):
        payload = {"data": [{"b64_json": "data:image/webp;base64," + _b64(PNG)}]}
        with patch("requests.post", return_value=_resp(200, payload)):
            res = generate_image(self.BODY)
        self.assertEqual(res.items[0].media_type, "image/webp")
        self.assertEqual(res.items[0].decode(), PNG)

    def test_svg_is_rejected(self):
        payload = {"data": [{"b64_json": _b64(SVG), "media_type": "image/svg+xml"}],
                   "usage": {"cost": 0.01}}
        with patch("requests.post", return_value=_resp(200, payload)):
            res = generate_image(self.BODY)
        self.assertFalse(res.ok)
        self.assertEqual(res.items, [])
        self.assertIn("svg", res.error)
        # Провайдер своё взял — себестоимость не теряем.
        self.assertEqual(res.cost, 0.01)

    def test_svg_disguised_as_png_is_rejected(self):
        for raw in (SVG, b"\xef\xbb\xbf  <svg/>", b"<html><body>x</body></html>"):
            payload = {"data": [{"b64_json": _b64(raw), "media_type": "image/png"}]}
            with patch("requests.post", return_value=_resp(200, payload)):
                res = generate_image(self.BODY)
            self.assertFalse(res.ok, raw)
            self.assertIn("markup", res.error)

    def test_non_image_media_type_is_rejected(self):
        payload = {"data": [{"b64_json": _b64(PNG), "media_type": "text/html"}]}
        with patch("requests.post", return_value=_resp(200, payload)):
            res = generate_image(self.BODY)
        self.assertFalse(res.ok)

    def test_svg_next_to_png_keeps_only_png(self):
        payload = {"data": [{"b64_json": _b64(SVG), "media_type": "image/svg+xml"},
                            {"b64_json": _b64(PNG), "media_type": "image/png"}]}
        with patch("requests.post", return_value=_resp(200, payload)):
            res = generate_image(self.BODY)
        self.assertTrue(res.ok)
        self.assertEqual([i.decode() for i in res.items], [PNG])

    def test_4xx_keeps_provider_text(self):
        raw = '{"error":{"message":"Request blocked by content policy moderation"}}'
        with patch("requests.post", return_value=_resp(400, text=raw)):
            res = generate_image(self.BODY)
        self.assertFalse(res.ok)
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.error, raw)
        self.assertEqual(explain_image_error(res.error)[1], "prompt_rejected")

    def test_5xx_is_error(self):
        with patch("requests.post", return_value=_resp(503, text="")):
            res = generate_image(self.BODY)
        self.assertFalse(res.ok)
        self.assertEqual(res.status_code, 503)
        self.assertEqual(res.error, "http 503")

    def test_exception_is_error_not_raise(self):
        with patch("requests.post", side_effect=requests.ReadTimeout("slow")):
            res = generate_image(self.BODY)
        self.assertFalse(res.ok)
        self.assertIsNone(res.status_code)
        self.assertIn("ReadTimeout", res.error)

    def test_empty_data(self):
        for payload in ({"data": []}, {}, {"data": [{"b64_json": ""}, "junk"]}):
            with patch("requests.post", return_value=_resp(200, payload)):
                res = generate_image(self.BODY)
            self.assertFalse(res.ok, payload)
            self.assertIn("нет изображения", res.error)

    def test_2xx_with_error_object(self):
        payload = {"error": {"message": "No endpoints found", "code": 404}}
        with patch("requests.post", return_value=_resp(200, payload)):
            res = generate_image(self.BODY)
        self.assertFalse(res.ok)
        self.assertIn("No endpoints found", res.error)

    def test_not_json(self):
        with patch("requests.post", return_value=_resp(200, text="<html>", json_error=True)):
            res = generate_image(self.BODY)
        self.assertFalse(res.ok)
        self.assertEqual(res.error, "<html>")

    def test_no_api_key_sends_nothing(self):
        self.cfg.return_value = {**CFG, "api_key": ""}
        with patch("requests.post") as post:
            res = generate_image(self.BODY)
        post.assert_not_called()
        self.assertFalse(res.ok)

    def test_image_item_decode(self):
        self.assertEqual(ImageItem(b64=_b64(JPEG), media_type="image/jpeg").decode(), JPEG)


class ChatPathUntouchedTests(SimpleTestCase):
    """Фаза 1: чат и довоз на media_provider НЕ переключаются (спецификация §0.2, §14).

    Перевод — отдельным коммитом в Фазе 1.5 с прогоном денежных сценариев;
    тогда этот тест удаляется вместе с ним.
    """

    def test_chat_and_recovery_do_not_use_media_provider(self):
        self.assertNotIn("media_provider", inspect.getsource(generation))
        self.assertNotIn("media_provider", inspect.getsource(recovery))
