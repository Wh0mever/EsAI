"""Студия мультфильмов: персонаж → сцены по пресетам → таймлайн → склейка.

Замысел клиента: человек НЕ пишет промпты и не разбирается в видео-моделях.
Он выбирает или создаёт персонажа, набирает готовые сцены из библиотеки и
получает цельный ролик.

Как достигается главное требование — один и тот же персонаж во всех сценах.
Проверено вживую 25.08.2026: если сгенерировать персонажа один раз и дальше
на каждую сцену делать КАДР-РАСКАДРОВКУ моделью с поддержкой референса
(Nano Banana), персонаж переносится в новую сцену практически без изменений —
та же морда, тот же плащ с эмблемой, те же очки. Этот кадр уходит в
видео-модель как first_frame, поэтому и ролик стартует с правильного
персонажа. Без промежуточного кадра видео-модель рисовала бы героя заново в
каждой сцене, и «единого мультфильма» не получилось бы.

Тот же замер показал, что FLUX Flex с референсом для этого не годится:
запрос не уложился в четыре минуты, а Nano Banana справляется за 8–18 секунд.

Всё, что влияет на результат и цену, вынесено в пресет и правится в админке —
добавлять сцены можно без единой строчки кода (требование клиента).
"""
from django.conf import settings
from django.db import models

from ai.models import GPTModels


class CartoonCategory(models.Model):
    """Раздел библиотеки: и для сцен, и для героев.

    Отдельной моделью, а не списком в коде: клиент просил, чтобы библиотека
    росла работами пользователей, а модератор при публикации выбирал раздел.
    Значит, разделы должны заводиться в админке, без выкладки кода.
    """
    title = models.CharField(max_length=80, verbose_name="Название")
    # Библиотека — такой же контент, как статьи блога, и переводится так же:
    # отдельным полем на язык. Пусто — покажется русское название.
    title_en = models.CharField(max_length=80, blank=True, default="", verbose_name="Название (EN)")
    title_kg = models.CharField(max_length=80, blank=True, default="", verbose_name="Название (KG)")
    slug = models.SlugField(max_length=90, unique=True, verbose_name="Код")
    emoji = models.CharField(
        max_length=8, blank=True, default="", verbose_name="Значок",
        help_text="Один символ для плитки раздела, необязательно.")
    sort_order = models.PositiveIntegerField(default=100, verbose_name="Порядок")
    is_active = models.BooleanField(default=True, verbose_name="Показывать")

    def __str__(self):
        return self.title

    class Meta:
        ordering = ("sort_order", "id")
        verbose_name = "Раздел библиотеки"
        verbose_name_plural = "Разделы библиотеки"


