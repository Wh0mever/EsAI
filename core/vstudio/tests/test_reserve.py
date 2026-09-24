"""Резерв кредитов, гейт запуска и списание (vstudio/reserve.py, спецификация §5.2–5.3).

Главное, что проверяем:
- два запуска на баланс для одного — второй получает 402 (на Postgres — два
  потока одновременно, на любой БД — последовательно);
- чат, бот и мультстудия видят резерв студии, а перевод кредитов не отдаёт
  обещанное за ролик, который ещё снимается;
- списание при выдаче — полное или «сколько есть» с пометкой partial.
"""
import threading
import time
from decimal import Decimal
from unittest import mock, skipUnless
from unittest.mock import MagicMock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import OperationalError, connection, transaction
from django.test import TestCase, TransactionTestCase, override_settings
from rest_framework.test import APIClient

from ai.models import AiChatSession, GenerationLog, GPTModels, OpenRouterAccount
from plans.models import TokenTransaction
from plans.wallet import credit_tokens, transferable_tokens
from vstudio import reserve
from vstudio.models import Take
from vstudio.tests import factories as f

CFG = {"api_key": "k", "base_url": "http://provider/api/v1"}
PARAMS = {"duration": 5, "resolution": "720p"}


def studio_take(user, credits=150, status=Take.STATUS_RUNNING, kind="video"):
    return f.make_take(f.make_shot(user, kind=kind), status=status, credits=credits)


def new_take(user, shot, credits, client_request_id=""):
    """Дубль так, как его создаёт POST shots/ — внутри spend_gate."""
    return Take.objects.create(user=user, shot=shot, project=shot.project, kind=shot.kind,
                               mode="t2v" if shot.kind == "video" else "t2i",
                               model_ref=shot.model_ref, serialized_prompt="p", request_body={},
                               credits_quoted=credits, credits_reserved=credits,
                               client_request_id=client_request_id)


def chat_open_video(user, credits, **kw):
    fields = dict(user=user, kind="video", source="chat", model="m",
                  status=GenerationLog.STATUS_SUBMITTED, credits_planned=credits)
    fields.update(kw)
    return GenerationLog.objects.create(**fields)


def refused(test, user, need, kind="video"):
    with test.assertRaises(reserve.SpendRefused) as cm:
        with reserve.spend_gate(user, need, kind=kind):
            test.fail("гейт должен был отказать")
    return cm.exception


def _db_blinks_on(table):
    def wrapper(execute, sql, params, many, context):
        if table in sql:
            raise OperationalError("db blinked")
        return execute(sql, params, many, context)
    return wrapper


# ---------------------------------------------------------------- суммы резервов

