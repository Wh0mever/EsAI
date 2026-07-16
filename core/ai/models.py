from django.db import models
from users.models import User
from django.utils import timezone
import uuid

# Create your models here.

def _gen_chat_session_uid() -> str:
    return uuid.uuid4().hex


class GPTModels(models.Model):
    """AI-модель OpenRouter (управляется из админки, без хардкода)."""
    name = models.CharField(max_length=100, unique=True, help_text="Отображаемое имя модели")
    openrouter_id = models.CharField(
        max_length=128, unique=True, default="",
        help_text="Системный ID модели в OpenRouter (напр. 'openai/gpt-4o')")
    description = models.TextField(blank=True)
    max_tokens = models.IntegerField(help_text="Maximum tokens allowed")
    system_prompt = models.TextField(
        blank=True, default="",
        help_text="Системный промпт по умолчанию для этой модели")
    temperature = models.FloatField(
        null=True, blank=True,
        help_text="Temperature (0..2). Пусто — использовать значение по умолчанию")
    top_p = models.FloatField(
        null=True, blank=True,
        help_text="Top-p (0..1). Пусто — использовать значение по умолчанию")
    markup_coefficient = models.DecimalField(
        max_digits=6, decimal_places=3, default=1.0,
        help_text="ТАРИФ: сколько кредитов списывать за 1000 токенов "
                  "(списание = total_tokens × тариф ÷ 1000). Напр. 17 = 17 кр/1000 токенов.")
    free_tier = models.BooleanField(
        default=False,
        help_text="Доступна гостям и бесплатным пользователям. НЕ зависит от тарифа: "
                  "бесплатная модель тоже списывает кредиты, просто не заблокирована пэйволом.")
    CATEGORY_CHOICES = [
        ("chat", "💬 Для общения"),
        ("writing", "✍️ Тексты и SEO"),
        ("coding", "💻 Программирование"),
        ("reasoning", "🧠 Анализ и рассуждения"),
        ("search", "🌐 Поиск в интернете"),
        ("image", "🖼️ Изображения"),
        ("fast", "⚡️ Быстрые"),
        ("budget", "💰 Экономичные"),
        ("video", "🎬 Видео"),
    ]
    category = models.CharField(
        max_length=20, choices=CATEGORY_CHOICES, default="chat",
        help_text="Группа в списке моделей на сайте (по назначению, не по вендору).")
    recommended = models.BooleanField(
        default=False,
        help_text="Показывать также в группе «⭐ Рекомендуемые» наверху списка.")
    sort_order = models.PositiveIntegerField(default=100)
    is_active = models.BooleanField(default=True)
    supports_vision = models.BooleanField(
        default=False,
        help_text="Модель принимает изображения (vision). Если выкл — отправка картинки вернёт понятную ошибку, без вызова провайдера.")
    CARTOON_STAGE_CHOICES = [
        ("", "—"),
        ("script", "Сценарий"),
        ("image", "Изображения"),
        ("video", "Видео"),
    ]
    cartoon_stage = models.CharField(
        max_length=10, blank=True, default="", choices=CARTOON_STAGE_CHOICES,
        help_text="Этап в студии мультфильмов. Пусто — модель не участвует в студии.")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def is_free(self) -> bool:
        """Доступна ли модель на бесплатном тарифе.

        Теперь определяется ЯВНЫМ флагом free_tier (а не коэффициентом), т.к.
        после нормализации тариф бесплатной модели может быть >1 (напр. Gemini=11).
        Гость и free-пользователь могут использовать только такие модели; остальные —
        только платным (ТЗ 4.1). Реализация в plans/tiers.py (единый источник правды).
        """
        from plans.tiers import model_is_free
        return model_is_free(self)

    def __str__(self):
        return self.name

    class Meta:
        ordering = ["sort_order", "id"]
        verbose_name = "GPT модель"
        verbose_name_plural = "GPT модели"


class AiProvider(models.Model):
    NAME_GPT = "GPT"

    NAME_CHOICES = [
        (NAME_GPT, "GPT"),
    ]

    NAME_TO_SLUG = {
        NAME_GPT: "gpt",
    }

    name = models.CharField(max_length=100, unique=True, choices=NAME_CHOICES)
    slug = models.SlugField(unique=True, editable=False)
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
    uid = models.CharField(max_length=32, unique=True, db_index=True, editable=False, default=_gen_chat_session_uid)
    provider = models.ForeignKey(
        AiProvider, on_delete=models.SET_NULL, null=True, blank=True, related_name="chat_sessions")
    title = models.CharField(max_length=255, blank=True,
                             help_text="Название чата (можно генерировать по первому сообщению)")
    chat_mode = models.CharField(max_length=20, default='text-chat')
    # Rolling-резюме более ранней части диалога. Свежие сообщения уходят в модель
    # дословно (по токен-бюджету), а всё, что вышло за окно, сворачивается сюда
    # фоновой задачей ai.tasks.summarize_session_context. Позволяет вести очень
    # длинные чаты (сотни/тысячи сообщений) без потери фактов/решений и без роста
    # стоимости запроса. БД/UI по-прежнему хранят всю переписку.
    context_summary = models.TextField(blank=True, default="")
    # id последнего сообщения, уже учтённого в context_summary (инкрементальная
    # суммаризация: сворачиваем только то, что появилось после этой отметки).
    summary_upto_message_id = models.BigIntegerField(null=True, blank=True)
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
        indexes = [
            # Горячий путь: история чата грузится фильтром по session с
            # сортировкой по created_at. Составной индекс убирает full scan.
            models.Index(fields=["session", "created_at"], name="ai_msg_session_created_idx"),
        ]


class AiMessageFeedback(models.Model):
    """Лайк/дизлайк пользователя на ответ ассистента."""
    VALUE_UP = 1
    VALUE_DOWN = -1
    VALUE_CHOICES = [
        (VALUE_UP, "Like"),
        (VALUE_DOWN, "Dislike"),
    ]

    message = models.ForeignKey(
        AiChatMessage, on_delete=models.CASCADE, related_name="feedbacks")
    user = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="ai_message_feedbacks")
    value = models.SmallIntegerField(choices=VALUE_CHOICES, help_text="1 — лайк, -1 — дизлайк")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Feedback {self.value} on message {self.message_id}"

    class Meta:
        unique_together = ("message", "user")
        verbose_name = "Оценка ответа ИИ"
        verbose_name_plural = "Оценки ответов ИИ"
