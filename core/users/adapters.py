import logging
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from allauth.core.exceptions import ImmediateHttpResponse
from django.contrib.auth import get_user_model
from django.conf import settings
from django.http import HttpResponseRedirect


def _frontend_base_from_request(request) -> str:
    configured = (getattr(settings, "SITE_BASE_URL", "") or "").strip().rstrip("/")
    raw_host = (
        request.headers.get("x-forwarded-host")
        or request.headers.get("host")
        or request.get_host()
    )
    host = (raw_host or "").split(",")[0].strip()
    proto_raw = request.headers.get("x-forwarded-proto") or ""
    proto = (proto_raw.split(",")[0].strip().lower() or ("https" if request.is_secure() else "http"))
    if host:
        return f"{proto}://{host}"
    return configured or "http://127.0.0.1:3000"


class SocialAccountAdapter(DefaultSocialAccountAdapter):
    """Map social profile data into our custom User model."""

    @staticmethod
    def _provider_id(sociallogin) -> str:
        try:
            return (sociallogin.account.provider or "").strip().lower()
        except Exception:
            return ""

    @staticmethod
    def _account_uid(sociallogin) -> str:
        try:
            return str(sociallogin.account.uid or "").strip()
        except Exception:
            return ""

    def _build_fallback_email(self, sociallogin) -> str:
        provider = self._provider_id(sociallogin) or "social"
        uid = self._account_uid(sociallogin) or "user"
        return f"{provider}_{uid}@social.esai.local"

    def populate_user(self, request, sociallogin, data):
        user = super().populate_user(request, sociallogin, data)

        extra = getattr(sociallogin.account, "extra_data", {}) or {}
        provider = self._provider_id(sociallogin)

        email = data.get("email") or extra.get("email")
        if not email:
            email = self._build_fallback_email(sociallogin)
        if email and not getattr(user, "email", None):
            user.email = email

        given = data.get("given_name") or data.get("first_name") or extra.get("given_name")
        family = data.get("family_name") or data.get("last_name") or extra.get("family_name")

        # Fallback: try split full name
        if not given and not family:
            full = data.get("name") or extra.get("name") or ""
            parts = [p for p in (full or "").split(" ") if p]
            if parts:
                given = parts[0]
                family = " ".join(parts[1:]) if len(parts) > 1 else family

        if given and not getattr(user, "first_name", None):
            user.first_name = given
        if family and not getattr(user, "last_name", None):
            user.last_name = family

        telegram_username = (
            extra.get("username")
            or data.get("username")
            or extra.get("telegram_username")
            or ""
        )
        if provider == "telegram" and telegram_username and not getattr(user, "telegram", None):
            user.telegram = str(telegram_username).strip().lstrip("@")[:30]

        user.is_confirmed = True

        return user

    def pre_social_login(self, request, sociallogin):
        """Auto-link social account to existing user by email.

        Prevents IntegrityError(UNIQUE email) when provider returns an email
        that already exists in our DB from classic (password/code) signup.
        """
        # If account already linked or no email — nothing to do
        if sociallogin.is_existing:
            return

        extra = getattr(sociallogin.account, "extra_data", {}) or {}
        email = (
            extra.get("email")
            or getattr(sociallogin.user, "email", None)
        )
        if not email:
            # Providers like Telegram/Instagram may not expose email. In that
            # case we keep the generated fallback email and continue signup.
            return

        User = get_user_model()
        try:
            existing = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            return

        # Attach this social account to the existing user
        try:
            sociallogin.connect(request, existing)
        except Exception as exc:
            # Any DB constraint issues -> back to signin with an error marker
            site_base = _frontend_base_from_request(request)
            raise ImmediateHttpResponse(HttpResponseRedirect(f"{site_base}/auth/signin?error=link_failed"))

    def on_authentication_error(
        self,
        request,
        provider,
        error=None,
        exception=None,
        extra_context=None,
    ):
        """Handle provider/auth errors and redirect to frontend.

        This is the modern hook used by allauth (authentication_error is deprecated).
        We raise ImmediateHttpResponse so allauth returns our redirect instead of
        rendering the default error template.
        """
        log = logging.getLogger(__name__)
        provider_id = getattr(provider, "id", str(provider))
        log.error(
            "Social auth error from provider=%s: %s | exc=%s",
            provider_id,
            error,
            exception,
        )

        site_base = _frontend_base_from_request(request)
        response = HttpResponseRedirect(f"{site_base}/auth/signin?error=social_login_failed")
        raise ImmediateHttpResponse(response)

    def save_user(self, request, sociallogin, form=None):
        user = super().save_user(request, sociallogin, form=form)
        if user and not getattr(user, "free_plan_activated", False):
            try:
                from users.services import activate_free_plan_for_user
                activate_free_plan_for_user(user)
            except Exception:
                pass
        return user