class ReservedSumTests(TestCase):
    def test_only_reserved_takes_of_this_user(self):
        user = f.make_user()
        studio_take(user, 100, Take.STATUS_QUEUED)
        studio_take(user, 50, Take.STATUS_SAVING)
        studio_take(user, 7, Take.STATUS_QUEUED, kind="image")
        studio_take(user, 70, Take.STATUS_DONE)
        studio_take(user, 30, Take.STATUS_FAILED)
        studio_take(user, 30, Take.STATUS_LOST)
        studio_take(f.make_user(), 999)
        self.assertEqual(reserve.vstudio_reserved(user), 157)

    def test_guest_and_empty(self):
        from django.contrib.auth.models import AnonymousUser

        self.assertEqual(reserve.vstudio_reserved(AnonymousUser()), 0)
        self.assertEqual(reserve.vstudio_reserved(None), 0)
        self.assertEqual(reserve.total_reserved(AnonymousUser()), 0)
        self.assertEqual(reserve.vstudio_reserved(f.make_user()), 0)

    def test_total_is_all_three_products(self):
        user = f.make_user()
        studio_take(user, 150)
        chat_open_video(user, 40)
        chat_open_video(user, 60, source="bot", status=GenerationLog.STATUS_SUBMITTING)
        chat_open_video(user, 500, status=GenerationLog.STATUS_DELIVERED)
        with mock.patch("cartoon.pricing.reserved_credits", return_value=25) as cartoon:
            self.assertEqual(reserve.total_reserved(user), 150 + 40 + 60 + 25)
            self.assertEqual(reserve.total_reserved(user, strict=True), 275)
        cartoon.assert_called_with(user)

    def test_studio_journal_rows_are_not_counted_twice(self):
        # Запись журнала дубля (source=vstudio) — не резерв чата: резерв студии — сам дубль.
        user = f.make_user()
        f.make_take(f.make_shot(user), status=Take.STATUS_RUNNING, credits=150, genlog=True)
        self.assertEqual(reserve.total_reserved(user), 150)

    def test_db_failure_does_not_block_other_products(self):
        user = f.make_user()
        studio_take(user, 150)
        with connection.execute_wrapper(_db_blinks_on("vstudio_take")), \
                self.assertLogs("vstudio.reserve", level="WARNING"):
            self.assertEqual(reserve.vstudio_reserved(user), 0)
        # Savepoint: транзакция запроса осталась рабочей.
        self.assertEqual(get_user_model().objects.filter(pk=user.pk).count(), 1)
        self.assertEqual(reserve.vstudio_reserved(user), 150)

    def test_strict_total_does_not_hide_failures(self):
        user = f.make_user()
        with connection.execute_wrapper(_db_blinks_on("vstudio_take")):
            with self.assertRaises(OperationalError), transaction.atomic():
                reserve.total_reserved(user, strict=True)
            with self.assertLogs("vstudio.reserve", level="WARNING"):
                self.assertEqual(reserve.total_reserved(user), 0)

    def test_app_not_installed_means_no_studio_reserve(self):
        user = f.make_user()
        studio_take(user, 150)
        with mock.patch("vstudio.reserve._installed", return_value=False):
            self.assertEqual(reserve.vstudio_reserved(user), 0)


class BalanceSnapshotTests(TestCase):
    def test_snapshot_for_quote_and_run(self):
        user = f.make_user(balance=500)
        studio_take(user, 120)
        user.token_balance = 0   # устаревший объект в памяти: баланс читается из БД
        self.assertEqual(reserve.balance_snapshot(user, 150),
                         {"balance": 500, "reserved": 120, "available": 380, "after": 230})
        self.assertEqual(reserve.balance_snapshot(user)["after"], None)
        self.assertEqual(reserve.balance_snapshot(user, 400)["after"], -20)

    def test_guest(self):
        from django.contrib.auth.models import AnonymousUser

        self.assertIsNone(reserve.balance_snapshot(AnonymousUser(), 10))
        self.assertIsNone(reserve.balance_snapshot(None))


# ---------------------------------------------------------------- гейт запуска

class SpendGateTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_passes_and_reserve_is_the_take(self):
        user = f.make_user(balance=500)
        shot = f.make_shot(user)
        user.token_balance = 0   # в памяти старое значение — гейт берёт строку под замком
        with reserve.spend_gate(user, 150, kind="video") as locked:
            self.assertEqual(locked.pk, user.pk)
            self.assertEqual(locked.token_balance, 500)
            new_take(locked, shot, 150)
        self.assertEqual(reserve.vstudio_reserved(user), 150)
        # Сам баланс не тронут: списание — только за готовый результат.
        self.assertEqual(get_user_model().objects.get(pk=user.pk).token_balance, 500)

    def test_second_run_sees_the_first_one(self):
        """Баланс на один ролик: второй запуск получает 402 в форме чата."""
        user = f.make_user(balance=200)
        shot = f.make_shot(user)
        with reserve.spend_gate(user, 150, kind="video") as locked:
            new_take(locked, shot, 150)
        exc = refused(self, user, 150)
        self.assertEqual(exc.status, 402)
        self.assertEqual(exc.error_code, "insufficient_balance")
        self.assertEqual(exc.payload["balance_tokens"], 50)
        self.assertEqual(exc.payload["required_estimate"], 150)
        self.assertEqual(exc.payload["reserved_credits"], 150)
        self.assertIn("ждёт оплаты", exc.payload["error"])
        self.assertEqual(Take.objects.filter(user=user).count(), 1)

    def test_chat_and_cartoon_reserves_count_too(self):
        user = f.make_user(balance=300)
        chat_open_video(user, 100)
        with mock.patch("cartoon.pricing.reserved_credits", return_value=60):
            exc = refused(self, user, 150)
        self.assertEqual(exc.status, 402)
        self.assertEqual(exc.payload["balance_tokens"], 140)
        self.assertEqual(exc.payload["reserved_credits"], 160)

    def test_plain_shortage_texts(self):
        user = f.make_user(balance=5)
        exc = refused(self, user, 6, kind="image")
        self.assertEqual(exc.payload, {"error": "Недостаточно кредитов для создания картинки.",
                                       "error_code": "insufficient_balance",
                                       "balance_tokens": 5, "required_estimate": 6})
        self.assertEqual(refused(self, user, 6).payload["error"],
                         "Недостаточно кредитов для генерации видео.")

    def test_exact_balance_is_enough(self):
        user = f.make_user(balance=150)
        with reserve.spend_gate(user, 150, kind="video"):
            pass

    def test_user_row_is_locked(self):
        user = f.make_user(balance=500)
        User = get_user_model()
        with mock.patch.object(User.objects, "select_for_update",
                               wraps=User.objects.select_for_update) as sfu:
            with reserve.spend_gate(user, 10, kind="video"):
                pass
        sfu.assert_called_once_with()

    def test_failure_inside_rolls_back_the_take(self):
        user = f.make_user(balance=500)
        shot = f.make_shot(user)
        with self.assertRaises(RuntimeError):
            with reserve.spend_gate(user, 150, kind="video") as locked:
                new_take(locked, shot, 150)
                raise RuntimeError("сбой после вставки")
        self.assertFalse(Take.objects.filter(user=user).exists())
        self.assertEqual(reserve.vstudio_reserved(user), 0)

    def test_open_limit_per_kind(self):
        user = f.make_user(balance=10_000)
        video = f.make_shot(user)
        f.make_take(video, status=Take.STATUS_QUEUED)
        f.make_take(video, status=Take.STATUS_RUNNING)
        f.make_take(video, status=Take.STATUS_DONE)       # закрытые не считаются
        f.make_take(video, status=Take.STATUS_FAILED)
        studio_take(f.make_user(), status=Take.STATUS_RUNNING)   # чужие тоже
        exc = refused(self, user, 10)
        self.assertEqual(exc.status, 409)
        self.assertEqual(exc.payload["error_code"], "too_many_open")
        self.assertEqual((exc.payload["limit"], exc.payload["kind"]), (2, "video"))
        self.assertIn("не больше 2 видео", exc.payload["error"])
        # Видео не мешают картинкам.
        with reserve.spend_gate(user, 10, kind="image"):
            pass
        with override_settings(VSTUDIO_MAX_OPEN_VIDEO=3):
            with reserve.spend_gate(user, 10, kind="video"):
                pass

    def test_image_limit_is_four(self):
        user = f.make_user(balance=10_000)
        image = f.make_shot(user, kind="image")
        for _ in range(3):
            f.make_take(image, status=Take.STATUS_RUNNING)
        with reserve.spend_gate(user, 5, kind="image") as locked:
            new_take(locked, image, 5)
        exc = refused(self, user, 5, kind="image")
        self.assertEqual((exc.status, exc.payload["limit"], exc.payload["kind"]), (409, 4, "image"))

    def test_same_click_gets_its_own_take_back(self):
        """Двойной клик «вплотную»: второй запрос после замка видит дубль первого."""
        user = f.make_user(balance=150)
        shot = f.make_shot(user)
        cid = "c" * 32
        with reserve.spend_gate(user, 150, kind="video", client_request_id=cid) as locked:
            first = new_take(locked, shot, 150, client_request_id=cid)
        # Баланса на второй нет и лимит не при чём — ответ тем же дублем, не 402.
        with self.assertRaises(reserve.AlreadyStarted) as cm:
            with reserve.spend_gate(user, 150, kind="video", client_request_id=cid):
                self.fail("второй дубль на тот же клик")
        self.assertEqual(cm.exception.take.pk, first.pk)
        # Другой клик — обычная проверка баланса.
        self.assertEqual(refused(self, user, 150).status, 402)
        with self.assertRaises(reserve.SpendRefused):
            with reserve.spend_gate(user, 150, kind="video", client_request_id="d" * 32):
                pass

    def test_limit_checked_before_balance(self):
        user = f.make_user(balance=0)
        video = f.make_shot(user)
        f.make_take(video, status=Take.STATUS_QUEUED)
        f.make_take(video, status=Take.STATUS_QUEUED)
        self.assertEqual(refused(self, user, 10).status, 409)

    def test_bad_arguments(self):
        user = f.make_user(balance=100)
        for kwargs in ({"need": 0, "kind": "video"}, {"need": -5, "kind": "video"},
                       {"need": 10, "kind": "audio"}):
            with self.assertRaises(ValueError):
                with reserve.spend_gate(user, kwargs["need"], kind=kwargs["kind"]):
                    pass


