import logging
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from allauth.core.exceptions import ImmediateHttpResponse
from django.contrib.auth import get_user_model
from django.conf import settings
from django.http import HttpResponseRedirect

logger = logging.getLogger(__name__)


def _allowed_frontend_hosts() -> set:
    """Allowlist разрешённых хостов для редиректа с JWT.

    Собираем из доверенных настроек (SITE_BASE_URL, CSRF_TRUSTED_ORIGINS,
    ALLOWED_HOSTS). Хост из запроса (в т.ч. x-forwarded-host) принимается
    ТОЛЬКО если он есть в этом списке — иначе защита от host-poisoning.
    """
    from urllib.parse import urlsplit

    hosts = set()
    configured = (getattr(settings, "SITE_BASE_URL", "") or "").strip().rstrip("/")
    if configured:
        netloc = urlsplit(configured).netloc
        if netloc:
            hosts.add(netloc.lower())
    for origin in (getattr(settings, "CSRF_TRUSTED_ORIGINS", []) or []):
        netloc = urlsplit(origin).netloc
        if netloc:
            hosts.add(netloc.lower())
    for h in (getattr(settings, "ALLOWED_HOSTS", []) or []):
        h = (h or "").strip().lower().lstrip("*.")
        if h and h != "*":
            hosts.add(h)
    return hosts


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
    # Защита от host-poisoning: доверяем присланному хосту ТОЛЬКО если он
    # в allowlist. Иначе JWT-редирект мог бы уйти на домен атакующего (ATO).
    if host and host.split(":")[0].lower() in _allowed_frontend_hosts():
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

        # Аватар из соц-входа: Telegram → photo_url, Google → picture.
        avatar = (extra.get("photo_url") or extra.get("picture") or "").strip()
        if avatar and not getattr(user, "avatar_url", ""):
            user.avatar_url = avatar[:512]

        user.is_confirmed = True

        return user

    def is_auto_signup_allowed(self, request, sociallogin):
        """Всегда авто-создаём аккаунт соц-входа БЕЗ промежуточной формы allauth.

        Telegram не отдаёт email → allauth по умолчанию показывает свою страшную
        форму «Зарегистрируйтесь / укажите email». Нам это не нужно: email-фолбэк
        проставляется в populate_user, аккаунт создаётся при первом входе сам
        (как у Google). Возвращаем True → форма пропускается, юзер логинится сразу.
        """
        return True

    def pre_social_login(self, request, sociallogin):
        """Auto-link social account to existing user by email.

        Prevents IntegrityError(UNIQUE email) when provider returns an email
        that already exists in our DB from classic (password/code) signup.
        """
        extra = getattr(sociallogin.account, "extra_data", {}) or {}

        # Чёрный список (домен почты / IP) — до всего остального, иначе успеем
        # обновить аватар и связать аккаунт заблокированному пользователю.
        # Существующему аккаунту вход рубим только при «Закрыть и вход»;
        # для нового запрет действует всегда.
        try:
            from .antifraud import get_client_ip
            from .blocklist import find_block

            _email = (extra.get("email") or getattr(sociallogin.user, "email", "") or "")
            if find_block(
                email=_email,
                ip=get_client_ip(request) or "",
                for_login=bool(sociallogin.is_existing),
            ):
                site_base = _frontend_base_from_request(request)
                raise ImmediateHttpResponse(
                    HttpResponseRedirect(f"{site_base}/auth/signin?error=blocked")
                )
        except ImmediateHttpResponse:
            raise
        except Exception:
            logger.exception("blocklist: проверка соц-входа упала")

        # Аватар: обновляем на КАЖДОМ входе (фото в Telegram/Google могло
        # смениться). Для нового юзера (ещё без pk) аватар проставит populate_user.
        avatar = (extra.get("photo_url") or extra.get("picture") or "").strip()[:512]
        if avatar:
            u = getattr(sociallogin, "user", None)
            if u is not None and getattr(u, "pk", None) and getattr(u, "avatar_url", "") != avatar:
                u.avatar_url = avatar
                try:
                    u.save(update_fields=["avatar_url"])
                except Exception:
                    pass

        # If account already linked or no email — nothing to do
        if sociallogin.is_existing:
            return

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
        # Приветственный бонус (3000 токенов) новым пользователям соц-входа.
        # Антифрод v1: approve → начислить сразу, delay → отложить на 24ч.
        # Идемпотентно (по reason='welcome'), повторно не начислит.
        if user:
            try:
                from .antifraud import maybe_grant_welcome_bonus
                maybe_grant_welcome_bonus(user, request)
            except Exception:
                pass
            try:
                # Привязка реферера (код в cookie esai_ref). Кредиты НЕ начисляются
                # тут — реферер получает % при каждом пополнении приглашённого.
                from .services import maybe_link_referrer
                maybe_link_referrer(request, user)
            except Exception:
                pass
            try:
                # Промокод при регистрации (cookie esai_promo или поле promo) — тихо.
                from .services import maybe_activate_promo_on_signup
                maybe_activate_promo_on_signup(request, user)
            except Exception:
                pass
            # Пометка «новый пользователь» для приветственного окна на фронте.
            # save_user вызывается только при СОЗДАНИИ соц-аккаунта; auth_complete
            # прочитает флаг и допишет welcome=1 в редирект на /auth/callback.
            try:
                from django.core.cache import cache
                cache.set(f"welcome_show:{user.pk}", "1", 600)
            except Exception:
                pass
        return user
