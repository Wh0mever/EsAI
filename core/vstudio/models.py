"""Видеостудия (/video-studio): проекты, материалы, запросы и дубли.

Схема разделяет «что человек хочет» и «что мы оплатили»:
- Shot — запрос как его составил человек (промпт-документ, лоток, параметры).
  После создания не меняется: «Изменить и перезапустить» — это новый Shot с
  forked_from.
- Take — одна оплачиваемая попытка = один вызов провайдера = одна строка
  журнала генераций. Резерв кредитов — это сама строка (charge_state), а все
  переходы — условные UPDATE (§2.2 спецификации), поэтому списание и снятие
  резерва происходят ровно один раз.

Публичные идентификаторы — только uid (uuid4().hex): числовые id и URL в API
не принимаются, чужой uid неотличим от несуществующего.
"""
from __future__ import annotations

import uuid

from django.conf import settings
from django.core.files.storage import default_storage
from django.db import models
from django.db.models import Q
from django.utils import timezone

USER_MODEL = settings.AUTH_USER_MODEL


def _uid() -> str:
    return uuid.uuid4().hex


def _media_url(path: str) -> str:
    return default_storage.url(path) if path else ""


# Константы дубля нужны и в Meta (CheckConstraint), а вложенный класс не видит
# атрибуты внешнего — поэтому они на уровне модуля и повторены в Take.
TAKE_QUEUED = "queued"
TAKE_SUBMITTING = "submitting"
TAKE_RUNNING = "running"
TAKE_SAVING = "saving"
TAKE_DONE = "done"
TAKE_FAILED = "failed"
TAKE_CANCELED = "canceled"
TAKE_LOST = "lost"
TAKE_OPEN = (TAKE_QUEUED, TAKE_SUBMITTING, TAKE_RUNNING, TAKE_SAVING)
TAKE_CLOSED = (TAKE_DONE, TAKE_FAILED, TAKE_CANCELED, TAKE_LOST)
# Исходы, при которых человек не платит: резерв снимается тем же UPDATE.
TAKE_RELEASING = (TAKE_FAILED, TAKE_CANCELED, TAKE_LOST)

CHARGE_RESERVED = "reserved"
CHARGE_CHARGED = "charged"
CHARGE_RELEASED = "released"


class Project(models.Model):
    """Строка «Истории» в левой колонке студии (Фаза 1: kind=playground)."""

    KIND_PLAYGROUND = "playground"
    KIND_PRODUCTION = "production"  # Фаза 2: пошаговый конвейер
    KIND_CHOICES = [(KIND_PLAYGROUND, "Песочница"), (KIND_PRODUCTION, "Производство")]
    # Название по умолчанию — начало первого промпта.
    AUTO_TITLE_CHARS = 60

    uid = models.CharField(max_length=32, unique=True, default=_uid, editable=False)
    user = models.ForeignKey(USER_MODEL, on_delete=models.CASCADE,
                             related_name="vstudio_projects", verbose_name="Пользователь")
    kind = models.CharField(max_length=12, choices=KIND_CHOICES, default=KIND_PLAYGROUND,
                            verbose_name="Тип")
    title = models.CharField(max_length=140, blank=True, default="", verbose_name="Название")
    # Последние параметры правой панели — чтобы проект открывался как был.
    settings = models.JSONField(default=dict, blank=True, verbose_name="Параметры панели")
    is_archived = models.BooleanField(default=False, verbose_name="В архиве")
    last_activity_at = models.DateTimeField(default=timezone.now, verbose_name="Активность")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Создан")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Изменён")

    class Meta:
        verbose_name = "Проект видеостудии"
        verbose_name_plural = "Проекты видеостудии"
        indexes = [models.Index(fields=["user", "is_archived", "-last_activity_at"],
                                name="vs_proj_user_act")]

    def __str__(self):
        return self.title or f"Проект {self.uid[:8]}"

    @classmethod
    def touch(cls, pk, at=None) -> None:
        """Поднять проект в «Истории» без save(): не затираем чужие поля."""
        cls.objects.filter(pk=pk).update(last_activity_at=at or timezone.now())


