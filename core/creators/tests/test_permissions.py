"""Кто что может: гость, пользователь, сотрудник, главный администратор, креатор.

Таблицы адресов здесь — те же, что в §8.3 и §8.4 спецификации: появился новый
адрес — он должен попасть в одну из них.
"""
from django.test import override_settings

from audit.models import AdminActionLog

from ..models import Creator, CreatorApplication
from . import factories as f
from . import test_api_public as api

API = api.API
M = api.MANAGE + "creators/"

# Адреса кабинета, доступные только креатору: (метод, путь).
CREATOR_ONLY = [
    ("get", "me/"),
    ("patch", "me/"),
    ("get", "code/check/"),
    ("post", "me/code/"),
    ("get", "me/publications/"),
    ("post", "me/publications/"),
    ("get", "me/credits/"),
    ("get", "me/commissions/"),
    ("get", "me/referrals/"),
    ("get", "me/withdrawals/"),
    ("post", "me/withdrawals/"),
    ("put", "me/payout-address/"),
]
# Адреса, которым достаточно входа.
SIGNED_IN = [("get", "application/"), ("post", "application/"), ("get", "invite/")]

# Админка: адреса любого сотрудника. {имя} — номер существующей строки.
STAFF_ROUTES = [
    ("get", "applications/"),
    ("post", "applications/{application}/approve/"),
    ("post", "applications/{application}/reject/"),
    ("get", ""),
    ("get", "{creator}/"),
    ("get", "publications/"),
    ("post", "publications/{publication}/approve/"),
    ("post", "publications/{publication}/reject/"),
    ("get", "referrals/"),
    ("get", "commissions/"),
    ("get", "withdrawals/"),
    ("get", "credits/"),
    ("get", "levels/"),
    ("get", "log/"),
]
# Админка: деньги и структура — только главный администратор.
SUPERUSER_ROUTES = [
    ("post", "applications/{application}/unblock/"),
    ("post", "{creator}/level/"),
    ("post", "{creator}/block/"),
    ("post", "{creator}/unblock/"),
    ("post", "{creator}/code/"),
    ("post", "{creator}/credits/"),
    ("post", "referrals/rebind/"),
    ("post", "referrals/{referral}/clear-suspect/"),
    ("post", "commissions/{commission}/void/"),
    ("post", "commissions/{commission}/release/"),
    ("post", "commissions/{commission}/restore/"),
    ("post", "withdrawals/{withdrawal}/approve/"),
    ("post", "withdrawals/{withdrawal}/reject/"),
    ("post", "withdrawals/{withdrawal}/mark-paid/"),
    ("post", "withdrawals/{withdrawal}/txid/"),
    ("post", "withdrawals/{withdrawal}/reopen/"),
    ("patch", "levels/creator_pro/"),
    ("get", "settings/"),
    ("patch", "settings/"),
    # Отметка возврата живёт рядом с платежами, а не в creators/.
    ("post", "../payments/{payment}/mark-refunded/"),
]


