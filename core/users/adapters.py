from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.contrib.auth import get_user_model


class SocialAccountAdapter(DefaultSocialAccountAdapter):
    """Map Google profile data into our custom User model.

    Ensures email is set and tries to populate first/last name
    from common Google fields.
    """

    def populate_user(self, request, sociallogin, data):
        user = super().populate_user(request, sociallogin, data)

        extra = getattr(sociallogin.account, "extra_data", {}) or {}

        email = data.get("email") or extra.get("email")
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

        return user

    def pre_social_login(self, request, sociallogin):
        """Auto-link social account to existing user by email.

        Prevents IntegrityError(UNIQUE email) when Google returns an email
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
            return

        User = get_user_model()
        try:
            existing = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            return

        # Attach this social account to the existing user
        sociallogin.connect(request, existing)
