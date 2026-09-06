# -*- coding: utf-8 -*-
"""Зависшая задача не должна навсегда отбирать у человека видео.

Воркер могли перезапустить посреди генерации: задача остаётся в running, и
замок «один ролик за раз» отвечает 409 на каждую следующую попытку. Отмена
такой задачи должна закрывать её тоже — иначе кнопка «Отменить» ничего не
отменяет.
"""
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from .models import GenerationJob, GPTModels
from .views_media import JOB_STALE_AFTER

TEST_CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                           "LOCATION": "jobs-stale-tests"}}
URL = "/api/ai/jobs/"
PARAMS = {"duration": 5, "resolution": "720p"}


def _user(balance=100, email="stale@example.com"):
    User = get_user_model()
    user = User.objects.create_user(email=email, password="x")
    user.token_balance = balance
    user.is_paid = True
    user.save(update_fields=["token_balance", "is_paid"])
    return user


def _client(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def _mocks():
    return (patch("ai.handlers._video_model_params", return_value=PARAMS),
            patch("ai.handlers._openrouter_config", return_value={"api_key": "k", "base_url": "http://x"}),
            patch("ai.tasks.run_generation_job.apply_async"))


def _age(job, seconds: int, *, started: bool = True):
    """Состарить задачу: created_at/started_at через UPDATE (auto_now_add)."""
    moment = timezone.now() - timedelta(seconds=seconds)
    GenerationJob.objects.filter(pk=job.pk).update(
        created_at=moment, started_at=moment if started else None)
    job.refresh_from_db()
    return job


@override_settings(CACHES=TEST_CACHES, CELERY_MEDIA_QUEUE="media")
class StaleJobTests(TestCase):
    def setUp(self):
        cache.clear()
        GPTModels.objects.create(name="Test Video", openrouter_id="test/video", max_tokens=1000,
                                 markup_coefficient=4, category="video", is_active=True,
                                 free_tier=False)
        self.user = _user()

    def _create(self):
        p1, p2, enqueue = _mocks()
        with p1, p2, enqueue:
            return _client(self.user).post(
                URL, {"message": "кот на скейте", "model": "test/video"}, format="json")

    def test_stale_running_job_does_not_block_new_one(self):
        stale = _age(GenerationJob.objects.create(user=self.user, status="running"),
                     JOB_STALE_AFTER + 60)
        with patch("ai.handlers._release_daily_request") as release:
            response = self._create()
        self.assertEqual(response.status_code, 202, response.data)
        stale.refresh_from_db()
        self.assertEqual(stale.status, GenerationJob.STATUS_FAILED)
        self.assertEqual(stale.error_code, "job_stale")
        self.assertIsNotNone(stale.finished_at)
        # Слот дневного лимита вернулся: ролика человек так и не получил.
        release.assert_called_once()

    def test_stale_queued_job_is_closed_too(self):
        """Очередь могла умереть, не начав задачу: started_at так и остался пустым."""
        stale = _age(GenerationJob.objects.create(user=self.user, status="queued"),
                     JOB_STALE_AFTER + 60, started=False)
        response = self._create()
        self.assertEqual(response.status_code, 202, response.data)
        stale.refresh_from_db()
        self.assertEqual(stale.status, GenerationJob.STATUS_FAILED)

    def test_live_job_still_blocks(self):
        """Живую генерацию не трогаем: параллельные ролики жгут баланс."""
        live = _age(GenerationJob.objects.create(user=self.user, status="running"), 60)
        response = self._create()
        self.assertEqual(response.status_code, 409, response.data)
        self.assertEqual(response.data["error_code"], "job_in_progress")
        live.refresh_from_db()
        self.assertEqual(live.status, GenerationJob.STATUS_RUNNING)

    def test_stale_job_of_another_user_is_not_touched(self):
        stranger = _user(email="other@example.com")
        theirs = _age(GenerationJob.objects.create(user=stranger, status="running"),
                      JOB_STALE_AFTER + 60)
        self.assertEqual(self._create().status_code, 202)
        theirs.refresh_from_db()
        self.assertEqual(theirs.status, GenerationJob.STATUS_RUNNING)

    def test_cancel_closes_running_job_and_unblocks_next_run(self):
        job = GenerationJob.objects.create(user=self.user, status="running")
        response = _client(self.user).post(f"{URL}{job.uid}/cancel/")
        self.assertEqual(response.data["status"], GenerationJob.STATUS_CANCELED)
        job.refresh_from_db()
        self.assertEqual(job.error_code, "canceled")
        self.assertIsNotNone(job.finished_at)
        # Ради этого отмена и нужна: следующий ролик должен запускаться сразу.
        self.assertEqual(self._create().status_code, 202)

    def test_cancel_of_live_job_leaves_the_slot_to_the_worker(self):
        """Дневной слот у живой задачи вернёт сам воркер — второй раз нельзя.

        Воркер увидит флаг отмены и вызовет _release_daily_request сам
        (generation.py). Верни мы слот ещё и здесь — счётчик просел бы на два
        за одну генерацию, и человек получал бы лишний запрос сверх дневного
        лимита за каждую отмену.
        """
        from .handlers import _daily_req_count_key, _reserve_daily_request

        _reserve_daily_request(self.user)
        _reserve_daily_request(self.user)
        job = GenerationJob.objects.create(user=self.user, status="running")
        _client(self.user).post(f"{URL}{job.uid}/cancel/")
        self.assertEqual(int(cache.get(_daily_req_count_key(self.user)) or 0), 2)

    def test_cancel_of_stale_job_returns_the_slot(self):
        """У зависшей задачи воркера нет — слот вернуть больше некому."""
        from .handlers import _daily_req_count_key, _reserve_daily_request

        _reserve_daily_request(self.user)
        _reserve_daily_request(self.user)
        job = _age(GenerationJob.objects.create(user=self.user, status="running"),
                   JOB_STALE_AFTER + 60)
        _client(self.user).post(f"{URL}{job.uid}/cancel/")
        self.assertEqual(int(cache.get(_daily_req_count_key(self.user)) or 0), 1)

    def test_cancel_sets_the_flag_for_a_live_worker(self):
        from .views_media import _cancel_key

        job = GenerationJob.objects.create(user=self.user, status="running")
        _client(self.user).post(f"{URL}{job.uid}/cancel/")
        self.assertTrue(cache.get(_cancel_key(job.uid)))

    def test_cancel_of_finished_job_changes_nothing(self):
        job = GenerationJob.objects.create(user=self.user, status="done")
        with patch("ai.handlers._release_daily_request") as release:
            response = _client(self.user).post(f"{URL}{job.uid}/cancel/")
        self.assertEqual(response.data["status"], GenerationJob.STATUS_DONE)
        release.assert_not_called()
