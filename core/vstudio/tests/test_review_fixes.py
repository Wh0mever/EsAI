"""Правки по ревью Фазы 1: деньги, ключ провайдера, неоднозначный COMMIT, ReDoS, память.

1. Опрос, скачивание и «Довезти» — ключом того аккаунта OpenRouter, что принял
   работу; 401/403/404/410 подряд — lost и снятый резерв, а не шесть часов.
2. Мгновенные траты (чат, мультстудия, распознавание голоса) не едят резерв
   идущих генераций.
3. Ошибка на COMMIT выдачи: если выдача записалась, файлы не стираются.
4. Эвристики компилятора линейны по длине текста.
5. Нормализатор фото: потолки по формату, без лишних копий, слоты на процесс.
8. Компилятор привязывает теги, набранные текстом.
"""
import gc
import io
import os
import threading
import time
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import OperationalError
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from ai import media_provider as mp
from ai.models import GenerationLog, OpenRouterAccount
from plans.models import TokenTransaction
from plans.wallet import InsufficientTokens, available_tokens, charge_tokens
from vstudio import assets as A
from vstudio import compiler as C
from vstudio import delivery, pipeline
from vstudio import prompt_doc as pd
from vstudio.models import Shot, Take
from vstudio.tests import factories as f
from vstudio.tests.caps_fixtures import make_caps
from vstudio.tests.test_api import ApiCase
from vstudio.tests.test_pipeline import POLL_URL, PipelineCase, accepted, png_b64, ready

KEY_A = "sk-or-v1-" + "a" * 56
KEY_B = "sk-or-v1-" + "b" * 56


def reserve_studio(user, credits):
    """Дубль студии в работе — резерв credits у user."""
    shot = f.make_shot(user)
    return f.make_take(shot, status="running", credits=credits)


# ---------------------------------------------------------------- 1. ключ провайдера