class AssetQuerySet(models.QuerySet):
    def owned_by(self, user):
        # Все выборки — только по владельцу: чужой uid выглядит как несуществующий.
        return self.filter(user=user)

    def alive(self):
        return self.filter(deleted_at__isnull=True)


class Asset(models.Model):
    """«Мои материалы»: всё, что можно упомянуть через @, и результаты дублей."""

    KIND_IMAGE = "image"
    KIND_VIDEO = "video"   # в Фазе 1 — только результаты генераций
    KIND_AUDIO = "audio"   # Фаза 1.5
    KIND_CHOICES = [(KIND_IMAGE, "Картинка"), (KIND_VIDEO, "Видео"), (KIND_AUDIO, "Звук")]

    SOURCE_UPLOAD = "upload"
    SOURCE_GENERATED_IMAGE = "generated_image"
    SOURCE_GENERATED_VIDEO = "generated_video"
    SOURCE_FRAME = "frame"                    # последний кадр готового видео
    SOURCE_IMPORT_CARTOON = "import_cartoon"  # Фаза 1.5
    SOURCE_IMPORT_CHAT = "import_chat"        # Фаза 1.5
    SOURCE_CHOICES = [
        (SOURCE_UPLOAD, "Загрузка"),
        (SOURCE_GENERATED_IMAGE, "Созданная картинка"),
        (SOURCE_GENERATED_VIDEO, "Созданное видео"),
        (SOURCE_FRAME, "Кадр из видео"),
        (SOURCE_IMPORT_CARTOON, "Из мультстудии"),
        (SOURCE_IMPORT_CHAT, "Из чата"),
    ]

    STATUS_PENDING = "pending"   # картинка ещё создаётся
    STATUS_READY = "ready"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [(STATUS_PENDING, "Создаётся"), (STATUS_READY, "Готово"),
                      (STATUS_FAILED, "Не получилось")]

    uid = models.CharField(max_length=32, unique=True, default=_uid, editable=False)
    user = models.ForeignKey(USER_MODEL, on_delete=models.CASCADE,
                             related_name="vstudio_assets", verbose_name="Пользователь")
    # Где материал появился; проект может уйти, материал остаётся в библиотеке.
    project = models.ForeignKey(Project, on_delete=models.SET_NULL, null=True, blank=True,
                                related_name="+", verbose_name="Проект")
    kind = models.CharField(max_length=8, choices=KIND_CHOICES, default=KIND_IMAGE,
                            verbose_name="Тип")
    source = models.CharField(max_length=16, choices=SOURCE_CHOICES, default=SOURCE_UPLOAD,
                              verbose_name="Откуда")
    status = models.CharField(max_length=8, choices=STATUS_CHOICES, default=STATUS_READY,
                              db_index=True, verbose_name="Состояние")
    # Пути в default_storage: vstudio/<user_id>/<uid>.jpg|png|mp4 и <uid>_t.jpg.
    file = models.CharField(max_length=512, blank=True, default="", verbose_name="Файл")
    thumb = models.CharField(max_length=512, blank=True, default="", verbose_name="Превью")
    mime = models.CharField(max_length=64, blank=True, default="", verbose_name="MIME")
    bytes = models.PositiveBigIntegerField(default=0, verbose_name="Размер, байт")
    width = models.PositiveIntegerField(null=True, blank=True, verbose_name="Ширина")
    height = models.PositiveIntegerField(null=True, blank=True, verbose_name="Высота")
    duration_s = models.FloatField(null=True, blank=True, verbose_name="Длительность, с")
    # Дедупликация загрузок одного человека: то же фото второй раз — тот же ассет.
    sha256 = models.CharField(max_length=64, blank=True, default="", verbose_name="SHA-256")
    # Алиас «@Анна»: интерфейс — Фаза 1.5, поле сразу, чтобы не мигрировать.
    label = models.CharField(max_length=40, blank=True, default="", verbose_name="Алиас")
    # {too_small, aspect, heic, exif_rotated, downscaled_from:[w,h], animated}
    flags = models.JSONField(default=dict, blank=True, verbose_name="Отметки")
    # original_name, prompt (у созданных картинок)
    meta = models.JSONField(default=dict, blank=True, verbose_name="Сведения")
    origin_take = models.ForeignKey("Take", on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name="+", verbose_name="Из дубля")
    error_code = models.CharField(max_length=40, blank=True, default="", verbose_name="Код ошибки")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Создан")
    # Удаление только мягкое: файл и строку стирает purge_assets через 30 дней,
    # если на материал не ссылаются запросы и дубли.
    deleted_at = models.DateTimeField(null=True, blank=True, verbose_name="Удалён")

    objects = AssetQuerySet.as_manager()

    class Meta:
        verbose_name = "Материал видеостудии"
        verbose_name_plural = "Материалы видеостудии"
        indexes = [
            models.Index(fields=["user", "deleted_at", "-created_at"], name="vs_asset_lib"),
            models.Index(fields=["user", "sha256"], name="vs_asset_dedup"),
        ]

    def __str__(self):
        return f"{self.get_kind_display()} {self.uid[:8]}"

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    @property
    def url(self) -> str:
        return _media_url(self.file)

    @property
    def thumb_url(self) -> str:
        return _media_url(self.thumb)


