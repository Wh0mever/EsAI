"""Адреса API программы EsAI Creators (/api/creators/)."""
from django.urls import path

from . import views

app_name = "creators"

urlpatterns = [
    # Публичное: условия программы, переход по ссылке, «кто меня пригласил».
    path("program/", views.ProgramView.as_view(), name="program"),
    path("click/", views.ClickView.as_view(), name="click"),
    path("invite/", views.InviteView.as_view(), name="invite"),
    # Заявка на участие.
    path("application/", views.ApplicationView.as_view(), name="application"),
    # Кабинет креатора.
    path("me/", views.MeView.as_view(), name="me"),
    path("code/check/", views.CodeCheckView.as_view(), name="code-check"),
    path("me/code/", views.MyCodeView.as_view(), name="me-code"),
    path("me/publications/", views.MyPublicationsView.as_view(), name="me-publications"),
    path("me/credits/", views.MyCreditsView.as_view(), name="me-credits"),
    path("me/commissions/", views.MyCommissionsView.as_view(), name="me-commissions"),
    path("me/referrals/", views.MyReferralsView.as_view(), name="me-referrals"),
    path("me/withdrawals/", views.MyWithdrawalsView.as_view(), name="me-withdrawals"),
    path("me/payout-address/", views.PayoutAddressView.as_view(), name="me-payout-address"),
]