class AdminPermissionTests(api.ApiTestCase):
    def setUp(self):
        super().setUp()
        self.creator = f.make_creator(code="TORA20")
        buyer = f.make_user()
        payment = f.make_payment(buyer)
        self.ids = {
            "creator": self.creator.pk,
            "application": api.make_application().pk,
            "publication": self.creator.publications.create(
                network="instagram", url="https://instagram.com/p/1",
                url_norm="instagram.com/p/1").pk,
            "referral": f.make_referral(self.creator, buyer, suspect=True).pk,
            "commission": f.make_commission(self.creator, payment, buyer=buyer).pk,
            "withdrawal": f.make_withdrawal(self.creator, "10.00").pk,
            "payment": payment.pk,
        }
        self.logs_before = AdminActionLog.objects.count()

    def call(self, client, method, path):
        url = (M + path.format(**self.ids)).replace("creators/../", "")
        return getattr(client, method)(url, {}, format="json")

    def test_every_route_is_listed(self):
        """Таблицы покрывают все адреса раздела: новый адрес без строки здесь — ошибка."""
        from adminapi import urls

        declared = {str(p.pattern) for p in urls.urlpatterns
                    if str(p.pattern).startswith("creators/")
                    or str(p.pattern).endswith("mark-refunded/")}
        listed = set()
        for _method, path in STAFF_ROUTES + SUPERUSER_ROUTES:
            route = ("creators/" + path).replace("creators/../", "")
            for name in self.ids:
                route = route.replace("{" + name + "}", "<int:pk>")
            listed.add(route.replace("levels/creator_pro/", "levels/<slug:key>/"))
        self.assertEqual(declared, listed)

    def test_anonymous_gets_401(self):
        client = self.client_for()
        for method, path in STAFF_ROUTES + SUPERUSER_ROUTES:
            response = self.call(client, method, path)
            self.assertEqual(response.status_code, 401, (method, path, response.data))
        self.assertEqual(AdminActionLog.objects.count(), self.logs_before)

    def test_ordinary_user_gets_403(self):
        client = self.client_for(f.make_user())
        for method, path in STAFF_ROUTES + SUPERUSER_ROUTES:
            response = self.call(client, method, path)
            self.assertEqual(response.status_code, 403, (method, path, response.data))
        # Креатор — не сотрудник: в админку ему тоже нельзя.
        response = self.call(self.client_for(self.creator.user), "get", "")
        self.assertEqual(response.status_code, 403, response.data)
        self.assertEqual(AdminActionLog.objects.count(), self.logs_before)

    def test_staff_is_allowed_on_staff_routes(self):
        client = self.client_for(f.make_user(staff=True))
        for method, path in STAFF_ROUTES:
            response = self.call(client, method, path)
            # 400/409 — отказ сервиса (нет уровня, не тот статус): права пройдены.
            self.assertNotIn(response.status_code, (401, 403, 404, 405),
                             (method, path, response.data))

    def test_staff_gets_403_on_every_superuser_route(self):
        client = self.client_for(f.make_user(staff=True))
        for method, path in SUPERUSER_ROUTES:
            self.assertError(self.call(client, method, path), 403, "superuser_required")
        self.assertEqual(AdminActionLog.objects.count(), self.logs_before)
        self.creator.refresh_from_db()
        self.assertEqual(self.creator.status, "active")

    def test_superuser_is_allowed_everywhere(self):
        client = self.client_for(f.make_user(superuser=True))
        for method, path in STAFF_ROUTES + SUPERUSER_ROUTES:
            response = self.call(client, method, path)
            self.assertNotIn(response.status_code, (401, 403, 404, 405),
                             (method, path, response.data))

    def test_superuser_flag_without_staff_is_not_enough(self):
        user = f.make_user()
        type(user).objects.filter(pk=user.pk).update(is_superuser=True)
        user.refresh_from_db()
        for path in ("settings/", ""):
            response = self.call(self.client_for(user), "get", path)
            self.assertEqual(response.status_code, 403, response.data)

    def test_non_base_level_needs_superuser(self):
        staff = self.client_for(f.make_user(staff=True))
        url = M + f"applications/{self.ids['application']}/approve/"
        self.assertError(staff.post(url, {"level": "creator_pro"}, format="json"),
                         403, "superuser_required")
        self.assertFalse(Creator.objects.exclude(pk=self.creator.pk).exists())
        self.assertEqual(staff.post(url, {"level": "creator"}, format="json").status_code, 200)

    def test_block_on_reject_needs_superuser(self):
        staff = self.client_for(f.make_user(staff=True))
        url = M + f"applications/{self.ids['application']}/reject/"
        self.assertError(staff.post(url, {"block": True}, format="json"),
                         403, "superuser_required")
        self.assertEqual(CreatorApplication.objects.get(pk=self.ids["application"]).status, "new")
        self.assertEqual(staff.post(url, {"reason": "Нет"}, format="json").data["status"],
                         "rejected")

    @override_settings(CREATORS_MODE="off")
    def test_admin_api_has_no_mode_gate(self):
        response = self.call(self.client_for(f.make_user(staff=True)), "get", "")
        self.assertEqual(response.status_code, 200, response.data)


