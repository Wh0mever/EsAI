from django.core.management.base import BaseCommand
from django.conf import settings


class Command(BaseCommand):
    help = "Ensure django-allauth Google SocialApp is configured for current SITE_ID"

    def handle(self, *args, **options):
        try:
            from allauth.socialaccount.models import SocialApp
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"allauth not installed: {e}"))
            return 1

        from django.contrib.sites.models import Site

        site_id = getattr(settings, "SITE_ID", 1)
        try:
            site = Site.objects.get(id=site_id)
        except Site.DoesNotExist:
            self.stderr.write(self.style.ERROR(f"Site with id={site_id} does not exist"))
            return 1

        # Read creds from settings (populated via env in settings.py)
        cfg = (getattr(settings, "SOCIALACCOUNT_PROVIDERS", {}) or {}).get("google", {})
        app_cfg = (cfg or {}).get("APP", {}) or {}
        client_id = app_cfg.get("client_id") or ""
        secret = app_cfg.get("secret") or ""

        if not client_id or not secret:
            self.stderr.write(self.style.ERROR("GOOGLE_CLIENT_ID/SECRET are not configured in settings"))
            return 1

        app, created = SocialApp.objects.get_or_create(
            provider="google",
            defaults={"name": "Google", "client_id": client_id, "secret": secret},
        )
        if not created:
            changed = []
            if app.client_id != client_id:
                app.client_id = client_id
                changed.append("client_id")
            if app.secret != secret:
                app.secret = secret
                changed.append("secret")
            if changed:
                app.save(update_fields=changed)

        # Ensure site linkage
        if site not in app.sites.all():
            app.sites.add(site)

        self.stdout.write(self.style.SUCCESS(
            f"SocialApp[google] is configured and linked to Site(id={site_id}, domain={site.domain})"
        ))
        return 0

