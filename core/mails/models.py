from django.db import models
from django.contrib.auth import get_user_model
from django.core.validators import validate_email

User = get_user_model()


# ===== Simplified mailer =====

class MailContext(models.Model):
    name = models.CharField(max_length=200)
    data = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "JSON-контекст. Правила рендера: каждый ключ — новая строка.\n"
            "Если в ключе есть 'title' — строка становится заголовком.\n"
            "Если в ключе есть 'link' — значение объект {href, text}.\n"
            "Если в ключе есть 'list' — значение список или объект элементов.\n"
            "Порядок вывода соответствует порядку ключей."
        ),
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "id"]
        verbose_name = "Почтовый контекст"
        verbose_name_plural = "Почтовые контексты"

    def __str__(self):
        return self.name


class SimpleMail(models.Model):
    name = models.CharField(max_length=200, help_text="Внутреннее имя рассылки")
    subject = models.CharField(max_length=255)
    context = models.ForeignKey(MailContext, null=True, blank=True, on_delete=models.SET_NULL, related_name="mails")

    # Режим рассылки
    send_to_all = models.BooleanField(default=False, help_text="Отправить всем активным пользователям")
    recipients = models.ManyToManyField(
        User,
        blank=True,
        related_name="simple_mail_recipients",
        help_text="Выберите конкретных пользователей для отправки (используется, если не включено 'Отправить всем').",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    last_sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "id"]
        verbose_name = "Простое письмо"
        verbose_name_plural = "Простые письма"

    def __str__(self):
        return self.name

    def build_recipients(self) -> list[str]:
        if self.send_to_all:
            qs = User.objects.filter(is_active=True).exclude(email__isnull=True).exclude(email="")
            users = [u.email.lower() for u in qs]
            return sorted(set(users))
        # иначе — выбранные пользователи из M2M
        qs = (self.recipients.all() if self.pk else User.objects.none())
        emails = [u.email.lower() for u in qs if u.email]
        return sorted(set(emails))