class CartoonPreset(models.Model):
    """Готовая сцена: скрытый промпт, модели, настройки и видео-превью.

    Пользователь видит только название и превью. Промпт, выбор моделей и
    длительность он не трогает — в этом вся идея студии.
    """
    title = models.CharField(max_length=120, verbose_name="Название")
    title_en = models.CharField(max_length=120, blank=True, default="", verbose_name="Название (EN)")
    title_kg = models.CharField(max_length=120, blank=True, default="", verbose_name="Название (KG)")
    subtitle = models.CharField(
        max_length=160, blank=True, default="", verbose_name="Подпись",
        help_text="Короткое пояснение под названием, напр. «Герой появляется на крыше»")
    subtitle_en = models.CharField(max_length=160, blank=True, default="", verbose_name="Подпись (EN)")
    subtitle_kg = models.CharField(max_length=160, blank=True, default="", verbose_name="Подпись (KG)")
    slug = models.SlugField(max_length=140, unique=True, verbose_name="Код")

    preview_video = models.FileField(
        upload_to="cartoon/previews/", blank=True, null=True,
        verbose_name="Видео-превью",
        help_text="Готовый ролик этой сцены. Именно его видит пользователь до генерации.")
    preview_poster = models.ImageField(
        upload_to="cartoon/posters/", blank=True, null=True,
        verbose_name="Обложка превью",
        help_text="Кадр для списка. Пусто — возьмётся первый кадр превью.")
    # Витрина показывает полторы сотни сцен разом, а кадр от модели весит
    # больше мегабайта — в сетке отдаём лёгкую копию (см. cartoon/thumbs.py).
    preview_thumb = models.ImageField(
        upload_to="cartoon/posters/thumbs/", blank=True, null=True,
        verbose_name="Обложка для списка (лёгкая)")
    # В ленте превью играют сами, без звука. Снятый ролик для этого слишком
    # тяжёл — шесть штук на экране съели бы двадцать мегабайт трафика,
    # поэтому там крутится облегчённая копия (см. cartoon/clips.py).
    preview_clip = models.FileField(
        upload_to="cartoon/previews/clips/", blank=True, null=True,
        verbose_name="Ролик для ленты (лёгкий)")

    # --- то, что уходит моделям ---
    scene_prompt = models.TextField(
        verbose_name="Промпт сцены (скрытый)",
        help_text=(
            "Что происходит в сцене. Пишите по-английски и от третьего лица: "
            "«The character flies above the city at sunset». Слово «character» "
            "будет заменено на описание персонажа."
        ))
    motion_prompt = models.TextField(
        blank=True, default="", verbose_name="Промпт движения",
        help_text=(
            "Чем движение отличается от статичного кадра: «camera slowly pushes in, "
            "cape flutters». Пусто — возьмётся промпт сцены."
        ))
    style_prompt = models.TextField(
        blank=True, default="", verbose_name="Стиль",
        help_text="Общий стиль кадра. Одинаковый у всех пресетов набора — так сцены выглядят одним мультфильмом.")

    image_model = models.ForeignKey(
        GPTModels, on_delete=models.PROTECT, related_name="cartoon_preset_image",
        verbose_name="Модель кадра",
        help_text="Делает кадр-раскадровку с персонажем. Нужна поддержка референса (Nano Banana).")
    video_model = models.ForeignKey(
        GPTModels, on_delete=models.PROTECT, related_name="cartoon_preset_video",
        verbose_name="Модель видео",
        help_text="Оживляет кадр. От неё зависит и цена сцены.")

    duration = models.PositiveSmallIntegerField(
        default=5, verbose_name="Длительность, с",
        help_text="Значение сверяется с тем, что умеет модель.")
    aspect_ratio = models.CharField(
        max_length=8, default="16:9", verbose_name="Пропорции кадра")
    resolution = models.CharField(
        max_length=8, blank=True, default="", verbose_name="Качество",
        help_text="Пусто — возьмётся значение по умолчанию модели.")

    credits_override = models.PositiveIntegerField(
        null=True, blank=True, verbose_name="Цена вручную",
        help_text="Пусто — цена считается по моделям и длительности. Заполните, чтобы назначить свою.")

    category = models.ForeignKey(
        CartoonCategory, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="presets", verbose_name="Раздел")
    # Аудитория живёт на сцене, а не на разделе: в «Приключениях» соседствуют
    # детские джунгли и взрослый поиск сокровищ, и стиль съёмки у них разный.
    audience = models.CharField(
        max_length=8, choices=[("kids", "Для детей"), ("adults", "Для взрослых")],
        default="adults", verbose_name="Для кого")
    is_pick = models.BooleanField(
        default=False, verbose_name="⭐ Выбор EsAI",
        help_text="Показывать в подборке наверху библиотеки.")
    sort_order = models.PositiveIntegerField(default=100, verbose_name="Порядок")
    is_active = models.BooleanField(default=True, verbose_name="Показывать")
    created_at = models.DateTimeField(auto_now_add=True)

    def estimated_credits(self) -> int:
        """Во сколько обойдётся сцена: кадр + видео, либо ручная цена."""
        if self.credits_override:
            return int(self.credits_override)
        frame = max(1, int(float(self.image_model.markup_coefficient or 1)))
        video = max(1, round(int(self.duration) * float(self.video_model.markup_coefficient or 1)))
        return frame + video

    def __str__(self):
        return self.title

    class Meta:
        ordering = ("sort_order", "id")
        verbose_name = "Пресет сцены"
        verbose_name_plural = "Пресеты сцен"