class ProviderGuardTests(TestCase):
    def _account(self, balance, active=True, title="Основной"):
        return OpenRouterAccount.objects.create(title=title, api_key="sk-or-test", is_active=active,
                                                balance_usd=balance)

    def test_low_openrouter_balance_refuses_before_anything_else(self):
        self._account(1.5)
        user = f.make_user(balance=0)   # и денег у человека нет — но первым отвечает 503
        User = get_user_model()
        with mock.patch.object(User.objects, "select_for_update") as sfu, \
                self.assertLogs("vstudio.reserve", level="ERROR"):
            exc = refused(self, user, 10)
        sfu.assert_not_called()
        self.assertEqual(exc.status, 503)
        self.assertEqual(exc.payload["error_code"], "provider_unavailable")
        self.assertIn("кредиты не списаны", exc.payload["error"])

    def test_nothing_to_judge_by_means_no_guard(self):
        user = f.make_user(balance=100)
        with reserve.spend_gate(user, 10, kind="video"):   # аккаунтов нет — ключ из настроек
            pass
        self._account(None)                                 # снимка ещё не было
        self._account(0, active=False, title="Пустой запасной")
        with reserve.spend_gate(user, 10, kind="video"):
            pass

    def test_threshold_and_setting(self):
        account = self._account(2.0)
        user = f.make_user(balance=100)
        with reserve.spend_gate(user, 10, kind="image"):    # ровно порог — можно
            pass
        OpenRouterAccount.objects.filter(pk=account.pk).update(balance_usd=3)
        with override_settings(VSTUDIO_MIN_PROVIDER_USD=5), \
                self.assertLogs("vstudio.reserve", level="ERROR"):
            self.assertEqual(refused(self, user, 10).status, 503)
        OpenRouterAccount.objects.filter(pk=account.pk).update(balance_usd=0)
        with override_settings(VSTUDIO_MIN_PROVIDER_USD=0):
            with reserve.spend_gate(user, 10, kind="video"):
                pass


# ---------------------------------------------------------------- списание при выдаче

class ChargeOnDeliveryTests(TestCase):
    def _ledger(self, user):
        return list(TokenTransaction.objects.filter(user=user).order_by("id"))

    def test_full_charge(self):
        user = f.make_user(balance=500)
        got = reserve.charge_on_delivery(user, 150, "vstudio_video",
                                         meta={"take": "t" * 32, "genlog": 7, "model": "m",
                                               "provider_cost_usd": Decimal("0.1234")})
        self.assertEqual(got, reserve.Charge(150, False))
        self.assertEqual(get_user_model().objects.get(pk=user.pk).token_balance, 350)
        [row] = self._ledger(user)
        self.assertEqual((row.delta, row.reason, row.balance_after), (-150, "vstudio_video", 350))
        self.assertEqual(row.meta["provider_cost_usd"], "0.1234")
        self.assertNotIn("partial", row.meta)

    def test_partial_charge_takes_what_is_left(self):
        user = f.make_user(balance=100)
        with transaction.atomic(), self.assertLogs("vstudio.reserve", level="WARNING"):
            got = reserve.charge_on_delivery(user, 150, "vstudio_image", meta={"take": "x" * 32})
            # Транзакция выдачи жива после InsufficientTokens: дальше идёт UPDATE журнала.
            self.assertEqual(get_user_model().objects.filter(pk=user.pk).count(), 1)
        self.assertEqual(got, reserve.Charge(100, True))
        self.assertEqual(get_user_model().objects.get(pk=user.pk).token_balance, 0)
        [row] = self._ledger(user)
        self.assertEqual((row.delta, row.reason), (-100, "vstudio_image"))
        self.assertEqual((row.meta["partial"], row.meta["wanted"], row.meta["balance_before"]),
                         (True, 150, 100))

    def test_nothing_left(self):
        user = f.make_user(balance=0)
        with self.assertLogs("vstudio.reserve", level="WARNING"):
            self.assertEqual(reserve.charge_on_delivery(user, 150, "vstudio_video"),
                             reserve.Charge(0, True))
        self.assertEqual(self._ledger(user), [])

    def test_zero_amount_writes_nothing(self):
        user = f.make_user(balance=50)
        self.assertEqual(reserve.charge_on_delivery(user, 0, "vstudio_video"), reserve.Charge(0, False))
        self.assertEqual(self._ledger(user), [])

    def test_only_studio_reasons(self):
        user = f.make_user(balance=50)
        with self.assertRaises(ValueError):
            reserve.charge_on_delivery(user, 10, "chat")
        with self.assertRaises(ValueError):
            reserve.charge_on_delivery(user, -1, "vstudio_video")
        self.assertEqual(self._ledger(user), [])

    def test_reason_for_kind(self):
        self.assertEqual(reserve.reason_for("video"), "vstudio_video")
        self.assertEqual(reserve.reason_for("image"), "vstudio_image")


