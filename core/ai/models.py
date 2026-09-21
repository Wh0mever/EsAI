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
    description = models.TextField(
        blank=True,
        help_text="Описание для каталога /models: одна строка о том, для чего модель.")
    # Короткая метка под названием в выборе модели. Раньше для video-моделей эту
    # роль играло description — из-за чего в каталоге у них вместо описания
    # стояло «Максимальное качество». Теперь у метки своё поле, а description
    # у всех моделей значит одно и то же.
    short_label = models.CharField(
        max_length=64, blank=True, default="",
        verbose_name="Короткая метка",
        help_text=(
            "Подпись под названием при выборе модели, напр. «Максимальное качество». "
            "У видео-моделей задаёт значок качества."
        ))
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


class SharedVideo(models.Model):
    """Публичная ссылка на сгенерированный ролик (esai.kg/v/<slug>).

    Зачем. Клиент просил «поделиться роликом специальной ссылкой, чтобы
    смотреть прямо из Telegram». Файл в /media/ и так открыт наружу, но голая
    ссылка на .mp4 в мессенджере выглядит вложением без превью и без бренда.
    Поэтому ссылка ведёт на нашу страницу с og:video — Telegram, WhatsApp и
    соцсети играют ролик прямо в ленте, а человек видит, что он сделан в EsAI.

    Пути к файлам храним ОТНОСИТЕЛЬНЫМИ (ai_videos/xxx.mp4), а не полными
    URL: домен и MEDIA_URL могут смениться, а ссылка должна пережить переезд.
    """
    slug = models.CharField(
        max_length=24, unique=True, db_index=True,
        verbose_name="Код ссылки", help_text="Часть адреса esai.kg/v/<код>")
    user = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="shared_videos", verbose_name="Автор")
    video_path = models.CharField(
        max_length=512, verbose_name="Файл ролика",
        help_text="Путь в хранилище, например ai_videos/abc.mp4")
    poster_path = models.CharField(
        max_length=512, blank=True, default="", verbose_name="Обложка")
    prompt = models.TextField(blank=True, default="", verbose_name="Запрос")
    model_name = models.CharField(max_length=128, blank=True, default="", verbose_name="Модель")
    kind = models.CharField(
        max_length=10, default="video",
        choices=[("video", "Ролик из чата"), ("cartoon", "Мультфильм из студии")],
        verbose_name="Что за ролик",
        help_text="От этого зависит призыв на публичной странице: ролик зовёт в чат, "
                  "мультфильм — в Cartoon Studio.")
    width = models.PositiveIntegerField(null=True, blank=True, verbose_name="Ширина")
    height = models.PositiveIntegerField(null=True, blank=True, verbose_name="Высота")
    duration = models.FloatField(null=True, blank=True, verbose_name="Длительность, с")
    views = models.PositiveIntegerField(default=0, verbose_name="Просмотров")
    is_active = models.BooleanField(
        default=True, verbose_name="Ссылка активна",
        help_text="Снимите галочку, чтобы закрыть доступ по ссылке")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    def __str__(self):
        return f"/v/{self.slug}"

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "Ссылка на ролик"
        verbose_name_plural = "Ссылки на ролики"


def _gen_job_uid() -> str:
    return uuid.uuid4().hex


class GenerationJob(models.Model):
    """Долгая генерация (видео), которая живёт дольше HTTP-запроса.

    Сайт получает ролик по SSE и держит соединение до восьми минут. Боту так
    нельзя: соединений у него мало, а перезапуск посреди генерации потерял бы
    ролик, за который человек уже заплатил. Поэтому задача кладётся сюда,
    выполняется в очереди, а о результате узнают по id — или получают его
    сообщением в Telegram, даже если бот тем временем перезапускался.
    """

    KIND_VIDEO = "video"
    KIND_CHOICES = [(KIND_VIDEO, "Видео")]

    STATUS_QUEUED = "queued"
    STATUS_RUNNING = "running"
    STATUS_DONE = "done"
    STATUS_FAILED = "failed"
    STATUS_CANCELED = "canceled"
    STATUS_CHOICES = [
        (STATUS_QUEUED, "В очереди"),
        (STATUS_RUNNING, "Выполняется"),
        (STATUS_DONE, "Готово"),
        (STATUS_FAILED, "Не удалось"),
        (STATUS_CANCELED, "Отменено"),
    ]
    ACTIVE_STATES = (STATUS_QUEUED, STATUS_RUNNING)

    uid = models.CharField(max_length=32, unique=True, db_index=True, editable=False,
                           default=_gen_job_uid)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="generation_jobs")
    session = models.ForeignKey(AiChatSession, on_delete=models.SET_NULL, null=True, blank=True,
                                related_name="generation_jobs")
    kind = models.CharField(max_length=12, choices=KIND_CHOICES, default=KIND_VIDEO)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_QUEUED,
                              db_index=True)
    # Всё, что пришло от клиента: модель, промпт, длительность, кадры.
    params = models.JSONField(default=dict, blank=True)
    progress = models.CharField(max_length=32, blank=True, default="")
    progress_at = models.DateTimeField(null=True, blank=True)
    result_message = models.ForeignKey(AiChatMessage, on_delete=models.SET_NULL, null=True,
                                       blank=True, related_name="+")
    # Снимок итога для клиента: вложения, списание, баланс — как в кадре done.
    result = models.JSONField(default=dict, blank=True)
    tokens_charged = models.IntegerField(default=0)
    need_credits = models.IntegerField(default=0)
    error = models.TextField(blank=True, default="")
    error_code = models.CharField(max_length=40, blank=True, default="")
    # Куда сообщить о готовности: "" — никуда (клиент опрашивает сам),
    # "telegram" — сообщением в бот.
    notify = models.CharField(max_length=16, blank=True, default="")
    notified_at = models.DateTimeField(null=True, blank=True)
    celery_task_id = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "Задача генерации"
        verbose_name_plural = "Задачи генерации"

    def __str__(self):
        return f"{self.kind} #{self.pk} {self.status}"

    @property
    def is_active(self) -> bool:
        return self.status in self.ACTIVE_STATES

    def public(self) -> dict:
        """Ответ API: без внутренних полей."""
        session = self.session
        return {
            "job_id": self.uid,
            "kind": self.kind,
            "status": self.status,
            "progress": self.progress,
            "need_credits": self.need_credits,
            "tokens_charged": self.tokens_charged,
            "error": self.error if self.status == self.STATUS_FAILED else "",
            "error_code": self.error_code,
            "result": self.result or None,
            "notified": self.notified_at is not None,
            "session": ({"id": session.id, "uid": session.uid, "title": session.title}
                        if session else None),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }


class GenerationLog(models.Model):
    """Журнал платных генераций: кто, когда, чем, за сколько и чем кончилось.

    Зачем (просьба клиента, 21.09.2026). В кабинете OpenRouter появилась
    оплаченная генерация видео на $1.17, а в EsAI её никто не нашёл: человек
    получил «не удалось запустить», кредиты не списались, ролик пропал. По
    логам контейнера такое ищется часами, поэтому каждая генерация теперь
    оставляет строку: пользователь → время → модель → запрос → ID провайдера →
    стоимость → списанные кредиты → статус → результат или ошибка, и отдельно —
    ход по шагам (stages).

    По этому же журналу фоновая задача находит оплаченные, но не доставленные
    ролики и довозит их человеку.
    """

    KIND_VIDEO = "video"
    KIND_IMAGE = "image"
    KIND_KEYFRAME = "keyframe"
    KIND_VOICE = "voice"
    KIND_MUSIC = "music"
    KIND_SFX = "sfx"
    KIND_CHOICES = [
        (KIND_VIDEO, "Видео"),
        (KIND_IMAGE, "Изображение"),
        (KIND_KEYFRAME, "Кадр студии"),
        (KIND_VOICE, "Озвучка"),
        (KIND_MUSIC, "Музыка"),
        (KIND_SFX, "Звуковой эффект"),
    ]

    SOURCE_CHAT = "chat"
    SOURCE_STUDIO = "studio"
    SOURCE_BOT = "bot"
    SOURCE_CHOICES = [(SOURCE_CHAT, "Чат"), (SOURCE_STUDIO, "Студия"), (SOURCE_BOT, "Бот")]

    # Путь запроса. submitting — отправляем провайдеру; submitted — провайдер
    # принял и выдал ID (с этого момента он берёт деньги); delivered — человек
    # получил результат и заплатил; lost — деньги у провайдера ушли, а результата
    # у человека нет; recovered — потерянное довезли фоном.
    STATUS_SUBMITTING = "submitting"
    STATUS_SUBMITTED = "submitted"
    STATUS_DELIVERED = "delivered"
    STATUS_FAILED = "failed"
    STATUS_LOST = "lost"
    STATUS_RECOVERED = "recovered"
    STATUS_CHOICES = [
        (STATUS_SUBMITTING, "Отправляется"),
        (STATUS_SUBMITTED, "Принято провайдером"),
        (STATUS_DELIVERED, "Выдано"),
        (STATUS_FAILED, "Не удалось"),
        (STATUS_LOST, "Оплачено, но не выдано"),
        (STATUS_RECOVERED, "Довезено фоном"),
    ]
    OPEN_STATES = (STATUS_SUBMITTING, STATUS_SUBMITTED)

    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                             related_name="generation_logs", verbose_name="Пользователь")
    kind = models.CharField(max_length=12, choices=KIND_CHOICES, db_index=True, verbose_name="Что")
    source = models.CharField(max_length=8, choices=SOURCE_CHOICES, default=SOURCE_CHAT,
                              verbose_name="Откуда")
    provider = models.CharField(max_length=24, default="openrouter", verbose_name="Провайдер")
    model = models.CharField(max_length=120, blank=True, default="", verbose_name="Модель")
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_SUBMITTING,
                              db_index=True, verbose_name="Состояние")
    provider_id = models.CharField(max_length=160, blank=True, default="", db_index=True,
                                   verbose_name="ID у провайдера")
    polling_url = models.CharField(max_length=512, blank=True, default="",
                                   verbose_name="Адрес опроса")
    prompt = models.TextField(blank=True, default="", verbose_name="Запрос")
    params = models.JSONField(default=dict, blank=True, verbose_name="Параметры")
    credits_charged = models.PositiveIntegerField(default=0, verbose_name="Списано кредитов")
    credits_planned = models.PositiveIntegerField(default=0, verbose_name="Цена в кредитах")
    provider_cost_usd = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True,
                                            verbose_name="Стоимость у провайдера, $")
    result_url = models.CharField(max_length=512, blank=True, default="", verbose_name="Результат")
    error = models.TextField(blank=True, default="", verbose_name="Ошибка")
    # Ход по шагам: [{"at": iso, "stage": "submitted", "note": "..."}]
    stages = models.JSONField(default=list, blank=True, verbose_name="Ход")
    session = models.ForeignKey(AiChatSession, on_delete=models.SET_NULL, null=True, blank=True,
                                related_name="+", verbose_name="Чат")
    message = models.ForeignKey(AiChatMessage, on_delete=models.SET_NULL, null=True, blank=True,
                                related_name="+", verbose_name="Сообщение с результатом")
    scene_id = models.PositiveIntegerField(null=True, blank=True, verbose_name="Сцена студии")
    ip = models.GenericIPAddressField(null=True, blank=True, verbose_name="IP")
    needs_review = models.BooleanField(default=False, db_index=True, verbose_name="Нужен разбор")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-id",)
        verbose_name = "Генерация"
        verbose_name_plural = "Журнал генераций"
        indexes = [models.Index(fields=["status", "kind", "updated_at"], name="genlog_status_kind_upd")]

    def __str__(self):
        return f"{self.get_kind_display()} · {self.model} · {self.get_status_display()}"