class CreatorPermissionTests(api.ApiTestCase):
    def call(self, client, method, path):
        return getattr(client, method)(API + path, {}, format="json")

    def test_anonymous_gets_401(self):
        client = self.client_for()
        for method, path in CREATOR_ONLY + SIGNED_IN:
            response = self.call(client, method, path)
            self.assertEqual(response.status_code, 401, (method, path, response.data))

    def test_non_creator_gets_403(self):
        client = self.client_for(f.make_user())
        for method, path in CREATOR_ONLY:
            self.assertError(self.call(client, method, path), 403, "not_creator")
        # Сотрудник без строки креатора — тоже не креатор.
        self.assertError(self.call(self.client_for(f.make_user(superuser=True)), "get", "me/"),
                         403, "not_creator")

    def test_applicant_is_not_a_creator_until_approved(self):
        user = f.make_user()
        api.make_application(user)
        self.assertError(self.call(self.client_for(user), "get", "me/"), 403, "not_creator")

    def test_creator_is_allowed(self):
        client = self.client_for(f.make_creator().user)
        for method, path in CREATOR_ONLY:
            response = self.call(client, method, path)
            self.assertNotIn(response.status_code, (401, 403, 404, 405),
                             (method, path, response.data))

    def test_every_creator_route_is_listed(self):
        from .. import urls

        declared = {str(p.pattern) for p in urls.urlpatterns}
        listed = {path for _method, path in CREATOR_ONLY + SIGNED_IN}
        self.assertEqual(declared - listed, {"program/", "click/"})
        self.assertEqual(listed - declared, set())

    @override_settings(CREATORS_MODE="off")
    def test_off_mode_hides_everything(self):
        creator = f.make_creator(f.make_user(superuser=True))
        client = self.client_for(creator.user)
        for method, path in CREATOR_ONLY + SIGNED_IN:
            self.assertError(self.call(client, method, path), 404, "disabled")

    @override_settings(CREATORS_MODE="staff")
    def test_staff_mode(self):
        # Креатор-не-сотрудник и обычный пользователь программы не видят.
        outsider = self.client_for(f.make_creator().user)
        for method, path in CREATOR_ONLY:
            self.assertError(self.call(outsider, method, path), 404, "disabled")
        self.assertError(self.call(self.client_for(f.make_user()), "get", "application/"),
                         404, "disabled")
        # Гость узнаёт только то, что раздела нет.
        self.assertError(self.call(self.client_for(), "get", "me/"), 404, "disabled")
        # Сотрудник-креатор работает как обычно.
        insider = self.client_for(f.make_creator(f.make_user(staff=True)).user)
        self.assertEqual(self.call(insider, "get", "me/").status_code, 200)

    @override_settings(CREATORS_MODE="staff")
    def test_invite_works_for_ordinary_users_in_staff_mode(self):
        creator = f.make_creator(f.make_user(staff=True), code="STAFF01", display_name="Tora")
        user = f.make_user()
        f.make_referral(creator, user)
        response = self.call(self.client_for(user), "get", "invite/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["invited_by"], "Tora")
        # Но вход всё равно нужен.
        self.assertEqual(self.call(self.client_for(), "get", "invite/").status_code, 401)


class RealTokenTests(api.ApiTestCase):
    """Те же проверки с настоящим JWT в заголовке, без force_authenticate."""

    def bearer(self, user):
        from rest_framework.test import APIClient
        from rest_framework_simplejwt.tokens import RefreshToken

        client = APIClient()
        client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
        return client

    def test_creator_cabinet_and_public_page(self):
        creator = f.make_creator()
        client = self.bearer(creator.user)
        self.assertEqual(client.get(API + "me/").status_code, 200)
        me = client.get(API + "program/").data["me"]
        self.assertEqual((me["is_authenticated"], me["is_creator"]), (True, True))
        self.assertError(self.bearer(f.make_user()).get(API + "me/"), 403, "not_creator")

    def test_broken_token_on_a_private_route_is_401(self):
        from rest_framework.test import APIClient

        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION="Bearer not-a-token")
        response = client.get(API + "me/")
        self.assertEqual(response.status_code, 401, response.data)
        self.assertEqual(response.data["code"], "token_not_valid")
        self.assertIsInstance(response.data["detail"], str)
        self.assertIsInstance(response.data["message"], str)

    @override_settings(CREATORS_MODE="staff")
    def test_staff_mode_with_real_tokens(self):
        self.assertError(self.bearer(f.make_creator().user).get(API + "me/"), 404, "disabled")
        staff_creator = f.make_creator(f.make_user(staff=True))
        self.assertEqual(self.bearer(staff_creator.user).get(API + "me/").status_code, 200)

    def test_admin_routes_with_real_tokens(self):
        self.assertEqual(self.bearer(f.make_user(staff=True)).get(M).status_code, 200)
        self.assertError(self.bearer(f.make_user(staff=True)).get(M + "settings/"),
                         403, "superuser_required")
        self.assertEqual(self.bearer(f.make_user(superuser=True)).get(M + "settings/").status_code,
                         200)
        self.assertEqual(self.bearer(f.make_user()).get(M).status_code, 403)