# ---------------------------------------------------------------- другие продукты видят резерв

def _resp(status=200, payload=None):
    r = MagicMock(status_code=status, content=b"", text=str(payload or ""))
    r.json.return_value = payload or {}
    return r


class OtherProductsSeeStudioReserveTests(TestCase):
    """Чат, бот и мультстудия вычитают дубли студии (однострочные добавки §2.3)."""

    NEED = 210   # чат: 5 с × 42 кр

    def setUp(self):
        cache.clear()
        self.user = f.make_user(balance=300)
        self.chat_model = GPTModels.objects.create(
            name="Seedance 2.5", openrouter_id="bytedance/seedance-2.5", max_tokens=1000,
            markup_coefficient=42, category="video", is_active=True)
        self.take = studio_take(self.user, 150)

    def _chat(self, post):
        from ai.generation import run_video_generation

        session = AiChatSession.objects.create(user=self.user, title="Видео")
        with mock.patch("ai.handlers._video_model_params", return_value=PARAMS), \
                mock.patch("ai.handlers._openrouter_config", return_value=CFG), \
                mock.patch("ai.handlers._openrouter_video_catalog", return_value={}), \
                mock.patch("requests.post", side_effect=post) as posted, \
                mock.patch("requests.get", return_value=_resp()), \
                mock.patch("time.sleep", return_value=None), \
                mock.patch("ai.handlers._release_daily_request") as release:
            frames = list(run_video_generation(
                user=self.user, model_obj=self.chat_model,
                selected_model_name=self.chat_model.openrouter_id, message="кот на пляже",
                attachments=[], origin_base="https://esai.kg", session=session))
        return frames, posted, release

    def test_chat_video_gate(self):
        frames, posted, release = self._chat(lambda *a, **kw: self.fail("не должно уйти провайдеру"))
        self.assertEqual(frames[-1]["error_code"], "insufficient_balance")
        self.assertEqual(frames[-1]["balance_tokens"], 300 - 150)
        self.assertEqual(frames[-1]["reserved_credits"], 150)
        posted.assert_not_called()
        release.assert_called_once()
        self.assertFalse(GenerationLog.objects.filter(source="chat").exists())

    def test_chat_passes_once_the_take_is_closed(self):
        Take.objects.transition(self.take.pk, Take.OPEN, Take.STATUS_FAILED)
        frames, posted, _ = self._chat(lambda *a, **kw: _resp(400, {"error": "bad"}))
        self.assertNotEqual(frames[-1].get("error_code"), "insufficient_balance")
        self.assertTrue(posted.called, "гейт пропустил — запрос ушёл провайдеру")

    def test_bot_job_gate(self):
        api = APIClient()
        api.force_authenticate(self.user)
        with mock.patch("ai.handlers._video_model_params", return_value=PARAMS), \
                mock.patch("ai.handlers._openrouter_config", return_value=CFG), \
                mock.patch("ai.handlers._openrouter_video_catalog", return_value={}), \
                mock.patch("ai.tasks.run_generation_job.apply_async") as enqueue:
            response = api.post("/api/ai/jobs/", {"message": "кот",
                                                  "model": self.chat_model.openrouter_id},
                                format="json")
        self.assertEqual(response.status_code, 402, response.data)
        self.assertEqual(response.data["error_code"], "insufficient_balance")
        self.assertEqual(response.data["reserved_credits"], 150)
        enqueue.assert_not_called()

    def _cartoon_scene(self):
        from cartoon.models import CartoonCharacter, CartoonPreset, CartoonProject, CartoonScene

        frame = GPTModels.objects.create(name="Frame", openrouter_id="test/frame", max_tokens=100,
                                         markup_coefficient=Decimal(4), category="image")
        video = GPTModels.objects.create(name="Video", openrouter_id="test/video", max_tokens=100,
                                         markup_coefficient=Decimal(3), category="video")
        preset = CartoonPreset.objects.create(title="Крыша", slug="roof",
                                              scene_prompt="The character on a roof",
                                              image_model=frame, video_model=video, duration=5)
        hero = CartoonCharacter.objects.create(name="Кот", image="cartoon/characters/cat.jpg",
                                               is_public=True)
        project = CartoonProject.objects.create(user=self.user, character=hero)
        return CartoonScene.objects.create(project=project, preset=preset, order=0)

    def _render(self, scene, price):
        api = APIClient()
        api.force_authenticate(self.user)
        with mock.patch("cartoon.views._scene_price", return_value=price), \
                mock.patch("cartoon.views.render_scene.delay") as delay, \
                self.captureOnCommitCallbacks(execute=True):
            response = api.post(f"/api/cartoon/scenes/{scene.pk}/render/", {}, format="json")
        return response, delay

    def test_cartoon_render_gate(self):
        scene = self._cartoon_scene()
        response, delay = self._render(scene, 200)
        self.assertEqual(response.status_code, 402, response.data)
        self.assertEqual((response.data["balance"], response.data["reserved"],
                          response.data["required"]), (150, 150, 200))
        delay.assert_not_called()
        response, delay = self._render(scene, 150)
        self.assertEqual(response.status_code, 200, response.data)
        delay.assert_called_once_with(scene.pk)


