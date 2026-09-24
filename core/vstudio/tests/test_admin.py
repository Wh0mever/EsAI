"""Админка видеостудии: списки и фильтры, только чтение денег, «Довезти»."""
import sys
import types
from datetime import timedelta
from unittest.mock import Mock

from django.contrib.admin.sites import site
from django.contrib.messages import get_messages
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from ai.models import GenerationLog

from ..admin import AssetAdmin, TakeAdmin, journal_url
from ..models import Asset, Project, Take
from . import factories as f

ACTION = "redeliver"


class _AdminCase(TestCase):
    def setUp(self):
        self.admin_user = f.make_user(is_staff=True, is_superuser=True)
        self.client.force_login(self.admin_user)
        self.owner = f.make_user(email="owner@example.com")
        self.asset = f.make_asset(self.owner)
        self.shot = f.make_shot(self.owner, inputs=[self.asset])

    def _changelist(self, model="take", query=""):
        url = reverse(f"admin:vstudio_{model}_changelist") + query
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, url)
        return response

    def _rows(self, query=""):
        return set(self._changelist("take", query).context["cl"].result_list)


class ChangelistTests(_AdminCase):
    def setUp(self):
        super().setUp()
        self.queued = f.make_take(self.shot)
        self.done = f.make_take(self.shot, status="done", genlog=True)
        self.lost = f.make_take(self.shot, status="lost", genlog=True)  # журнал: needs_review
        other_shot = f.make_shot(self.owner, model_ref="kwaivgi/kling-v3", model=None)
        self.kling = f.make_take(other_shot, status="failed")

    def test_all_changelists_open(self):
        for model in ("project", "asset", "shot", "take"):
            self._changelist(model)

    def test_link_from_generation_log_filters_by_uid(self):
        # adminapi.generations строит ссылку reverse("admin:vstudio_take_changelist")?uid=…
        self.assertEqual(self._rows(f"?uid={self.lost.uid}"), {self.lost})

    def test_filters(self):
        self.assertEqual(self._rows("?status__exact=lost"), {self.lost})
        self.assertEqual(self._rows("?charge_state__exact=reserved"), {self.queued})
        self.assertEqual(self._rows("?review=1"), {self.lost})
        self.assertEqual(self._rows("?review=0"), {self.queued, self.done, self.kling})
        self.assertEqual(self._rows("?model_ref=kwaivgi/kling-v3"), {self.kling})

    def test_search_by_provider_id_and_email(self):
        self.assertEqual(self._rows(f"?q={self.done.provider_id}"), {self.done})
        self.assertEqual(len(self._rows("?q=owner@example.com")), 4)