class ProviderAccountTests(PipelineCase):
    def setUp(self):
        super().setUp()
        self.acc_a = OpenRouterAccount.objects.create(title="Основной", api_key=KEY_A, is_active=True)
        self.acc_b = OpenRouterAccount.objects.create(title="Резервный", api_key=KEY_B)

    def switch_to_b(self):
        # Так делает ai.tasks.openrouter_autoswitch: save() снимает активность с остальных.
        self.acc_b.is_active = True
        self.acc_b.save()
        self.assertFalse(OpenRouterAccount.objects.get(pk=self.acc_a.pk).is_active)

    def submitted(self):
        take = self.video_take()
        with self.provider(submit=accepted()) as p:
            self.assertEqual(pipeline.submit(take.pk), "running")
        self.assertEqual(p.mocks["submit"].call_args.kwargs["cfg"]["api_key"], KEY_A)
        take.refresh_from_db()
        return take

    def test_submit_records_which_account_sent_the_job(self):
        take = self.submitted()
        self.assertEqual(take.provider_account_id, self.acc_a.pk)
        self.assertEqual(take.provider_key_fp, mp.key_fingerprint(KEY_A))
        self.assertNotIn(KEY_A, take.provider_key_fp)

    def test_poll_after_autoswitch_still_uses_the_submitting_key(self):
        take = self.submitted()
        self.switch_to_b()
        self.set(take, next_poll_at=self.ago(seconds=1))
        with self.provider(poll=mp.Poll(status="in_progress", status_code=200)) as p:
            self.assertEqual(pipeline.poll(take.pk), "polling")
        self.assertEqual(p.mocks["poll"].call_args.kwargs["cfg"]["api_key"], KEY_A)

    def test_finalize_polls_and_downloads_with_the_submitting_key(self):
        take = self.submitted()
        self.switch_to_b()
        self.set(take, status="saving", lease_until=timezone.now())
        with self.provider(poll=ready()) as p:
            self.assertEqual(pipeline.finalize(take.pk), "done")
        self.assertEqual(p.mocks["poll"].call_args.kwargs["cfg"]["api_key"], KEY_A)
        self.assertEqual(p.mocks["download"].call_args.kwargs["cfg"]["api_key"], KEY_A)
        take.refresh_from_db()
        self.assertEqual((take.status, take.charge_state), ("done", "charged"))

    def test_redeliver_uses_the_submitting_key(self):
        take = self.submitted()
        self.switch_to_b()
        self.set(take, status="lost", charge_state="released", lease_until=None)
        with self.captureOnCommitCallbacks(execute=True):
            self.assertTrue(pipeline.admin_redeliver(take.pk))
        with self.provider(poll=ready()) as p:
            self.assertEqual(pipeline.finalize(take.pk, redeliver=True), "done")
        self.assertEqual(p.mocks["poll"].call_args.kwargs["cfg"]["api_key"], KEY_A)
        self.assertEqual(p.mocks["download"].call_args.kwargs["cfg"]["api_key"], KEY_A)

    def test_unreachable_polls_give_up_and_release_the_reserve(self):
        take = self.submitted()
        for n in range(1, pipeline.POLL_UNREACHABLE_MAX):
            self.set(take, next_poll_at=self.ago(seconds=1))
            with self.provider(poll=mp.Poll(transient=True, error="not found", status_code=404)):
                self.assertEqual(pipeline.poll(take.pk), "polling")
            take.refresh_from_db()
            self.assertEqual((take.status, take.poll_errors), ("running", n))
            # Пауза не меньше 30 с: короткий сбой авторизации дубль переживает.
            self.assertGreaterEqual(self.enqueued[-1][2], pipeline.POLL_UNREACHABLE_STEP)
        self.set(take, next_poll_at=self.ago(seconds=1))
        with self.provider(poll=mp.Poll(transient=True, error="unauthorized", status_code=401)):
            self.assertEqual(pipeline.poll(take.pk), "lost")
        take.refresh_from_db()
        self.assertEqual((take.status, take.charge_state, take.error_code),
                         ("lost", "released", "provider_unreachable"))
        self.assertIn("Кредиты не списаны", take.error)
        row = GenerationLog.objects.get(pk=take.genlog_id)
        self.assertEqual(row.status, "lost")
        self.assertTrue(row.needs_review)
        self.assertEqual(self.ledger(), [])
        self.assert_money_invariant()

    def test_a_good_answer_resets_the_unreachable_counter(self):
        take = self.set(self.submitted(), poll_errors=pipeline.POLL_UNREACHABLE_MAX - 1,
                        next_poll_at=self.ago(seconds=1))
        with self.provider(poll=mp.Poll(status="in_progress", status_code=200)):
            self.assertEqual(pipeline.poll(take.pk), "polling")
        take.refresh_from_db()
        self.assertEqual((take.status, take.poll_errors), ("running", 0))

    def test_5xx_stays_transient_forever(self):
        take = self.set(self.submitted(), poll_errors=0)
        for _ in range(pipeline.POLL_UNREACHABLE_MAX + 2):
            self.set(take, next_poll_at=self.ago(seconds=1))
            with self.provider(poll=mp.Poll(transient=True, error="bad gateway", status_code=502)):
                self.assertEqual(pipeline.poll(take.pk), "polling")
        take.refresh_from_db()
        self.assertEqual((take.status, take.poll_errors), ("running", 0))