class CartoonCharacter(models.Model):
    """Персонаж: из библиотеки, загруженный пользователем или сгенерированный.

    Библиотечные (user=None, is_public=True) заводит клиент в админке.
    Пользовательские принадлежат своему владельцу и в чужой библиотеке не видны.
    """
    SOURCE_LIBRARY = "library"
    SOURCE_UPLOAD = "upload"
    SOURCE_GENERATED = "generated"
    SOURCE_CHOICES = [
        (SOURCE_LIBRARY, "Из библиотеки"),
        (SOURCE_UPLOAD, "Загружен пользователем"),
        (SOURCE_GENERATED, "Сгенерирован в EsAI"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True,
        related_name="cartoon_characters", verbose_name="Владелец",
        help_text="Пусто — персонаж из общей библиотеки.")
    name = models.CharField(max_length=120, verbose_name="Имя")
    name_en = models.CharField(max_length=120, blank=True, default="", verbose_name="Имя (EN)")
    name_kg = models.CharField(max_length=120, blank=True, default="", verbose_name="Имя (KG)")
    image = models.ImageField(upload_to="cartoon/characters/", verbose_name="Изображение")
    image_thumb = models.ImageField(
        upload_to="cartoon/characters/thumbs/", blank=True, null=True,
        verbose_name="Изображение для списка (лёгкое)")
    description = models.TextField(
        blank=True, default="", verbose_name="Описание для моделей",
        help_text=(
            "По-английски, короткой фразой: «a ginger cat superhero in a blue cape». "
            "Подставляется в промпт вместо слова «character»."
        ))
    category = models.ForeignKey(
        CartoonCategory, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="characters", verbose_name="Раздел")
    audience = models.CharField(
        max_length=8, choices=[("kids", "Для детей"), ("adults", "Для взрослых")],
        default="adults", verbose_name="Для кого")
    source = models.CharField(max_length=12, choices=SOURCE_CHOICES, default=SOURCE_LIBRARY,
                              verbose_name="Откуда")
    is_public = models.BooleanField(default=False, verbose_name="В общей библиотеке")
    sort_order = models.PositiveIntegerField(default=100, verbose_name="Порядок")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    class Meta:
        ordering = ("sort_order", "-created_at")
        verbose_name = "Персонаж"
        verbose_name_plural = "Персонажи"


class CartoonProject(models.Model):
    """Мультфильм пользователя: персонаж и набор сцен."""
    STATUS_DRAFT = "draft"
    STATUS_ASSEMBLING = "assembling"
    STATUS_READY = "ready"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Черновик"),
        (STATUS_ASSEMBLING, "Собирается"),
        (STATUS_READY, "Готов"),
        (STATUS_FAILED, "Ошибка сборки"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="cartoon_projects", verbose_name="Пользователь")
    title = models.CharField(max_length=140, blank=True, default="Мой мультфильм",
                             verbose_name="Название")
    character = models.ForeignKey(
        CartoonCharacter, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="projects", verbose_name="Персонаж")
    aspect_ratio = models.CharField(max_length=8, default="16:9", verbose_name="Пропорции")
    # Лента, собранная гостем до входа, приезжает сюда одним запросом. Ключ
    # черновика не даёт завести второй такой же проект, если страница после
    # входа перезагрузилась, пока шёл перенос.
    import_key = models.CharField(max_length=64, blank=True, default="", db_index=True,
                                  verbose_name="Ключ гостевого черновика")

    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_DRAFT,
                              verbose_name="Состояние")
    result_video = models.CharField(
        max_length=512, blank=True, default="", verbose_name="Готовый ролик",
        help_text="Путь в хранилище после склейки.")
    error = models.TextField(blank=True, default="", verbose_name="Последняя ошибка")

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.title} (#{self.pk})"

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "Мультфильм"
        verbose_name_plural = "Мультфильмы"


class CartoonScene(models.Model):
    """Одна сцена в таймлайне: кадр-раскадровка и оживлённый ролик.

    keyframe хранится отдельно от video намеренно. Во-первых, его видно сразу,
    пока видео ещё считается, и человек понимает, что получит. Во-вторых, если
    ролик не удался, пересоздать его можно с ТЕМ ЖЕ кадром — персонаж и
    композиция не поедут.
    """
    STATUS_DRAFT = "draft"
    STATUS_NEW = "new"
    STATUS_KEYFRAME = "keyframe"
    STATUS_VIDEO = "video"
    STATUS_READY = "ready"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "В ленте, не снята"),
        (STATUS_NEW, "Ожидает"),
        (STATUS_KEYFRAME, "Рисуется кадр"),
        (STATUS_VIDEO, "Оживляется"),
        (STATUS_READY, "Готова"),
        (STATUS_FAILED, "Ошибка"),
    ]

    project = models.ForeignKey(
        CartoonProject, on_delete=models.CASCADE, related_name="scenes",
        verbose_name="Мультфильм")
    preset = models.ForeignKey(
        CartoonPreset, on_delete=models.PROTECT, related_name="scenes",
        verbose_name="Пресет")
    # Свой герой у отдельной сцены. Пусто — берётся герой мультфильма. Нужно,
    # чтобы во второй сцене мог появиться другой персонаж: без этого история из
    # двух героев не собирается вообще.
    character = models.ForeignKey(
        "CartoonCharacter", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="scenes", verbose_name="Герой этой сцены")
    order = models.PositiveIntegerField(default=0, verbose_name="Позиция в таймлайне")

    keyframe = models.CharField(max_length=512, blank=True, default="",
                                verbose_name="Кадр-раскадровка")
    video = models.CharField(max_length=512, blank=True, default="",
                             verbose_name="Ролик сцены")
    # Черновик по умолчанию: человек сначала набирает ленту, а снимает потом и
    # по одной — так он видит, за что платит, и не теряет кредиты на сцене,
    # добавленной по ошибке.
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_DRAFT,
                              verbose_name="Состояние")
    error = models.TextField(blank=True, default="", verbose_name="Ошибка")
    credits_spent = models.PositiveIntegerField(default=0, verbose_name="Списано кредитов")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.project_id}/{self.order} — {self.preset.title if self.preset_id else '—'}"

    class Meta:
        ordering = ("order", "id")
        verbose_name = "Сцена"
        verbose_name_plural = "Сцены"


