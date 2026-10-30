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
        """Во сколько обойдётся сцена: кадр + видео, либо ручная цена.

        Видео считается по длительности, которую МОДЕЛЬ действительно снимет:
        у Veo это 4/6/8 секунд, и пятисекундный пресет снялся бы на четыре, а
        списалось бы за пять.
        """
        # Ручная цена учитывается там же, где и списание (pricing.scene_credits):
        # раньше она меняла только витрину, а списывалось по моделям.
        from .pricing import scene_credits

        return scene_credits(self)

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
    # Настройки съёмки из дока (модель, качество, длительность новых сцен).
    # Пусто — как в пресете сцены: так снимают старые мультфильмы и бот, и
    # ничего не меняется, пока человек сам не выберет (cartoon/pricing.py).
    video_model = models.ForeignKey(
        GPTModels, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
        verbose_name="Модель видео",
        help_text="Пусто — модель пресета каждой сцены.")
    resolution = models.CharField(
        max_length=8, null=True, blank=True, verbose_name="Качество",
        help_text="Пусто — качество пресета сцены.")
    duration = models.PositiveSmallIntegerField(
        null=True, blank=True, verbose_name="Длительность новых сцен, с",
        help_text="Пусто — длительность пресета сцены.")
    # Лента, собранная гостем до входа, приезжает сюда одним запросом. Ключ
    # черновика не даёт завести второй такой же проект, если страница после
    # входа перезагрузилась, пока шёл перенос.
    import_key = models.CharField(max_length=64, blank=True, default="", db_index=True,
                                  verbose_name="Ключ гостевого черновика")
    # Отмечен в админке как удачная работа — для рекламы и витрины.
    featured_at = models.DateTimeField(null=True, blank=True, db_index=True,
                                       verbose_name="Отмечен для рекламы")

    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_DRAFT,
                              verbose_name="Состояние")
    result_video = models.CharField(
        max_length=512, blank=True, default="", verbose_name="Готовый ролик",
        help_text="Путь в хранилище после склейки.")
    error = models.TextField(blank=True, default="", verbose_name="Последняя ошибка")
    # Когда задача склейки реально взялась за работу. Пусто при «Собирается» —
    # склейка ещё стоит в очереди media за съёмками: уборка не должна считать
    # это ожидание оборвавшейся склейкой.
    assembly_started_at = models.DateTimeField(null=True, blank=True,
                                               verbose_name="Склейка началась")
    # Голос каждого героя на весь мультфильм: {"<id героя>": {"voice_id", "voice_name"}}.
    # Видеомодель не помнит голос между съёмками, поэтому один и тот же герой
    # говорил бы по-разному — голос закрепляется здесь (cartoon.voiceover.hero_voice).
    hero_voices = models.JSONField(default=dict, blank=True, verbose_name="Голоса героев")

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
    # Своя сцена (клиент: «вместо готового пресета просто написать, что герой
    # делает»). Текст человека хранится как есть; промпт кадра и движения
    # формируется из него один раз при первой генерации и дальше не меняется —
    # пересъёмка не должна давать другую сцену. Пресет у такой сцены служебный
    # (services.CUSTOM_PRESET_SLUG): от него берутся модели, стиль и цена.
    custom_text = models.TextField(blank=True, default="", verbose_name="Своя сцена: описание")
    custom_title = models.CharField(max_length=80, blank=True, default="",
                                    verbose_name="Своя сцена: название")
    custom_prompt = models.TextField(blank=True, default="", verbose_name="Своя сцена: промпт кадра")
    custom_motion = models.TextField(blank=True, default="", verbose_name="Своя сцена: промпт движения")
    # Отмечена в админке как удачная работа — для рекламы и витрины.
    featured_at = models.DateTimeField(null=True, blank=True, db_index=True,
                                       verbose_name="Отмечена для рекламы")
    # Что герой говорит в этой сцене — словами человека, на его языке.
    # Уходит и в промпт съёмки (модель играет реплику), и в озвучку.
    dialogue = models.CharField(max_length=300, blank=True, default="",
                                verbose_name="Реплика героя")
    # Решение режиссёра: в поле реплики слова героя или описание событий («он
    # играет, потом ищет маму»). Описание вслух не читаем и за голос не берём.
    # Кэшируется вместе с video_prompt и сбрасывается вместе с ним при смене реплики.
    dialogue_is_speech = models.BooleanField(default=True, verbose_name="Реплика — прямая речь")
    # Каким голосом режиссёр слышит героя ({"gender", "age"}): нужен, пока голос за
    # героем ещё не закреплён. Живёт в сцене, потому что промпт кэшируется.
    voice_hint = models.JSONField(default=dict, blank=True, verbose_name="Голос по мнению режиссёра")
    # Окно, где в ролике говорит сама модель, секунды. Считается бесплатно (ffmpeg).
    # Пусто — не считалось или модель промолчала.
    speech_start = models.FloatField(null=True, blank=True, verbose_name="Речь модели: начало, с")
    speech_end = models.FloatField(null=True, blank=True, verbose_name="Речь модели: конец, с")
    # Готовый промпт съёмки, разложенный режиссёром по секундам. Кэш: при
    # пересъёмке его не собирают заново.
    video_prompt = models.TextField(blank=True, default="", verbose_name="Промпт съёмки")
    video_negative = models.TextField(blank=True, default="", verbose_name="Чего в кадре быть не должно")
    # Последний кадр снятого ролика: с него начинается следующая сцена, чтобы
    # герой, одежда и комната не «прыгали» между сценами.
    last_frame = models.CharField(max_length=512, blank=True, default="",
                                  verbose_name="Последний кадр ролика")
    # Звук: видео сцены, сведённое со всеми её дорожками (голоса, музыка,
    # эффекты). Пусто — дорожек нет, играет исходное видео.
    mixed_video = models.CharField(max_length=512, blank=True, default="",
                                   verbose_name="Видео со звуком")
    sound_volume = models.FloatField(default=1.0, verbose_name="Громкость звука самой сцены")

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
    # Своя длительность этой сцены. Пусто — длительность мультфильма или пресета.
    duration = models.PositiveSmallIntegerField(
        null=True, blank=True, verbose_name="Длительность сцены, с",
        help_text="Пусто — как у мультфильма (или пресета).")
    # Снимок настроек в момент «Снять» (pricing.snapshot_fields): съёмка, резерв и
    # списание идут по нему, поэтому смена дока после запуска не меняет ни модель,
    # ни цену уже поставленной сцены. Пересъёмка снимает новый снимок. Пусто —
    # сцена снималась до снимков: всё считается по пресету, как раньше.
    shot_model = models.ForeignKey(
        GPTModels, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
        verbose_name="Снята моделью")
    shot_resolution = models.CharField(max_length=8, null=True, blank=True,
                                       verbose_name="Снята в качестве")
    shot_duration = models.PositiveSmallIntegerField(null=True, blank=True,
                                                     verbose_name="Снята длительностью, с")
    shot_aspect = models.CharField(max_length=8, null=True, blank=True, verbose_name="Снята в формате")
    credits_planned = models.PositiveIntegerField(
        null=True, blank=True, verbose_name="Цена при запуске",
        help_text="Сколько показали на кнопке «Снять»: кадр + видео (или только видео с готовым кадром).")
    shot_video_credits = models.PositiveIntegerField(
        null=True, blank=True, verbose_name="Видео по цене запуска",
        help_text="Видео-часть цены при запуске — её и списывает готовый ролик.")
    # Отдельно от видео, потому что голос может и не случиться (описание, сбой),
    # а часть кадра задача считает как «цена запуска минус видео минус голос».
    shot_voice_credits = models.PositiveIntegerField(
        null=True, blank=True, verbose_name="Голос по цене запуска",
        help_text="Часть цены при запуске за автоозвучку реплики. Спишется, только если голос готов.")

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
    # Формат — часть ключа: вертикальному мультфильму горизонтальный кадр не
    # подходит, а раньше он достался бы ему из общего запаса.
    aspect_ratio = models.CharField(max_length=8, default="16:9", verbose_name="Формат")
    image = models.CharField(max_length=512, verbose_name="Кадр")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("preset", "character", "aspect_ratio")
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
    # Формат — часть ключа, как у кадров: вертикальный ролик в горизонтальном
    # мультфильме показывал бы не то, что человек получит.
    aspect_ratio = models.CharField(max_length=8, default="16:9", verbose_name="Формат")
    video = models.CharField(max_length=512, verbose_name="Ролик")
    clip = models.CharField(
        max_length=512, blank=True, default="", verbose_name="Лёгкая копия",
        help_text="480p без звука — для автозапуска в витрине и ленте на телефоне.")
    source_scene = models.ForeignKey(
        "CartoonScene", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+", verbose_name="Из какой съёмки")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("preset", "character", "aspect_ratio")
        verbose_name = "Ролик героя в сцене"
        verbose_name_plural = "Ролики героев в сценах"

    def __str__(self):
        return f"{self.character_id} в {self.preset_id} (ролик)"


class CartoonAudioTrack(models.Model):
    """Звуковая дорожка сцены: реплика, свой голос, музыка или эффект.

    У каждой — момент начала и громкость (просьба клиента). Файл всегда mp3:
    загрузки и запись с диктофона приводятся к нему при сохранении.
    """
    KIND_VOICE = "voice"
    KIND_OWN = "own"
    KIND_MUSIC = "music"
    KIND_SFX = "sfx"
    # Реплика героя вместо речи модели: сведение глушит речь в её окне и ставит
    # эту дорожку (cartoon/audio.py). Одна на сцену — см. Meta.
    KIND_LINE = "line"
    KIND_CHOICES = [
        (KIND_VOICE, "ИИ-голос"),
        (KIND_OWN, "Свой голос"),
        (KIND_MUSIC, "Музыка"),
        (KIND_SFX, "Звуковой эффект"),
        (KIND_LINE, "Реплика героя"),
    ]

    scene = models.ForeignKey("CartoonScene", on_delete=models.CASCADE, related_name="audio_tracks",
                              verbose_name="Сцена")
    kind = models.CharField(max_length=8, choices=KIND_CHOICES, verbose_name="Тип")
    character = models.ForeignKey(CartoonCharacter, on_delete=models.SET_NULL, null=True, blank=True,
                                  related_name="audio_tracks", verbose_name="Чья реплика")
    voice_id = models.CharField(max_length=64, blank=True, default="", verbose_name="Голос (id)")
    voice_name = models.CharField(max_length=120, blank=True, default="", verbose_name="Голос")
    text = models.TextField(blank=True, default="", verbose_name="Текст или описание")
    # Музыка и эффекты делаются в фоне (до пары минут): дорожка появляется
    # сразу в состоянии «готовится», файл приходит позже.
    STATUS_PENDING = "pending"
    STATUS_READY = "ready"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [(STATUS_PENDING, "Готовится"), (STATUS_READY, "Готова"),
                      (STATUS_FAILED, "Не получилась")]
    status = models.CharField(max_length=8, choices=STATUS_CHOICES, default=STATUS_READY,
                              verbose_name="Состояние")
    error = models.CharField(max_length=300, blank=True, default="", verbose_name="Ошибка")
    credits_planned = models.PositiveIntegerField(default=0, verbose_name="Цена в кредитах")
    seconds_asked = models.FloatField(default=0, verbose_name="Запрошенная длительность, с")
    file = models.CharField(max_length=512, blank=True, default="", verbose_name="Файл")
    duration = models.FloatField(default=0, verbose_name="Длительность, с")
    start_sec = models.FloatField(default=0, verbose_name="Начало, с")
    volume = models.FloatField(default=1.0, verbose_name="Громкость")
    credits_spent = models.PositiveIntegerField(default=0, verbose_name="Списано кредитов")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("start_sec", "id")
        verbose_name = "Звуковая дорожка"
        verbose_name_plural = "Звуковые дорожки"
        constraints = [
            # Две реплики на сцену — это два голоса разом и двойная оплата.
            models.UniqueConstraint(fields=["scene"], condition=models.Q(kind="line"),
                                    name="cartoon_one_line_per_scene"),
        ]

    def __str__(self):
        return f"{self.get_kind_display()} · сцена {self.scene_id}"


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