class Shot(models.Model):
    """ЧТО человек хочет. После создания не меняется."""

    KIND_VIDEO = "video"
    KIND_IMAGE = "image"
    KIND_CHOICES = [(KIND_VIDEO, "Видео"), (KIND_IMAGE, "Картинка")]
    ORIGIN_COMPOSER = "composer"
    ORIGIN_TRAY = "tray"   # «Создать картинку» прямо в лоток
    ORIGIN_CHOICES = [(ORIGIN_COMPOSER, "Композер"), (ORIGIN_TRAY, "Лоток")]

    uid = models.CharField(max_length=32, unique=True, default=_uid, editable=False)
    user = models.ForeignKey(USER_MODEL, on_delete=models.CASCADE,
                             related_name="vstudio_shots", verbose_name="Пользователь")
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="shots",
                                verbose_name="Проект")
    kind = models.CharField(max_length=8, choices=KIND_CHOICES, verbose_name="Что")
    origin = models.CharField(max_length=8, choices=ORIGIN_CHOICES, default=ORIGIN_COMPOSER,
                              verbose_name="Откуда")
    # Модель могут убрать из каталога — запрос остаётся с её openrouter_id.
    model = models.ForeignKey("ai.GPTModels", on_delete=models.SET_NULL, null=True, blank=True,
                              related_name="+", verbose_name="Модель")
    model_ref = models.CharField(max_length=128, verbose_name="ID модели")
    prompt_doc = models.JSONField(verbose_name="Промпт (документ)")  # §4.1
    # Человекочитаемо, с «@Image N». БЕЗ обрезки: по нему поиск, копирование, админка.
    prompt_text = models.TextField(verbose_name="Промпт")
    # Как запросил человек: {duration, resolution, aspect_ratio|"auto",
    #  generate_audio, seed, negative_prompt}. Что ушло на деле — Take.effective.
    params = models.JSONField(default=dict, blank=True, verbose_name="Параметры")
    forked_from = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name="+", verbose_name="Изменён из")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Создан")

    class Meta:
        verbose_name = "Запрос видеостудии"
        verbose_name_plural = "Запросы видеостудии"
        indexes = [models.Index(fields=["project", "created_at"], name="vs_shot_proj")]

    def __str__(self):
        return f"{self.get_kind_display()} {self.uid[:8]} · {self.model_ref}"


