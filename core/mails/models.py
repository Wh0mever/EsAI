from django.db import models
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.utils import timezone
from django.core.validators import validate_email

User = get_user_model()


class EmailTemplate(models.Model):
    key = models.SlugField(unique=True, help_text="Internal key, e.g. promo_sep")
    name = models.CharField(max_length=200)
    subject = models.CharField(max_length=255)
    body_html = models.TextField(help_text="Django template string")
    body_text = models.TextField(blank=True, default="", help_text="Plain text fallback")
    is_active = models.BooleanField(default=True)
    description = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return f"{self.name} ({self.key})"


class EmailPreference(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="email_pref")
    is_unsubscribed = models.BooleanField(default=False)
    unsubscribed_at = models.DateTimeField(null=True, blank=True)

    def unsubscribe(self):
        self.is_unsubscribed = True
        self.unsubscribed_at = timezone.now()
        self.save(update_fields=["is_unsubscribed", "unsubscribed_at"])

    def __str__(self):
        return f"{self.user} unsubscribed={self.is_unsubscribed}"


class EmailCampaign(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SCHEDULED = "scheduled", "Scheduled"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"

    title = models.CharField(max_length=255)
    template = models.ForeignKey(EmailTemplate, on_delete=models.PROTECT, related_name="campaigns")
    groups = models.ManyToManyField(Group, blank=True, related_name="email_campaigns")
    extra_recipients = models.TextField(
        blank=True, default="",
        help_text="One email per line; will be merged & deduplicated"
    )
    context_json = models.JSONField(default=dict, blank=True)
    from_email = models.EmailField(blank=True, default="")
    scheduled_at = models.DateTimeField(null=True, blank=True)

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    last_run_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="created_email_campaigns"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title} [{self.status}]"

    def parsed_extra_recipients(self) -> list[str]:
        emails = []
        for raw in (self.extra_recipients or "").splitlines():
            email = raw.strip()
            if not email:
                continue
            validate_email(email)
            emails.append(email.lower())
        return emails

    def build_recipients(self) -> list[str]:
        qs = User.objects.filter(is_active=True).exclude(email__isnull=True).exclude(email="")
        if self.groups.exists():
            qs = qs.filter(groups__in=list(self.groups.all())).distinct()

        # respect unsubscribed
        qs = qs.exclude(email_pref__is_unsubscribed=True)

        users = [u.email.lower() for u in qs]
        merged = set(users) | set(self.parsed_extra_recipients())
        return sorted(merged)


class EmailLog(models.Model):
    campaign = models.ForeignKey(EmailCampaign, null=True, blank=True, on_delete=models.SET_NULL, related_name="logs")
    to_email = models.EmailField()
    subject = models.CharField(max_length=255)
    success = models.BooleanField(default=False)
    error = models.TextField(blank=True, default="")
    message_id = models.CharField(max_length=255, blank=True, default="")
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["campaign"]),
            models.Index(fields=["to_email"]),
        ]

    def __str__(self):
        ok = "OK" if self.success else "ERR"
        return f"{self.to_email} {ok} {self.sent_at:%Y-%m-%d %H:%M}"