class TakeChangeViewTests(_AdminCase):
    def test_view_only_with_journal_link(self):
        take = f.make_take(self.shot, status="lost", genlog=True)
        url = reverse("admin:vstudio_take_change", args=[take.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn(journal_url(take.uid), html)
        self.assertIn(f"/admin-new/generations?q={take.uid}", html)
        self.assertIn("нужен разбор", html)
        # Деньги и статус только для чтения: формы сохранения нет вовсе.
        self.assertNotIn('name="_save"', html)
        self.assertNotIn('name="credits_reserved"', html)
        self.assertNotIn('name="charge_state"', html)
        # POST на изменение запрещён.
        before = (take.status, take.charge_state, take.credits_reserved)
        response = self.client.post(url, {"status": "done", "charge_state": "charged",
                                          "credits_reserved": 0})
        self.assertEqual(response.status_code, 403)
        take.refresh_from_db()
        self.assertEqual((take.status, take.charge_state, take.credits_reserved), before)

    def test_take_without_journal(self):
        take = f.make_take(self.shot)
        response = self.client.get(reverse("admin:vstudio_take_change", args=[take.pk]))
        self.assertContains(response, "искать в журнале")

    def test_no_add(self):
        self.assertEqual(self.client.get(reverse("admin:vstudio_take_add")).status_code, 403)
        self.assertEqual(self.client.get(reverse("admin:vstudio_shot_add")).status_code, 403)

    def test_open_take_cannot_be_deleted(self):
        model_admin = site._registry[Take]
        request = RequestFactory().get("/")
        request.user = self.admin_user
        self.assertFalse(model_admin.has_delete_permission(request, f.make_take(self.shot)))
        self.assertTrue(model_admin.has_delete_permission(
            request, f.make_take(self.shot, status="failed")))
        open_take = f.make_take(self.shot, status="running")
        response = self.client.post(reverse("admin:vstudio_take_delete", args=[open_take.pk]),
                                    {"post": "yes"})
        self.assertEqual(response.status_code, 403)
        self.assertTrue(Take.objects.filter(pk=open_take.pk).exists())

    def test_shot_change_view_shows_inputs_and_takes(self):
        take = f.make_take(self.shot)
        response = self.client.get(reverse("admin:vstudio_shot_change", args=[self.shot.pk]))
        self.assertContains(response, reverse("admin:vstudio_take_change", args=[take.pk]))
        self.assertContains(response, self.shot.prompt_text)
        self.assertNotContains(response, 'name="_save"')


class RedeliverActionTests(_AdminCase):
    def setUp(self):
        super().setUp()
        self.lost = f.make_take(self.shot, status="lost", genlog=True)
        self.lost2 = f.make_take(self.shot, status="lost", genlog=True)
        self.done = f.make_take(self.shot, status="done")
        self.calls = []
        self.fake = types.ModuleType("vstudio.pipeline")
        self.fake.admin_redeliver = self._redeliver
        saved = sys.modules.get("vstudio.pipeline")

        def restore():
            # Настоящий pipeline (BE-7) вернуть на место, если он был загружен.
            if saved is None:
                sys.modules.pop("vstudio.pipeline", None)
            else:
                sys.modules["vstudio.pipeline"] = saved

        self.addCleanup(restore)
        sys.modules["vstudio.pipeline"] = self.fake

    def _redeliver(self, take_id):
        self.calls.append(take_id)
        return True

    def _run(self, *takes):
        url = reverse("admin:vstudio_take_changelist")
        response = self.client.post(url, {"action": ACTION, "index": 0,
                                          "_selected_action": [t.pk for t in takes]}, follow=True)
        self.assertEqual(response.status_code, 200)
        return [str(m) for m in get_messages(response.wsgi_request)]

    def test_calls_pipeline_only_for_lost(self):
        msgs = self._run(self.lost, self.lost2, self.done)
        self.assertEqual(sorted(self.calls), sorted([self.lost.pk, self.lost2.pk]))
        self.assertTrue(any("Довоз запущен: 2" in m for m in msgs), msgs)
        self.assertTrue(any("Пропущено 1" in m for m in msgs), msgs)

    def test_one_failure_does_not_stop_others(self):
        def flaky(take_id):
            if take_id == self.lost.pk:
                raise ValueError("провайдер не отдал файл")
            self.calls.append(take_id)
            return None

        self.fake.admin_redeliver = flaky
        msgs = self._run(self.lost, self.lost2)
        self.assertEqual(self.calls, [self.lost2.pk])
        self.assertTrue(any("провайдер не отдал файл" in m for m in msgs), msgs)
        self.assertTrue(any("Довоз запущен: 1" in m for m in msgs), msgs)

    def test_refusal_is_reported(self):
        self.fake.admin_redeliver = Mock(return_value=False)
        msgs = self._run(self.lost)
        self.assertTrue(any("отказ" in m for m in msgs), msgs)

    def test_pipeline_not_ready(self):
        sys.modules["vstudio.pipeline"] = None  # import → ImportError
        msgs = self._run(self.lost)
        self.assertTrue(any("Довоз ещё не подключён" in m for m in msgs), msgs)
        self.assertEqual(Take.objects.get(pk=self.lost.pk).status, "lost")

    def test_action_needs_permission(self):
        model_admin = site._registry[Take]
        request = RequestFactory().get("/")
        request.user = f.make_user(is_staff=True)
        self.assertNotIn(ACTION, model_admin.get_actions(request))
        request.user = self.admin_user
        self.assertIn(ACTION, model_admin.get_actions(request))


class AssetAndProjectAdminTests(_AdminCase):
    def test_soft_delete_and_restore(self):
        url = reverse("admin:vstudio_asset_changelist")
        self.client.post(url, {"action": "soft_delete", "index": 0,
                               "_selected_action": [self.asset.pk]})
        self.asset.refresh_from_db()
        self.assertIsNotNone(self.asset.deleted_at)
        self.client.post(url, {"action": "restore", "index": 0,
                               "_selected_action": [self.asset.pk]})
        self.asset.refresh_from_db()
        self.assertIsNone(self.asset.deleted_at)

    def test_asset_filters(self):
        gone = f.make_asset(self.owner, deleted_at=timezone.now())
        rows = set(self._changelist("asset", "?deleted=1").context["cl"].result_list)
        self.assertEqual(rows, {gone})

    def test_label_edit_does_not_clobber_worker_fields(self):
        # Воркер успел перевести ассет в ready, пока админ держал форму.
        stale = Asset.objects.get(pk=self.asset.pk)
        stale.status = "pending"
        Asset.objects.filter(pk=self.asset.pk).update(status="ready", width=2048)
        stale.label = "Анна"
        form = Mock(changed_data=["label"])
        request = RequestFactory().post("/")
        request.user = self.admin_user
        AssetAdmin(Asset, site).save_model(request, stale, form, change=True)
        fresh = Asset.objects.get(pk=self.asset.pk)
        self.assertEqual((fresh.label, fresh.status, fresh.width), ("Анна", "ready", 2048))

    def test_project_rename_via_admin(self):
        project = self.shot.project
        url = reverse("admin:vstudio_project_change", args=[project.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        later = timezone.now() + timedelta(hours=2)
        Project.objects.filter(pk=project.pk).update(last_activity_at=later)
        response = self.client.post(url, {"title": "Новое имя", "is_archived": "on"})
        self.assertEqual(response.status_code, 302)
        project.refresh_from_db()
        self.assertEqual((project.title, project.is_archived), ("Новое имя", True))
        self.assertEqual(project.last_activity_at, later)

    def test_generation_log_link_target_exists(self):
        # Ссылка BE-1 (adminapi.generations) должна разрешаться, когда vstudio подключён.
        self.assertEqual(reverse("admin:vstudio_take_changelist"), "/admin/vstudio/take/")
        log = GenerationLog.objects.create(kind="video", source="vstudio",
                                           params={"take": "0" * 32})
        from adminapi.generations import _take_link
        self.assertEqual(_take_link(log), ("0" * 32, f"/admin/vstudio/take/?uid={'0' * 32}"))


class TakeAdminUnitTests(TestCase):
    def test_redeliver_permission_for_plain_staff(self):
        model_admin = TakeAdmin(Take, site)
        request = RequestFactory().get("/")
        request.user = f.make_user(is_staff=False)
        self.assertFalse(model_admin.has_redeliver_permission(request))