class ShotInput(models.Model):
    """Материал в запросе. Номера @Image N считаются отсюда, в текст не пишутся."""

    SLOT_REFERENCE = "reference"
    SLOT_FIRST_FRAME = "first_frame"
    SLOT_LAST_FRAME = "last_frame"
    SLOT_CHOICES = [(SLOT_REFERENCE, "Референс"), (SLOT_FIRST_FRAME, "Первый кадр"),
                    (SLOT_LAST_FRAME, "Последний кадр")]
    FRAME_SLOTS = (SLOT_FIRST_FRAME, SLOT_LAST_FRAME)

    shot = models.ForeignKey(Shot, on_delete=models.CASCADE, related_name="inputs",
                             verbose_name="Запрос")
    # В спецификации PROTECT; RESTRICT держит ту же защиту (ассет, на который
    # ссылается запрос, жёстко не удалить — только мягко), но не мешает удалить
    # пользователя целиком: его запросы уходят каскадом в той же операции.
    # С PROTECT удаление аккаунта падало бы ProtectedError.
    asset = models.ForeignKey(Asset, on_delete=models.RESTRICT, related_name="+",
                              verbose_name="Материал")
    slot = models.CharField(max_length=12, choices=SLOT_CHOICES, verbose_name="Слот")
    position = models.PositiveSmallIntegerField(verbose_name="Позиция в лотке")
    # Роль в узле не хранится: одно фото можно упомянуть дважды.
    role = models.CharField(max_length=60, blank=True, default="", verbose_name="Роль")
    # False — серый чип «не учитывается и не оплачивается».
    included = models.BooleanField(default=True, verbose_name="Учитывается")

    class Meta:
        verbose_name = "Материал запроса"
        verbose_name_plural = "Материалы запроса"
        constraints = [
            models.UniqueConstraint(fields=["shot", "slot", "position"], name="vs_input_pos"),
            models.UniqueConstraint(fields=["shot", "slot", "asset"], name="vs_input_once"),
        ]

    def __str__(self):
        return f"{self.get_slot_display()} #{self.position}"


class TakeQuerySet(models.QuerySet):
    def open(self):
        return self.filter(status__in=TAKE_OPEN)

    def reserved(self):
        return self.filter(charge_state=CHARGE_RESERVED)

    def transition(self, pk, frm, to: str | None = None, **fields) -> bool:
        """Условный переход §2.2 одним UPDATE. True — строку сдвинул этот вызов.

        Ноль строк значит, что работу уже сделал кто-то другой (вторая копия
        задачи, sweep, отмена), и вызывающий тихо выходит. Доп. условия —
        цепочкой: Take.objects.filter(charge_state="reserved").transition(...).

        Зачем помощник, а не голый update():
        - update() не трогает auto_now, а sweep ищет зависшие «submitting» по
          updated_at — время ставим сами, иначе дубль, простоявший в очереди,
          сочли бы зависшим сразу после захвата;
        - failed/canceled/lost снимают резерв тем же UPDATE: у закрытого дубля
          денег в резерве не бывает (CheckConstraint vs_take_open_reserved).
          Для done charge_state задаёт вызывающий (charged при выдаче;
          при довозе из lost он уже released).
        """
        statuses = (frm,) if isinstance(frm, str) else tuple(frm)
        now = timezone.now()
        if to is not None:
            fields["status"] = to
            if to in TAKE_CLOSED:
                fields.setdefault("finished_at", now)
            if to in TAKE_RELEASING:
                fields.setdefault("charge_state", CHARGE_RELEASED)
        fields.setdefault("updated_at", now)
        return self.filter(pk=pk, status__in=statuses).update(**fields) == 1