class TransferKeepsReserveTests(TestCase):
    def setUp(self):
        self.sender = f.make_user("sender@example.com")
        self.friend = f.make_user("friend@example.com")
        credit_tokens(self.sender, 300, "purchase", meta={"order_id": "o-vs-1"})
        self.api = APIClient()
        self.api.force_authenticate(self.sender)

    def _send(self, amount):
        return self.api.post("/api/users/transfer/", {"recipient": "friend@example.com",
                                                     "amount": amount}, format="json")

    def test_run_then_transfer_is_not_a_loophole(self):
        take = studio_take(self.sender, 200)
        self.assertEqual(transferable_tokens(self.sender), 100)
        response = self._send(150)
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(response.data["transferable"], 100)
        self.assertEqual(self._send(100).status_code, 200)
        self.friend.refresh_from_db()
        self.assertEqual(self.friend.token_balance, 100)
        self.assertEqual(transferable_tokens(self.sender), 0)
        # Дубль не получился — резерв снят, остаток снова можно перевести.
        Take.objects.transition(take.pk, Take.OPEN, Take.STATUS_FAILED)
        self.assertEqual(transferable_tokens(self.sender), 200)

    def test_every_product_reserve_counts(self):
        chat_open_video(self.sender, 50)
        with mock.patch("cartoon.pricing.reserved_credits", return_value=30):
            self.assertEqual(transferable_tokens(self.sender), 220)
        studio_take(self.sender, 1000)
        self.assertEqual(transferable_tokens(self.sender), 0)

    def test_get_shows_the_same_pool(self):
        studio_take(self.sender, 120)
        response = self.api.get("/api/users/transfer/")
        self.assertEqual(response.data["transferable"], 180)


# ---------------------------------------------------------------- гонки (только Postgres)

