from allauth.socialaccount.adapter import DefaultSocialAccountAdapter


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