class Take(models.Model):
    """ОДНА оплачиваемая попытка = один вызов провайдера = одна строка журнала."""

    KIND_VIDEO = "video"
    KIND_IMAGE = "image"
    KIND_CHOICES = [(KIND_VIDEO, "Видео"), (KIND_IMAGE, "Картинка")]

    STATUS_QUEUED = TAKE_QUEUED
    STATUS_SUBMITTING = TAKE_SUBMITTING
    STATUS_RUNNING = TAKE_RUNNING
    STATUS_SAVING = TAKE_SAVING
    STATUS_DONE = TAKE_DONE
    STATUS_FAILED = TAKE_FAILED
    STATUS_CANCELED = TAKE_CANCELED
    STATUS_LOST = TAKE_LOST
    STATUS_CHOICES = [
        (TAKE_QUEUED, "В очереди"),
        (TAKE_SUBMITTING, "Отправляется"),
        (TAKE_RUNNING, "Генерируется"),
        (TAKE_SAVING, "Сохраняется"),
        (TAKE_DONE, "Готово"),
        (TAKE_FAILED, "Не получилось"),
        (TAKE_CANCELED, "Отменён"),
        (TAKE_LOST, "Потерян"),
    ]
    OPEN = TAKE_OPEN
    CLOSED = TAKE_CLOSED

    CHARGE_RESERVED = CHARGE_RESERVED
    CHARGE_CHARGED = CHARGE_CHARGED
    CHARGE_RELEASED = CHARGE_RELEASED
    CHARGE_CHOICES = [(CHARGE_RESERVED, "В резерве"), (CHARGE_CHARGED, "Списано"),
                      (CHARGE_RELEASED, "Резерв снят")]

    MODE_T2V = "t2v"
    MODE_I2V = "i2v"
    MODE_FLF2V = "flf2v"
    MODE_R2V = "r2v"
    MODE_R2V_PIN = "r2v_pin"
    MODE_T2I = "t2i"
    MODE_I2I = "i2i"
    MODE_CHOICES = [
        (MODE_T2V, "Текст → видео"),
        (MODE_I2V, "Первый кадр → видео"),
        (MODE_FLF2V, "Первый и последний кадр"),
        (MODE_R2V, "Референсы → видео"),
        (MODE_R2V_PIN, "Референсы + мягкий первый кадр"),
        (MODE_T2I, "Текст → картинка"),
        (MODE_I2I, "Фото → картинка"),
    ]

    uid = models.CharField(max_length=32, unique=True, default=_uid, editable=False)
    user = models.ForeignKey(USER_MODEL, on_delete=models.CASCADE,
                             related_name="vstudio_takes", verbose_name="Пользователь")
    shot = models.ForeignKey(Shot, on_delete=models.CASCADE, related_name="takes",
                             verbose_name="Запрос")
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="+",
                                verbose_name="Проект")
    kind = models.CharField(max_length=8, choices=KIND_CHOICES, verbose_name="Что")
    mode = models.CharField(max_length=8, choices=MODE_CHOICES, verbose_name="Режим")
    model_ref = models.CharField(max_length=128, verbose_name="Модель")
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=TAKE_QUEUED,
                              db_index=True, verbose_name="Состояние")
    # Статус провайдера во время опроса (in_progress, …) — для «идёт генерация».
    stage = models.CharField(max_length=24, blank=True, default="", verbose_name="Шаг")
    # Ровно то, что ушло модели: блок «Что ушло модели» и разбор жалоб.
    serialized_prompt = models.TextField(verbose_name="Текст для модели")
    # Тело submit без ключей, URL абсолютные.
    request_body = models.JSONField(verbose_name="Тело запроса")
    # {duration, resolution, aspect_ratio, generate_audio} — по ним и цена.
    effective = models.JSONField(default=dict, blank=True, verbose_name="Фактические параметры")
    # [{asset, slot, reason}] — выключенное человеком и лишнее: не ушло и не оплачено.
    dropped = models.JSONField(default=list, blank=True, verbose_name="Не отправлено")
    warnings = models.JSONField(default=list, blank=True, verbose_name="Предупреждения")  # [{code, params}]
    credits_quoted = models.PositiveIntegerField(verbose_name="Цена на кнопке, кр")
    credits_reserved = models.PositiveIntegerField(verbose_name="В резерве, кр")
    credits_charged = models.PositiveIntegerField(default=0, verbose_name="Списано, кр")
    charge_state = models.CharField(max_length=10, choices=CHARGE_CHOICES, default=CHARGE_RESERVED,
                                    db_index=True, verbose_name="Деньги")
    # ID и адрес опроса лежат на дубле: если провайдер принял работу, результат
    # довезём даже при потере журнала или задачи.
    provider_id = models.CharField(max_length=160, blank=True, default="", db_index=True,
                                   verbose_name="ID у провайдера")
    polling_url = models.CharField(max_length=512, blank=True, default="",
                                   verbose_name="Адрес опроса")
    # Чьим ключом отправлена работа. Работу видит только принявший её аккаунт:
    # после автопереключения на запасной опрос чужим ключом получал 401/404, и
    # оплаченный ролик до выдачи не доезжал. Опрос, скачивание и «Довезти»
    # берут ключ отсюда (media_provider.config_for). Не FK: аккаунт могут
    # удалить, а отпечаток всё равно найдёт ключ в настройках.
    provider_account_id = models.PositiveIntegerField(null=True, blank=True,
                                                      verbose_name="Аккаунт OpenRouter")
    provider_key_fp = models.CharField(max_length=16, blank=True, default="",
                                       verbose_name="Отпечаток ключа")
    # Сколько опросов подряд провайдер ответил 401/403/404/410 («работы не
    # вижу»): после POLL_UNREACHABLE_MAX дубль — lost, резерв снят.
    poll_errors = models.PositiveSmallIntegerField(default=0, verbose_name="Ошибок опроса подряд")
    provider_cost_usd = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True,
                                            verbose_name="Себестоимость, $")
    genlog = models.OneToOneField("ai.GenerationLog", on_delete=models.SET_NULL, null=True,
                                  blank=True, related_name="vstudio_take",
                                  verbose_name="Запись журнала")
    # У картинок ассет в pending создаётся сразу при запуске — чип в лотке.
    result_asset = models.ForeignKey(Asset, on_delete=models.SET_NULL, null=True, blank=True,
                                     related_name="+", verbose_name="Результат")
    error = models.TextField(blank=True, default="", verbose_name="Ошибка")
    error_code = models.CharField(max_length=40, blank=True, default="", verbose_name="Код ошибки")
    # uid виноватого входа (модерация провайдера) — подсветка фото в ленте.
    error_input = models.CharField(max_length=32, blank=True, default="",
                                   verbose_name="Виноватый материал")
    next_poll_at = models.DateTimeField(null=True, blank=True, verbose_name="Следующий опрос")
    poll_count = models.PositiveIntegerField(default=0, verbose_name="Опросов")
    lease_until = models.DateTimeField(null=True, blank=True, verbose_name="Аренда до")
    attempts = models.PositiveSmallIntegerField(default=0, verbose_name="Попыток сохранения")
    # Идемпотентность запуска: повтор того же клика не создаёт второй дубль.
    client_request_id = models.CharField(max_length=64, blank=True, default="",
                                         verbose_name="ID клика")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Создан")
    submitted_at = models.DateTimeField(null=True, blank=True, verbose_name="Отправлен")
    finished_at = models.DateTimeField(null=True, blank=True, verbose_name="Завершён")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Изменён")

    objects = TakeQuerySet.as_manager()

    class Meta:
        verbose_name = "Дубль видеостудии"
        verbose_name_plural = "Дубли видеостудии"
        constraints = [
            models.UniqueConstraint(fields=["user", "client_request_id"],
                                    condition=~Q(client_request_id=""), name="vs_take_idem"),
            # У открытого дубля деньги всегда в резерве, у закрытого — никогда.
            # Ошибка в коде перехода станет IntegrityError, а не «вечным резервом».
            models.CheckConstraint(
                name="vs_take_open_reserved",
                condition=(Q(status__in=TAKE_OPEN) & Q(charge_state=CHARGE_RESERVED))
                | (~Q(status__in=TAKE_OPEN) & ~Q(charge_state=CHARGE_RESERVED)),
            ),
        ]
        indexes = [
            models.Index(fields=["status", "next_poll_at"], name="vs_take_poll"),
            models.Index(fields=["user", "charge_state"], name="vs_take_user_res"),
            models.Index(fields=["shot", "created_at"], name="vs_take_shot"),
        ]

    def __str__(self):
        return f"{self.get_kind_display()} {self.uid[:8]} · {self.get_status_display()}"

    @property
    def is_open(self) -> bool:
        return self.status in TAKE_OPEN