@skipUnless(connection.vendor == "postgresql", "замок строки проверяется только на Postgres")
class SpendGateRaceTests(TransactionTestCase):
    """Два потока одновременно: select_for_update выстраивает их в очередь."""

    def _threads(self, *targets):
        threads = [threading.Thread(target=t) for t in targets]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        self.assertFalse(any(t.is_alive() for t in threads), "поток завис на замке")

    def test_two_parallel_runs_with_balance_for_one(self):
        user = f.make_user(balance=200)
        shot = f.make_shot(user)
        barrier = threading.Barrier(2)
        results = []

        def run():
            try:
                barrier.wait(timeout=10)
                with transaction.atomic():
                    with reserve.spend_gate(user, 150, kind="video") as locked:
                        time.sleep(0.3)   # держим замок: второй обязан дождаться коммита
                        new_take(locked, shot, 150)
                results.append("ok")
            except reserve.SpendRefused as exc:
                results.append(exc.status)
            except Exception as exc:  # noqa: BLE001 — покажем в assert
                results.append(repr(exc))
            finally:
                connection.close()

        self._threads(run, run)
        self.assertEqual(sorted(map(str, results)), ["402", "ok"])
        self.assertEqual(Take.objects.filter(user=user).count(), 1)
        self.assertEqual(reserve.vstudio_reserved(user), 150)

    def test_double_click_with_one_request_id(self):
        """Оба запроса прошли проверку идемпотентности до коммита — дубль один, 402 нет."""
        user = f.make_user(balance=150)
        shot = f.make_shot(user)
        cid = "e" * 32
        barrier = threading.Barrier(2)
        results = []

        def run():
            try:
                barrier.wait(timeout=10)
                with transaction.atomic():
                    with reserve.spend_gate(user, 150, kind="video", client_request_id=cid) as locked:
                        time.sleep(0.3)
                        new_take(locked, shot, 150, client_request_id=cid)
                results.append("ok")
            except reserve.AlreadyStarted as exc:
                results.append("same:" + exc.take.client_request_id)
            except Exception as exc:  # noqa: BLE001
                results.append(repr(exc))
            finally:
                connection.close()

        self._threads(run, run)
        self.assertEqual(sorted(results), ["ok", "same:" + cid])
        self.assertEqual(Take.objects.filter(user=user).count(), 1)

    def test_parallel_runs_respect_the_open_limit(self):
        user = f.make_user(balance=10_000)
        shot = f.make_shot(user, kind="image")
        barrier = threading.Barrier(3)
        results = []

        def run():
            try:
                barrier.wait(timeout=10)
                with transaction.atomic():
                    with reserve.spend_gate(user, 5, kind="image") as locked:
                        time.sleep(0.2)
                        new_take(locked, shot, 5)
                results.append("ok")
            except reserve.SpendRefused as exc:
                results.append(exc.status)
            except Exception as exc:  # noqa: BLE001
                results.append(repr(exc))
            finally:
                connection.close()

        with override_settings(VSTUDIO_MAX_OPEN_IMAGE=2):
            self._threads(run, run, run)
        self.assertEqual(sorted(map(str, results)), ["409", "ok", "ok"])

    def test_transfer_waits_for_the_run_and_sees_its_reserve(self):
        user = f.make_user("race-sender@example.com")
        f.make_user("race-friend@example.com")
        credit_tokens(user, 300, "purchase", meta={"order_id": "o-race"})
        shot = f.make_shot(user)
        locked_evt = threading.Event()
        results = {}

        def run():
            try:
                with transaction.atomic():
                    with reserve.spend_gate(user, 200, kind="video") as locked:
                        locked_evt.set()
                        time.sleep(0.4)
                        new_take(locked, shot, 200)
                results["run"] = "ok"
            except Exception as exc:  # noqa: BLE001
                results["run"] = repr(exc)
            finally:
                locked_evt.set()
                connection.close()

        def transfer():
            try:
                locked_evt.wait(timeout=10)
                api = APIClient()
                api.force_authenticate(user)
                response = api.post("/api/users/transfer/", {"recipient": "race-friend@example.com",
                                                             "amount": 200}, format="json")
                results["transfer"] = (response.status_code, response.data.get("transferable"))
            except Exception as exc:  # noqa: BLE001
                results["transfer"] = repr(exc)
            finally:
                connection.close()

        self._threads(run, transfer)
        self.assertEqual(results["run"], "ok")
        self.assertEqual(results["transfer"], (400, 100))
        self.assertEqual(get_user_model().objects.get(pk=user.pk).token_balance, 300)
