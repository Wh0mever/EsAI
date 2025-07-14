from django.db import models
from users.models import User

# Create your models here.


class AiProvider(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(unique=True)
    base_url = models.URLField(help_text="Базовый URL API")
    description = models.TextField(blank=True)

    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name

class AiToken(models.Model):
    provider = models.ForeignKey(AiProvider, on_delete=models.CASCADE, related_name='tokens')
    name = models.CharField(max_length=100, help_text="Название ключа (например, для продакшна)")
    token = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)

    usage_limit = models.IntegerField(null=True, blank=True, help_text="Максимальное кол-во запросов в месяц")
    usage_count = models.IntegerField(default=0)

    last_used = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.provider.slug})"


class AiPromptPreset(models.Model):
    TASK_TYPES = [
        ('text_title', 'Text Title Generation'),
        ('text_summary', 'Text Summary'),
        ('music_style', 'Music Style Prompt'),
        ('image_style', 'Image Stylizer'),
        ('universal', 'Universal Prompt Layer'),
    ]

    provider = models.ForeignKey(AiProvider, on_delete=models.CASCADE, related_name='prompts')
    task_type = models.CharField(max_length=50, choices=TASK_TYPES)
    title = models.CharField(max_length=100)
    prompt_prefix = models.TextField(blank=True)
    prompt_suffix = models.TextField(blank=True)

    min_user_role = models.CharField(
        max_length=50,
        default='free',
        help_text="Минимальный тариф, которому доступен этот пресет"
    )

    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.title} ({self.task_type})"

class AiGenerationLog(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='ai_logs')
    provider = models.ForeignKey(AiProvider, on_delete=models.SET_NULL, null=True)
    prompt = models.TextField()
    response = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    task_type = models.CharField(max_length=50, blank=True)
    status = models.CharField(max_length=20, choices=[('success', 'Success'), ('error', 'Error')], default='success')
    error_message = models.TextField(blank=True)

    tokens_used = models.IntegerField(null=True, blank=True)
    latency_ms = models.IntegerField(null=True, blank=True)

    def __str__(self):
        return f"{self.user.username} — {self.provider.slug} — {self.created_at.strftime('%Y-%m-%d %H:%M')}"
