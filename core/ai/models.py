from django.db import models
from users.models import User

# Create your models here.

class GPTModels(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    max_tokens = models.IntegerField(help_text="Maximum tokens allowed")
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class AiProvider(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(unique=True)
    base_url = models.URLField(help_text="API URL", blank=True, null=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    token = models.CharField(max_length=255)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class AiPromptTemplate(models.Model):
    name = models.CharField(max_length=100, unique=True)
    provider = models.ForeignKey(
        AiProvider, on_delete=models.CASCADE, related_name='prompt_templates')
    template = models.TextField(help_text="Prompt template text")
    purpose = models.CharField(
        max_length=255, help_text="Purpose of the prompt template")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    description = models.TextField(blank=True)

    created_by = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='created_prompt_templates')
    usage_count = models.PositiveIntegerField(
        default=0, help_text="Number of times this template has been used")
    is_active = models.BooleanField(
        default=True, help_text="Is this template currently active?")
    is_public = models.BooleanField(
        default=False, help_text="Is this template visible to all users?")

    def __str__(self):
        return self.name


class AiPromptTemplateFavorite(models.Model):
    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name='favorite_templates')
    template = models.JSONField(help_text="Template data in JSON format")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.email} favorite templates"


class AiChatSession(models.Model):
    """Одна сессия чата с ИИ (как диалог в GPT)."""
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="ai_chat_sessions")
    provider = models.ForeignKey(
        AiProvider, on_delete=models.SET_NULL, null=True, blank=True, related_name="chat_sessions")
    title = models.CharField(max_length=255, blank=True,
                             help_text="Название чата (можно генерировать по первому сообщению)")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"Chat {self.id} ({self.user.email})"


class AiChatMessage(models.Model):
    """Сообщение внутри чата (текст, картинки, аудио и т.д.)."""
    ROLE_CHOICES = [
        ("user", "User"),
        ("assistant", "Assistant"),
        ("system", "System"),
    ]

    session = models.ForeignKey(
        AiChatSession, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    content = models.TextField(
        blank=True, help_text="Текстовое содержимое сообщения")
    attachments = models.JSONField(
        blank=True, null=True, help_text="Список вложений: [{type: 'image', url: '...'}, ...]")
    meta = models.JSONField(
        blank=True, null=True, help_text="Дополнительные метаданные, например токены, затраты и т.д.")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"[{self.role}] {self.content[:30]}"

    class Meta:
        ordering = ["created_at"]