class CartoonKeyframe(models.Model):
    """Кадр «этот герой в этой сцене» — общий на всех.

    Зачем. Клиент попросил показывать сцены сразу с выбранным героем, ещё до
    генерации. Нарисовать все полторы сотни сцен под каждого пользователя
    невозможно: это шестьсот кредитов за один просмотр библиотеки.

    Но пара «сцена + герой» повторяется у разных людей: героев в библиотеке
    двадцать шесть, и кадр «кот-супергерой на крыше» одинаков для всех, кто
    его выберет. Поэтому кадр рисуется один раз и дальше отдаётся бесплатно —
    и в примерке, и при самой съёмке сцены, где он же идёт первым кадром.

    Личные персонажи сюда тоже попадают: кадр принадлежит паре, а не человеку,
    и чужому он не покажется просто потому, что чужого персонажа не выбрать.
    """
    preset = models.ForeignKey(
        CartoonPreset, on_delete=models.CASCADE, related_name="keyframes",
        verbose_name="Сцена")
    character = models.ForeignKey(
        CartoonCharacter, on_delete=models.CASCADE, related_name="keyframes",
        verbose_name="Герой")
    image = models.CharField(max_length=512, verbose_name="Кадр")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("preset", "character")
        verbose_name = "Кадр героя в сцене"
        verbose_name_plural = "Кадры героев в сценах"

    def __str__(self):
        return f"{self.character_id} в {self.preset_id}"


class CartoonPairVideo(models.Model):
    """Готовый ролик «герой в сцене» — общий для всех, как кадр примерки.

    Клиент: выбрал героя и сцену — и сразу видишь сцену с ним в движении, без
    новой генерации. Подставить героя в чужой ролик нельзя (у нас коты и
    капибары, а не лица), поэтому движущееся превью пары — это видео, снятое
    с этим героем хотя бы раз. Дальше оно показывается всем мгновенно.

    Сюда попадает каждая удачная съёмка библиотечного героя в библиотечной
    сцене: в таком ролике нет ничего личного — тот же герой, та же сцена,
    тот же первый кадр, что увидел бы любой. Свои персонажи пользователей
    сюда не попадают никогда.
    """
    preset = models.ForeignKey(
        CartoonPreset, on_delete=models.CASCADE, related_name="pair_videos", verbose_name="Сцена")
    character = models.ForeignKey(
        CartoonCharacter, on_delete=models.CASCADE, related_name="pair_videos", verbose_name="Герой")
    video = models.CharField(max_length=512, verbose_name="Ролик")
    clip = models.CharField(
        max_length=512, blank=True, default="", verbose_name="Лёгкая копия",
        help_text="480p без звука — для автозапуска в витрине и ленте на телефоне.")
    source_scene = models.ForeignKey(
        "CartoonScene", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+", verbose_name="Из какой съёмки")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("preset", "character")
        verbose_name = "Ролик героя в сцене"
        verbose_name_plural = "Ролики героев в сценах"

    def __str__(self):
        return f"{self.character_id} в {self.preset_id} (ролик)"


class CartoonGuestTryOn(models.Model):
    """Бесплатная примерка героя, которую получил гость.

    Клиент: человек должен сначала попробовать студию и увидеть результат, а
    регистрацию мы получаем после. Поэтому одну примерку гость делает без
    входа — но одну на устройство, а не на героя: кадр рисуется за наш счёт.

    Устройство узнаётся по тому же ключу, что и везде на сайте. Он живёт в
    браузере и чистится вместе с ним, поэтому рядом ещё два ограничения —
    на IP за сутки и общий дневной потолок (см. views._guest_try_on).
    """
    device_key = models.CharField(max_length=64, unique=True, verbose_name="Ключ устройства")
    ip = models.GenericIPAddressField(null=True, blank=True, db_index=True, verbose_name="IP")
    preset = models.ForeignKey(
        CartoonPreset, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="guest_try_ons", verbose_name="Сцена")
    character = models.ForeignKey(
        CartoonCharacter, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="guest_try_ons", verbose_name="Герой")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "Бесплатная примерка гостя"
        verbose_name_plural = "Бесплатные примерки гостей"

    def __str__(self):
        return f"{self.device_key[:8]} · {self.created_at:%Y-%m-%d %H:%M}"