class ConfigForTests(TestCase):
    def test_finds_the_account_even_when_it_is_no_longer_active(self):
        a = OpenRouterAccount.objects.create(title="A", api_key=KEY_A, is_active=True)
        OpenRouterAccount.objects.create(title="B", api_key=KEY_B, is_active=True)  # A больше не активен
        cfg = mp.config_for(a.pk, mp.key_fingerprint(KEY_A))
        self.assertEqual(cfg["api_key"], KEY_A)
        self.assertEqual(mp.current_config()["api_key"], KEY_B)

    def test_deleted_account_is_found_by_fingerprint_among_settings_keys(self):
        OpenRouterAccount.objects.create(title="B", api_key=KEY_B, is_active=True)
        with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": KEY_A}):
            cfg = mp.config_for(999, mp.key_fingerprint(KEY_A))
        self.assertEqual(cfg["api_key"], KEY_A)

    def test_changed_key_of_the_account_is_not_used_blindly(self):
        a = OpenRouterAccount.objects.create(title="A", api_key=KEY_B, is_active=True)
        with self.assertLogs("ai.media_provider", "WARNING"):
            cfg = mp.config_for(a.pk, mp.key_fingerprint(KEY_A))
        self.assertEqual(cfg["api_key"], KEY_B)  # ключа A нигде нет — текущий, с предупреждением

    def test_legacy_takes_without_a_mark_use_the_current_key(self):
        OpenRouterAccount.objects.create(title="B", api_key=KEY_B, is_active=True)
        self.assertEqual(mp.config_for(None, "")["api_key"], KEY_B)

    def test_current_config_names_the_account(self):
        a = OpenRouterAccount.objects.create(title="A", api_key=KEY_A, is_active=True)
        cfg = mp.current_config()
        self.assertEqual((cfg["account_id"], cfg["key_fp"]), (a.pk, mp.key_fingerprint(KEY_A)))


class PollKeyUnitTests(SimpleTestCase):
    def test_poll_sends_the_given_key_and_marks_404_unreachable(self):
        cfg = {"base_url": "https://openrouter.ai/api/v1", "api_key": KEY_A}
        resp = mock.Mock(status_code=404, text="not found")
        with mock.patch("ai.media_provider.requests.get", return_value=resp) as get, \
                mock.patch("ai.media_provider._config", side_effect=AssertionError("текущий ключ")):
            res = mp.poll_video(POLL_URL, cfg=cfg)
        self.assertEqual(get.call_args.kwargs["headers"]["Authorization"], f"Bearer {KEY_A}")
        self.assertTrue(res.transient)
        self.assertTrue(res.unreachable)
        self.assertFalse(res.is_failed)

    def test_unreachable_codes(self):
        for code, expected in ((401, True), (403, True), (404, True), (410, True),
                               (429, False), (500, False), (502, False), (None, False)):
            self.assertIs(mp.Poll(transient=True, status_code=code).unreachable, expected, code)


# ---------------------------------------------------------------- 2. мгновенные траты и резерв

class WalletReserveTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = f.make_user(balance=500)
        reserve_studio(self.user, 500)

    def test_available_is_balance_minus_reserves(self):
        self.assertEqual(available_tokens(self.user), 0)
        get_user_model().objects.filter(pk=self.user.pk).update(token_balance=700)
        self.assertEqual(available_tokens(self.user), 200)

    def test_instant_charge_cannot_eat_the_reserve(self):
        with self.assertRaises(InsufficientTokens) as ctx:
            charge_tokens(self.user, 10, "chat", respect_reserves=True)
        self.assertEqual((ctx.exception.balance, ctx.exception.total), (0, 500))
        self.assertFalse(TokenTransaction.objects.filter(user=self.user).exists())

    def test_delivery_charge_still_uses_the_reserve(self):
        # Выдача самой резервной генерации платит из резерва — без флага.
        self.assertEqual(charge_tokens(self.user, 500, "vstudio_video"), 0)

    def test_chat_charges_only_what_is_free(self):
        from ai.handlers import _charge_up_to_balance

        get_user_model().objects.filter(pk=self.user.pk).update(token_balance=530)
        self.assertEqual(_charge_up_to_balance(self.user, 100, {"session_id": 1}), 500)
        deltas = list(TokenTransaction.objects.filter(user=self.user).values_list("delta", "reason"))
        self.assertEqual(deltas, [(-30, "chat")])

    def test_chat_gate_sees_the_reserve(self):
        from ai.handlers import _precise_balance_gate

        model = f.make_gpt_model("openai/gpt-4o-mini", category="text", markup=1)
        refusal = _precise_balance_gate(self.user, model, [{"role": "user", "content": "привет"}],
                                        limited=False, web_search=False, model_max_tokens=100)
        self.assertEqual(refusal["error_code"], "insufficient_balance")
        self.assertEqual(refusal["balance_tokens"], 0)

    def test_studio_video_is_charged_in_full_after_chat_tried_to_spend(self):
        """Сценарий ревью: 500 кр, видео за 500 в резерве, чат пытается потратить их же."""
        from ai.handlers import _charge_up_to_balance

        self.assertEqual(_charge_up_to_balance(self.user, 500, {"session_id": 1}), 500)
        self.user.refresh_from_db()
        self.assertEqual(self.user.token_balance, 500)