class OpenRouterAccount(models.Model):
    """Аккаунт OpenRouter, с которого работает весь сайт.

    Зачем модуль. Ключ был один и лежал в настройках строкой. Когда на нём
    заканчиваются деньги, встаёт всё: чат, картинки, видео и студия. Пополнение
    идёт вручную и не всегда вовремя, поэтому клиенту нужен запасной аккаунт и
    возможность переключиться на него за один клик, не трогая сервер.

    Активный аккаунт ровно один — его и отдаёт ai.handlers._openrouter_config
    всему коду. Если активного нет, всё работает как раньше: ключ берётся из
    настроек, а затем из окружения. Так переход на модуль ничего не ломает.

    Баланс хранится снимком, а не спрашивается у OpenRouter на каждый показ
    страницы: список аккаунтов открывают часто, а лишний поход по сети на
    каждый рендер — это секунда ожидания и лишняя нагрузка на их API.
    """
    title = models.CharField(
        max_length=80, verbose_name="Название",
        help_text="Как отличать аккаунты между собой: «Основной», «Резервный».")
    api_key = models.CharField(max_length=200, verbose_name="Ключ API")
    is_active = models.BooleanField(
        default=False, verbose_name="Активный",
        help_text="С этого аккаунта идут все запросы. Активным может быть только один.")
    auto_switch = models.BooleanField(
        default=False, verbose_name="Запасной",
        help_text="Разрешить включить этот аккаунт автоматически, когда на рабочем "
                  "закончатся деньги. Выбор рабочего вручную это не отменяет.")
    auto_switched_at = models.DateTimeField(
        null=True, blank=True, verbose_name="Включён автоматически",
        help_text="Когда система сама переключилась на этот аккаунт.")
    note = models.TextField(blank=True, default="", verbose_name="Заметка")

    balance_usd = models.FloatField(null=True, blank=True, verbose_name="Осталось, $")
    spent_usd = models.FloatField(null=True, blank=True, verbose_name="Потрачено, $")
    limit_usd = models.FloatField(null=True, blank=True, verbose_name="Пополнено, $")
    checked_at = models.DateTimeField(null=True, blank=True, verbose_name="Баланс проверен")
    last_error = models.TextField(blank=True, default="", verbose_name="Последняя ошибка")

    created_at = models.DateTimeField(auto_now_add=True)

    def masked_key(self) -> str:
        """Ключ для показа в панели. Целиком наружу не отдаём никогда."""
        key = self.api_key or ""
        return f"{key[:12]}…{key[-4:]}" if len(key) > 20 else "…"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Активный ровно один: иначе непонятно, с какого аккаунта уходят деньги.
        if self.is_active:
            OpenRouterAccount.objects.exclude(pk=self.pk).filter(
                is_active=True).update(is_active=False)

    def __str__(self):
        return f"{self.title}{' (активный)' if self.is_active else ''}"

    class Meta:
        ordering = ("-is_active", "title")
        verbose_name = "Аккаунт OpenRouter"
        verbose_name_plural = "Аккаунты OpenRouter"
