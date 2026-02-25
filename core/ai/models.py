from django.db import models
from users.models import User
from django.utils import timezone
import uuid

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

    class Meta:
        verbose_name = "GPT модель"
        verbose_name_plural = "GPT модели"


class AiProvider(models.Model):
    NAME_GPT = "GPT"
    NAME_TOPMEDIA = "Topmedia"
    NAME_DALLE = "Dall-e"

    NAME_CHOICES = [
        (NAME_GPT, "GPT"),
        (NAME_TOPMEDIA, "Topmedia"),
        (NAME_DALLE, "Dall-e"),
    ]

    NAME_TO_SLUG = {
        NAME_GPT: "gpt",
        NAME_TOPMEDIA: "topmedia",
        NAME_DALLE: "dall-e",
    }

    name = models.CharField(max_length=100, unique=True, choices=NAME_CHOICES)
    slug = models.SlugField(unique=True, editable=False)
    base_url = models.URLField(help_text="API URL", blank=True, null=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    token = models.CharField(max_length=255)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        canonical_slug = self.NAME_TO_SLUG.get(self.name)
        if canonical_slug:
            self.slug = canonical_slug
        elif self.slug:
            self.slug = self.slug.strip().lower()
        super().save(*args, **kwargs)

    class Meta:
        verbose_name = "AI провайдер"
        verbose_name_plural = "AI провайдеры"


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

    class Meta:
        verbose_name = "AI шаблон промпта"
        verbose_name_plural = "AI шаблоны промптов"


class AiPromptTemplateFavorite(models.Model):
    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name='favorite_templates')
    template = models.JSONField(help_text="Template data in JSON format")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.email} favorite templates"

    class Meta:
        verbose_name = "Избранный шаблон"
        verbose_name_plural = "Избранные шаблоны"


class AiChatSession(models.Model):
    """Одна сессия чата с ИИ (как диалог в GPT)."""
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="ai_chat_sessions")
    provider = models.ForeignKey(
        AiProvider, on_delete=models.SET_NULL, null=True, blank=True, related_name="chat_sessions")
    title = models.CharField(max_length=255, blank=True,
                             help_text="Название чата (можно генерировать по первому сообщению)")
    chat_mode = models.CharField(max_length=20, default='text-chat')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"Chat {self.id} ({self.user.email})"

    class Meta:
        verbose_name = "AI сессия чата"
        verbose_name_plural = "AI сессии чата"


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
        verbose_name = "AI сообщение чата"
        verbose_name_plural = "AI сообщения чата"


def _gen_image_upload_path(instance: "AiGeneratedImage", filename: str) -> str:
    uid = instance.uniqid or uuid.uuid4().hex
    instance.uniqid = uid
    # keep original extension if provided
    ext = "" if "." not in filename else filename.split(".")[-1]
    name = f"image.{ext or 'png'}"
    return f"generated/{instance.user_id}/{uid}/{name}"


class AiGeneratedImage(models.Model):
    """Сгенерированное изображение, связанное с пользователем и (опционально) сессией чата."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="generated_images")
    session = models.ForeignKey('AiChatSession', on_delete=models.SET_NULL, null=True, blank=True, related_name="generated_images")
    provider = models.ForeignKey('AiProvider', on_delete=models.SET_NULL, null=True, blank=True)
    model_name = models.CharField(max_length=100, default="gpt-image-1")
    prompt = models.TextField()
    uniqid = models.CharField(max_length=64, editable=False, db_index=True)
    image = models.ImageField(upload_to=_gen_image_upload_path)
    size = models.CharField(max_length=20, default="1024x1024")
    meta = models.JSONField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.user_id}:{self.model_name}:{self.uniqid}"

    class Meta:
        verbose_name = "AI сгенерированное изображение"
        verbose_name_plural = "AI сгенерированные изображения"