@override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                                       "LOCATION": "vs-review-stt"}},
                   STT_CREDITS_PER_MINUTE=2, STT_MAX_SECONDS=120)
class SttAndCartoonReserveTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = f.make_user(balance=20)
        reserve_studio(self.user, 20)
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    def test_stt_refuses_before_calling_the_model(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        from ai import stt

        with mock.patch.object(stt, "convert_to_mp3", return_value=(b"mp3", 30.0, -20.0)), \
                mock.patch.object(stt, "transcribe_audio") as model:
            res = self.api.post("/api/ai/transcribe/",
                                {"file": SimpleUploadedFile("v.ogg", b"ogg", content_type="audio/ogg")},
                                format="multipart")
        self.assertEqual(res.status_code, 402)
        self.assertEqual(res.data["balance_tokens"], 0)
        model.assert_not_called()

    def test_cartoon_character_refuses_before_calling_the_provider(self):
        f.make_gpt_model("google/gemini-2.5-flash-image", category="image", markup=6)
        with mock.patch("requests.post") as post:
            res = self.api.post("/api/cartoon/characters/generate/", {"prompt": "дракон"}, format="json")
        self.assertEqual(res.status_code, 402, res.content)
        self.assertEqual(res.data["balance"], 0)
        post.assert_not_called()


# ---------------------------------------------------------------- 3. неоднозначный COMMIT

class AmbiguousCommitTests(PipelineCase):
    def saving(self):
        take = self.video_take(status="saving", genlog=True)
        return self.set(take, lease_until=timezone.now(), submitted_at=self.ago(minutes=2))

    def test_commit_applied_but_reported_as_error_keeps_the_files(self):
        take = self.saving()
        real = delivery.commit_video

        def applied_then_lost(*args, **kw):
            real(*args, **kw)
            raise OperationalError("server closed the connection unexpectedly")

        with self.provider(poll=ready()), \
                mock.patch("vstudio.delivery.commit_video", side_effect=applied_then_lost):
            self.assertEqual(pipeline.finalize(take.pk), "done")
        take.refresh_from_db()
        self.assertEqual((take.status, take.charge_state, take.credits_charged), ("done", "charged", 150))
        self.assertTrue(os.path.exists(os.path.join(self.media, take.result_asset.file)))
        self.assertEqual(len(self.studio_files()), 2)
        self.assertEqual([t.delta for t in self.ledger()], [-150])
        row = GenerationLog.objects.get(pk=take.genlog_id)
        self.assertIn("delivered", [s["stage"] for s in row.stages])
        self.assert_money_invariant()

    def test_commit_not_applied_still_deletes_and_retries(self):
        take = self.saving()
        with self.provider(poll=ready()), \
                mock.patch("vstudio.delivery.commit_video", side_effect=OperationalError("gone")):
            self.assertEqual(pipeline.finalize(take.pk), "retry")
        take.refresh_from_db()
        self.assertEqual((take.status, take.charge_state), ("saving", "reserved"))
        self.assertEqual(self.studio_files(), [])

    def test_unreadable_state_keeps_the_files(self):
        take = self.saving()
        with self.provider(poll=ready()), \
                mock.patch("vstudio.delivery.commit_video", side_effect=OperationalError("gone")), \
                mock.patch("vstudio.pipeline.delivery_landed", return_value=None):
            self.assertEqual(pipeline.finalize(take.pk), "retry")
        self.assertEqual(len(self.studio_files()), 2)

    def test_image_commit_applied_but_reported_as_error(self):
        take, pending = self.image_take()
        real = delivery.commit_image

        def applied_then_lost(*args, **kw):
            real(*args, **kw)
            raise OperationalError("server closed the connection unexpectedly")

        ok = mp.Images(items=[mp.ImageItem(b64=png_b64(), media_type="image/jpeg")], cost=0.04,
                       status_code=200)
        with self.provider(image=ok), \
                mock.patch("vstudio.delivery.commit_image", side_effect=applied_then_lost):
            self.assertEqual(pipeline.run_image(take.pk), "done")
        take.refresh_from_db()
        pending.refresh_from_db()
        self.assertEqual((take.status, take.charge_state), ("done", "charged"))
        self.assertEqual(pending.status, "ready")
        self.assertTrue(os.path.exists(os.path.join(self.media, pending.file)))
        self.assert_money_invariant()

    def test_delivery_landed(self):
        take = self.saving()
        self.assertIs(pipeline.delivery_landed(take.pk, "vstudio/1/x.mp4"), False)
        self.assertIs(pipeline.delivery_landed(10 ** 9, "vstudio/1/x.mp4"), False)
        asset = f.make_asset(self.user, kind="video")
        Take.objects.filter(pk=take.pk).update(status="done", charge_state="charged", result_asset=asset)
        self.assertIs(pipeline.delivery_landed(take.pk, asset.file), True)
        self.assertIs(pipeline.delivery_landed(take.pk, "vstudio/1/other.mp4"), False)


# ---------------------------------------------------------------- 4. ReDoS в эвристиках

class CompilerSpeedTests(SimpleTestCase):
    def test_pathological_texts_compile_fast(self):
        caps = make_caps("bytedance/seedance-2.0")
        texts = ["a" + "\n" * 20000, " \n" * 10000, "1." + "\n" * 19990, "\t\n" * 9990,
                 "scene" + " " * 19990, ("1. x\n") * 4000]
        for text in texts:
            doc = {"v": 1, "blocks": [[{"t": "text", "v": text[:20000]}]]}
            started = time.perf_counter()
            C.compile(caps, "video", doc, [], {}, site_base="https://esai.kg")
            self.assertLess(time.perf_counter() - started, 0.1, repr(text[:12]))
            started = time.perf_counter()
            C.script_signs(text)
            self.assertLess(time.perf_counter() - started, 0.1, repr(text[:12]))

    def test_script_signs_still_work(self):
        self.assertGreaterEqual(C.script_signs("Сцена 1. Кот идёт\n  Scene 2 — прыгает\n1. раз\n2) два"), 4)
        self.assertEqual(C.script_signs("просто описание"), 0)

    def test_quote_with_a_newline_bomb_is_fast(self):
        """Сценарий ревью: 40 КБ переводов строк в quote/ — не 13 секунд."""
        doc = {"v": 1, "blocks": [[{"t": "text", "v": "a" + "\n" * 19990}]]}
        caps = make_caps("bytedance/seedance-2.0")
        started = time.perf_counter()
        out = C.compile(caps, "video", doc, [], {}, site_base="https://esai.kg")
        self.assertLess(time.perf_counter() - started, 0.1)
        self.assertIn("prompt_too_long", [e["code"] for e in out.errors])
        self.assertNotIn("looks_like_script", [w["code"] for w in out.warnings])


# ---------------------------------------------------------------- 5. память нормализатора

def _png(side, mode="RGBA", transparent=False):
    from PIL import Image

    img = Image.new(mode, (side, side), (10, 200, 30, 255) if mode == "RGBA" else (10, 200, 30))
    if transparent:
        img.putpixel((1, 1), (11, 200, 30, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    del img
    return buf.getvalue()


def _peak_rss_mb(fn):
    import psutil

    proc = psutil.Process()
    gc.collect()
    base = proc.memory_info().rss
    top = [base]
    stop = threading.Event()

    def sample():
        while not stop.is_set():
            top[0] = max(top[0], proc.memory_info().rss)
            time.sleep(0.002)

    t = threading.Thread(target=sample)
    t.start()
    try:
        fn()
    finally:
        stop.set()
        t.join()
    return (top[0] - base) / 1e6


try:
    import psutil  # noqa: F401
    HAS_PSUTIL = True
except ImportError:  # на сервере psutil нет — замер памяти пропускаем
    HAS_PSUTIL = False


class NormalizerMemoryTests(SimpleTestCase):
    def test_limits_by_format(self):
        self.assertEqual(A.pixel_limit("JPEG"), A.MAX_PIXELS)
        self.assertEqual(A.pixel_limit("MPO"), A.MAX_PIXELS)
        self.assertEqual(A.pixel_limit("HEIF"), A.MAX_PIXELS_HEIF)
        self.assertEqual(A.pixel_limit("WEBP"), A.MAX_PIXELS_WEBP)
        for fmt in ("PNG", "GIF", "BMP", ""):
            self.assertEqual(A.pixel_limit(fmt), A.MAX_PIXELS_FULL_DECODE)

    def test_50mp_rgba_png_is_refused_before_decoding(self):
        blob = _png(7072)  # 50 Мп, файл — ~200 КБ
        self.assertLess(len(blob), 1_000_000)
        with mock.patch("PIL.PngImagePlugin.PngImageFile.load",
                        side_effect=AssertionError("декодирует")):
            with self.assertRaises(A.AssetError) as ctx:
                A.normalize_image_bytes(blob)
        self.assertEqual(ctx.exception.code, "too_many_pixels")
        self.assertEqual(ctx.exception.params["max_pixels"], A.MAX_PIXELS_FULL_DECODE)
        self.assertIn("16 Мп", ctx.exception.message)

    def test_provider_result_is_trusted_up_to_the_general_limit(self):
        with mock.patch.object(A, "MAX_PIXELS_FULL_DECODE", 100 * 100):
            with self.assertRaises(A.AssetError):
                A.normalize_image_bytes(_png(200, mode="RGB"))
            norm = A.normalize_image_bytes(_png(200, mode="RGB"), trusted=True)
        self.assertEqual((norm.width, norm.height), (200, 200))

    def test_rgba_is_not_copied_by_convert(self):
        from PIL import Image

        img = Image.new("RGBA", (10, 10))
        out, _ = A._to_rgb_or_rgba(img, None)
        self.assertIs(out, img)

    def test_busy_slots_answer_429(self):
        with mock.patch.object(A, "_normalize_slots", threading.BoundedSemaphore(1)) as slots, \
                mock.patch.object(A, "NORMALIZE_WAIT_S", 0.01):
            slots.acquire()
            try:
                with self.assertRaises(A.AssetError) as ctx:
                    A.normalize_image_bytes(f.image_bytes(10, 10))
            finally:
                slots.release()
        self.assertEqual((ctx.exception.code, ctx.exception.status), ("throttled", 429))
        # Слот освобождается и после ошибки нормализации.
        with self.assertRaises(A.AssetError):
            A.normalize_image_bytes(b"not an image")
        self.assertEqual(A.normalize_image_bytes(f.image_bytes(10, 10)).width, 10)

    def test_peak_memory_at_the_limits(self):
        if not HAS_PSUTIL:
            self.skipTest("psutil не установлен")
        side = int(A.MAX_PIXELS_FULL_DECODE ** 0.5)  # 4000×4000 RGBA
        cases = {
            "50 Мп RGBA PNG (отказ)": (_png(7072), 40),
            "16 Мп непрозрачный RGBA PNG": (_png(side), 160),
            "16 Мп прозрачный RGBA PNG": (_png(side, transparent=True), 230),
        }
        for name, (blob, limit_mb) in cases.items():
            with self.subTest(name):
                def run(blob=blob):
                    try:
                        A.normalize_image_bytes(blob)
                    except A.AssetError:
                        pass
                self.assertLess(_peak_rss_mb(run), limit_mb)


# ---------------------------------------------------------------- 8. теги, набранные текстом

class TextTagLinkTests(SimpleTestCase):
    A1, A2 = "a" * 32, "b" * 32

    def inputs(self):
        def ref(uid, pos):
            view = C.AssetView(uid=uid, width=1080, height=1920, file=f"vstudio/1/{uid}.jpg")
            return C.ResolvedInput(view, "reference", pos, "", True)
        return [ref(self.A1, 0), ref(self.A2, 1)]

    def compile(self, text):
        caps = make_caps("bytedance/seedance-2.0")
        doc = {"v": 1, "blocks": [[{"t": "text", "v": text}]]}
        return C.compile(caps, "video", doc, self.inputs(), {}, site_base="https://esai.kg",
                         storage_url=lambda name: "/media/" + name)

    def test_typed_tag_binds_the_reference(self):
        out = self.compile("Кошка в стиле @Image 1")
        self.assertEqual(out.errors, [])
        self.assertIn("[Image 1]", out.body["prompt"])
        self.assertNotIn("@Image 1", out.body["prompt"])
        unmentioned = [w["params"].get("asset") for w in out.warnings if w["code"] == "ref_unmentioned"]
        self.assertNotIn(self.A1, unmentioned)
        self.assertIn(self.A2, unmentioned)
        self.assertEqual(pd.ref_uids(out.doc), [self.A1])

    def test_unknown_tag_warns(self):
        out = self.compile("Кошка и @Image 3")
        self.assertEqual([w["params"]["text"] for w in out.warnings if w["code"] == "tag_unknown"],
                         ["@Image 3"])

    def test_media_tag_blocks(self):
        out = self.compile("девушка как на @Видео 1")
        self.assertIn("video_refs_unsupported", [e["code"] for e in out.errors])
        self.assertEqual(out.body, {})

    def test_hard_break_is_a_tag_boundary(self):
        doc = pd.link_tags({"v": 1, "blocks": [[{"t": "text", "v": "@\nImage 1 и @Image 2"}]]},
                           self.inputs()).doc
        self.assertEqual(doc["blocks"][0],
                         [{"t": "text", "v": "@\nImage 1 и "}, {"t": "ref", "asset": self.A2}])


class TextTagApiTests(ApiCase):
    def setUp(self):
        super().setUp()
        self.photo = f.make_asset(self.user)

    def body(self, **extra):
        return super().body(inputs=[self.photo], **extra)

    def test_quote_binds_a_tag_left_as_text(self):
        body = self.body(doc={"v": 1, "blocks": [[{"t": "text", "v": "Кошка в стиле @Image 1"}]]})
        data = self.quote(body).json()
        self.assertEqual(data["errors"], [])
        self.assertIn("[Image 1]", data["serialized_prompt"])
        self.assertNotIn("ref_unmentioned", [w["code"] for w in data["warnings"]])

    def test_run_stores_the_bound_document(self):
        body = self.body(doc={"v": 1, "blocks": [[{"t": "text", "v": "Кошка в стиле @Image 1"}]]})
        res = self.launch(body)
        self.assertEqual(res.status_code, 202, res.content)
        shot = Shot.objects.get(user=self.user)
        self.assertEqual(pd.ref_uids(shot.prompt_doc), [self.photo.uid])

    def test_prompt_text_path_does_not_double_warnings(self):
        body = self.body(text="Кошка и @Image 3 и @Видео 1")
        data = self.quote(body).json()
        self.assertEqual([w["code"] for w in data["warnings"]].count("tag_unknown"), 1)
        self.assertEqual([e["code"] for e in data["errors"]].count("video_refs_unsupported"), 1)