class ShowcaseItem(models.Model):
    """Работа в витрине первого экрана (карусель «12 сценариев»).

    Строка — разрешение показать результат одного готового дубля всем, включая
    гостей; ставит её владелец в /admin-new. Своего ролика у строки нет:
    витрина показывает сам материал дубля, поэтому результат, удалённый
    человеком, пропадает и отсюда. Единственная копия — лёгкий ролик для лент
    (clip): его стирают вместе со строкой и вместе с результатом. Что именно
    уходит наружу — vstudio.showcase.
    """

    # Сценарий — для чего ролик: под этим именем он стоит в карусели. Те же
    # ключи у фронта (home/scenarios.ts); поле — 8 символов, длиннее ключ не влезет.
    CATEGORY_FILM = "film"
    CATEGORY_AD = "ad"
    CATEGORY_PERSON = "person"
    CATEGORY_CAR = "car"
    CATEGORY_ACTION = "action"
    CATEGORY_SCIFI = "scifi"
    CATEGORY_FASHION = "fashion"
    CATEGORY_MUSIC = "music"
    CATEGORY_I2V = "i2v"
    CATEGORY_ANIM = "anim"
    CATEGORY_REAL = "real"
    CATEGORY_VERTICAL = "vertical"
    CATEGORY_OTHER = "other"
    CATEGORY_CHOICES = [
        (CATEGORY_FILM, "Киносцена"),
        (CATEGORY_AD, "Реклама товара"),
        (CATEGORY_PERSON, "Персонаж"),
        (CATEGORY_CAR, "Автомобиль"),
        (CATEGORY_ACTION, "Экшен"),
        (CATEGORY_SCIFI, "Фантастика"),
        (CATEGORY_FASHION, "Fashion"),
        (CATEGORY_MUSIC, "Музыкальный клип"),
        (CATEGORY_I2V, "Image → Video"),
        (CATEGORY_ANIM, "Анимация"),
        (CATEGORY_REAL, "Реалистичная сцена"),
        (CATEGORY_VERTICAL, "Reels / TikTok"),
        (CATEGORY_OTHER, "Другое"),
    ]
    # Порядок карусели. «Другое» — не сценарий: такая работа своего места в ней не имеет.
    SCENARIOS = (
        CATEGORY_FILM, CATEGORY_AD, CATEGORY_PERSON, CATEGORY_CAR, CATEGORY_ACTION,
        CATEGORY_SCIFI, CATEGORY_FASHION, CATEGORY_MUSIC, CATEGORY_I2V, CATEGORY_ANIM,
        CATEGORY_REAL, CATEGORY_VERTICAL,
    )

    # Один дубль — одна строка: второй раз ту же работу в витрину не поставить.
    # Дубль уходит (удалили аккаунт) — уходит и строка.
    take = models.OneToOneField(Take, on_delete=models.CASCADE, related_name="showcase",
                                verbose_name="Дубль")
    title = models.CharField(max_length=80, blank=True, default="", verbose_name="Название")
    category = models.CharField(max_length=8, choices=CATEGORY_CHOICES, default=CATEGORY_OTHER,
                                verbose_name="Сценарий")
    # Меньше — выше; при равных выше та, что добавлена позже.
    sort = models.IntegerField(default=0, verbose_name="Порядок")
    is_active = models.BooleanField(default=True, verbose_name="Показывать")
    # Запрос — чужая находка: наружу только по явной галочке. С ней же виден
    # первый кадр работы «Image → Video» (vstudio.showcase.start_frame_url).
    show_prompt = models.BooleanField(default=False, verbose_name="Показывать запрос")
    # Первый экран сам крутит ролики в карусели, а результат дубля весит
    # мегабайты. Копию (480 px, без звука) собирает задача
    # build_showcase_clip; пока её нет, на сайте играет исходник.
    clip = models.FileField(upload_to="vstudio/showcase/", blank=True,
                            verbose_name="Ролик для ленты (лёгкий)")
    created_by = models.ForeignKey(USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="+", verbose_name="Кто добавил")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Добавлена")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Изменена")

    class Meta:
        verbose_name = "Работа в витрине"
        verbose_name_plural = "Витрина видеостудии"

    def __str__(self):
        return self.title or f"Работа {self.take_id}"
