from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Ensure configured django-allauth SocialApps are present for current SITE_ID"

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

        providers = ("google", "facebook", "telegram", "instagram")
        configured_any = False

        for provider in providers:
            cfg = (getattr(settings, "SOCIALACCOUNT_PROVIDERS", {}) or {}).get(provider, {})
            app_cfg = (cfg or {}).get("APP", {}) or {}
            client_id = (app_cfg.get("client_id") or "").strip()
            secret = (app_cfg.get("secret") or "").strip()

            if not client_id or not secret:
                self.stdout.write(f"Skip {provider}: client_id/secret are not configured")
                continue

            configured_any = True
            app, created = SocialApp.objects.get_or_create(
                provider=provider,
                defaults={
                    "name": provider.capitalize(),
                    "client_id": client_id,
                    "secret": secret,
                },
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

            if site not in app.sites.all():
                app.sites.add(site)

            self.stdout.write(self.style.SUCCESS(
                f"SocialApp[{provider}] is configured and linked to Site(id={site_id}, domain={site.domain})"
            ))

        if not configured_any:
            self.stdout.write("No configured social apps found in settings")

        return 0
