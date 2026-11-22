"""Creative Studio (/creative): 15 инструментов на стороннем API генерации.

Схема повторяет видеостудию (vstudio.models.Take):
- CreativeJob — ОДНА оплачиваемая задача = один запрос к поставщику = одна
  строка журнала генераций. Резерв кредитов — сама строка (charge_state), все
  переходы — условные UPDATE (CreativeJob.objects.transition), поэтому списание
  и снятие резерва случаются ровно один раз, даже если вебхук и опрос пришли
  одновременно.
- CreativeUpload — файл человека (фото или видео), уже проверенный и
  приведённый к виду, который принимает поставщик (видео — MP4).
- CreativeCharacter — свой персонаж («Постоянный персонаж»): обучение — это
  задача kind=character, персонаж у поставщика общий на весь аккаунт EsAI,
  поэтому владельца проверяет только наша база.

Публичные идентификаторы — только uid (uuid4().hex). Имя поставщика и адреса
его моделей в базе не храним: адреса моделей живут в creative/registry.py,
а в params лежат наши имена полей и uid своих загрузок. request_body — тело,
ушедшее поставщику (с его временными ссылками на файлы): служебное поле, в API
и в админку не отдаётся, нужно только для повтора с тем же Idempotency-Key.
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


# Константы задачи нужны и в Meta (CheckConstraint) — поэтому на уровне модуля.
JOB_QUEUED = "queued"
JOB_SUBMITTING = "submitting"
JOB_RUNNING = "running"
JOB_SAVING = "saving"
JOB_DONE = "done"
JOB_FAILED = "failed"
JOB_NSFW = "nsfw"
JOB_CANCELED = "canceled"
JOB_LOST = "lost"
JOB_OPEN = (JOB_QUEUED, JOB_SUBMITTING, JOB_RUNNING, JOB_SAVING)
JOB_CLOSED = (JOB_DONE, JOB_FAILED, JOB_NSFW, JOB_CANCELED, JOB_LOST)
# Исходы, при которых человек не платит: резерв снимается тем же UPDATE.
JOB_RELEASING = (JOB_FAILED, JOB_NSFW, JOB_CANCELED, JOB_LOST)

CHARGE_RESERVED = "reserved"
CHARGE_CHARGED = "charged"
CHARGE_RELEASED = "released"

KIND_IMAGE = "image"
KIND_VIDEO = "video"
KIND_CHARACTER = "character"


class CreativeTool(models.Model):
    """Настройки инструмента из админки. Строки нет — инструмент включён, наценка общая.

    slug совпадает с id карточки на сайте (next/src/lib/creative/tools.ts).
    """

    slug = models.CharField(max_length=40, unique=True, verbose_name="Инструмент")
    enabled = models.BooleanField(default=True, verbose_name="Включён")
    # Своя наценка, % к себестоимости; null — общая (runtime creative_markup_pct).
    markup_pct = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True,
                                     verbose_name="Своя наценка, %")
    use_own_markup = models.BooleanField(default=False, verbose_name="Своя наценка включена")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Изменён")

    class Meta:
        verbose_name = "Инструмент Creative Studio"
        verbose_name_plural = "Инструменты Creative Studio"

    def __str__(self):
        return self.slug


class CreativeJobQuerySet(models.QuerySet):
    def open(self):
        return self.filter(status__in=JOB_OPEN)

    def reserved(self):
        return self.filter(charge_state=CHARGE_RESERVED)

    def transition(self, pk, frm, to: str | None = None, **fields) -> bool:
        """Условный переход одним UPDATE. True — строку сдвинул этот вызов.

        Ноль строк — работу уже сделал кто-то другой (вторая копия задачи,
        вебхук, sweep, отмена): вызывающий тихо выходит. Доп. условия —
        цепочкой: CreativeJob.objects.filter(charge_state="reserved").transition(...).
        failed/nsfw/canceled/lost снимают резерв тем же UPDATE (CheckConstraint
        cs_job_open_reserved не даст закрытой задаче держать деньги).
        updated_at ставим сами: update() не трогает auto_now, а sweep ищет
        зависшие шаги по нему.
        """
        statuses = (frm,) if isinstance(frm, str) else tuple(frm)
        now = timezone.now()
        if to is not None:
            fields["status"] = to
            if to in JOB_CLOSED:
                fields.setdefault("finished_at", now)
            if to in JOB_RELEASING:
                fields.setdefault("charge_state", CHARGE_RELEASED)
        fields.setdefault("updated_at", now)
        return self.filter(pk=pk, status__in=statuses).update(**fields) == 1


class CreativeJob(models.Model):
    """Одна оплачиваемая задача инструмента."""

    KIND_CHOICES = [(KIND_IMAGE, "Картинка"), (KIND_VIDEO, "Видео"), (KIND_CHARACTER, "Персонаж")]
    STATUS_CHOICES = [
        (JOB_QUEUED, "В очереди"),
        (JOB_SUBMITTING, "Отправляется"),
        (JOB_RUNNING, "Генерируется"),
        (JOB_SAVING, "Сохраняется"),
        (JOB_DONE, "Готово"),
        (JOB_FAILED, "Не получилось"),
        (JOB_NSFW, "Отклонено модерацией"),
        (JOB_CANCELED, "Отменена"),
        (JOB_LOST, "Потеряна"),
    ]
    CHARGE_CHOICES = [(CHARGE_RESERVED, "В резерве"), (CHARGE_CHARGED, "Списано"),
                      (CHARGE_RELEASED, "Резерв снят")]
    OPEN = JOB_OPEN
    CLOSED = JOB_CLOSED

    uid = models.CharField(max_length=32, unique=True, default=_uid, editable=False)
    user = models.ForeignKey(USER_MODEL, on_delete=models.CASCADE, related_name="creative_jobs",
                             verbose_name="Пользователь")
    tool_slug = models.CharField(max_length=40, db_index=True, verbose_name="Инструмент")
    kind = models.CharField(max_length=10, choices=KIND_CHOICES, verbose_name="Что")
    # Параметры формы нашими именами и uid своих загрузок — без ссылок поставщика.
    params = models.JSONField(default=dict, blank=True, verbose_name="Параметры")
    # {"body": тело поставщику, "hook": адрес вебхука или ""} — для повтора с тем
    # же Idempotency-Key. Служебное: наружу не отдаётся.
    request_body = models.JSONField(default=dict, blank=True, editable=False,
                                    verbose_name="Отправлено (служебное)")
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=JOB_QUEUED,
                              db_index=True, verbose_name="Состояние")
    # Шаг для «идёт генерация»: наши слова (queued, in_progress, uploading, saving…).
    stage = models.CharField(max_length=24, blank=True, default="", verbose_name="Шаг")
    charge_state = models.CharField(max_length=10, choices=CHARGE_CHOICES, default=CHARGE_RESERVED,
                                    db_index=True, verbose_name="Деньги")
    credits_quoted = models.PositiveIntegerField(verbose_name="Цена на кнопке, кр")
    credits_reserved = models.PositiveIntegerField(verbose_name="В резерве, кр")
    credits_charged = models.PositiveIntegerField(default=0, verbose_name="Списано, кр")
    cost_usd = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True,
                                   verbose_name="Себестоимость, $")
    markup_pct_at_launch = models.DecimalField(max_digits=7, decimal_places=2, null=True,
                                               blank=True, verbose_name="Наценка при запуске, %")
    # Сколько файлов обещано (партия картинок): выдали меньше — платят за выданные.
    expected_outputs = models.PositiveSmallIntegerField(default=1, verbose_name="Ожидается файлов")
    provider_request_id = models.CharField(max_length=64, blank=True, default="", db_index=True,
                                           verbose_name="ID у поставщика")
    idempotency_key = models.CharField(max_length=64, blank=True, default="",
                                       verbose_name="Ключ идемпотентности")
    client_request_id = models.CharField(max_length=64, blank=True, default="",
                                         verbose_name="ID клика")
    # [{path, mime, w, h, bytes, poster}] — файлы в default_storage.
    result_files = models.JSONField(default=list, blank=True, verbose_name="Результаты")
    error_code = models.CharField(max_length=40, blank=True, default="", verbose_name="Код ошибки")
    error = models.TextField(blank=True, default="", verbose_name="Ошибка")
    needs_review = models.BooleanField(default=False, db_index=True, verbose_name="Нужен разбор")
    next_poll_at = models.DateTimeField(null=True, blank=True, verbose_name="Следующий шаг")
    poll_count = models.PositiveIntegerField(default=0, verbose_name="Опросов")
    poll_errors = models.PositiveSmallIntegerField(default=0, verbose_name="Ошибок опроса подряд")
    lease_until = models.DateTimeField(null=True, blank=True, verbose_name="Аренда до")
    attempts = models.PositiveSmallIntegerField(default=0, verbose_name="Попыток")
    genlog = models.OneToOneField("ai.GenerationLog", on_delete=models.SET_NULL, null=True,
                                  blank=True, related_name="creative_job",
                                  verbose_name="Запись журнала")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Создана")
    submitted_at = models.DateTimeField(null=True, blank=True, verbose_name="Отправлена")
    finished_at = models.DateTimeField(null=True, blank=True, verbose_name="Завершена")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Изменена")

    objects = CreativeJobQuerySet.as_manager()

    class Meta:
        verbose_name = "Задача Creative Studio"
        verbose_name_plural = "Задачи Creative Studio"
        constraints = [
            models.UniqueConstraint(fields=["user", "client_request_id"],
                                    condition=~Q(client_request_id=""), name="cs_job_idem"),
            # У открытой задачи деньги всегда в резерве, у закрытой — никогда.
            models.CheckConstraint(
                name="cs_job_open_reserved",
                condition=(Q(status__in=JOB_OPEN) & Q(charge_state=CHARGE_RESERVED))
                | (~Q(status__in=JOB_OPEN) & ~Q(charge_state=CHARGE_RESERVED)),
            ),
        ]
        indexes = [
            models.Index(fields=["status", "next_poll_at"], name="cs_job_poll"),
            models.Index(fields=["user", "charge_state"], name="cs_job_user_res"),
            models.Index(fields=["user", "created_at"], name="cs_job_user_time"),
        ]

    def __str__(self):
        return f"{self.tool_slug} {self.uid[:8]} · {self.get_status_display()}"

    @property
    def is_open(self) -> bool:
        return self.status in JOB_OPEN


class CreativeUpload(models.Model):
    """Файл человека для инструмента: фото или видео (уже MP4)."""

    KIND_IMAGE = "image"
    KIND_VIDEO = "video"
    KIND_CHOICES = [(KIND_IMAGE, "Фото"), (KIND_VIDEO, "Видео")]

    uid = models.CharField(max_length=32, unique=True, default=_uid, editable=False)
    user = models.ForeignKey(USER_MODEL, on_delete=models.CASCADE, related_name="creative_uploads",
                             verbose_name="Пользователь")
    kind = models.CharField(max_length=8, choices=KIND_CHOICES, verbose_name="Что")
    path = models.CharField(max_length=255, verbose_name="Файл")
    # Превью: у фото — уменьшенная копия, у видео — кадр.
    thumb_path = models.CharField(max_length=255, blank=True, default="", verbose_name="Превью")
    mime = models.CharField(max_length=40, verbose_name="Тип")
    bytes = models.PositiveBigIntegerField(default=0, verbose_name="Размер")
    w = models.PositiveIntegerField(null=True, blank=True, verbose_name="Ширина")
    h = models.PositiveIntegerField(null=True, blank=True, verbose_name="Высота")
    duration_s = models.FloatField(null=True, blank=True, verbose_name="Длительность, с")
    sha256 = models.CharField(max_length=64, blank=True, default="", db_index=True,
                              verbose_name="SHA-256")
    # Временная ссылка на копию у поставщика (его CDN): только сервер.
    provider_url = models.CharField(max_length=2100, blank=True, default="", editable=False,
                                    verbose_name="Копия у поставщика (служебное)")
    provider_url_expires_at = models.DateTimeField(null=True, blank=True,
                                                   verbose_name="Копия у поставщика до")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name="Загружен")

    class Meta:
        verbose_name = "Загрузка Creative Studio"
        verbose_name_plural = "Загрузки Creative Studio"
        indexes = [models.Index(fields=["user", "created_at"], name="cs_upload_user_time")]

    def __str__(self):
        return f"{self.get_kind_display()} {self.uid[:8]}"

    @property
    def url(self) -> str:
        return _media_url(self.path)

    @property
    def thumb_url(self) -> str:
        return _media_url(self.thumb_path)

    @property
    def pixels(self) -> int:
        return int(self.w or 0) * int(self.h or 0)


class CreativeCharacter(models.Model):
    """Свой персонаж человека. «Удалить» — скрыть у себя (deleted_at): у поставщика удаления нет."""

    STATUS_TRAINING = "training"
    STATUS_READY = "ready"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [(STATUS_TRAINING, "Обучается"), (STATUS_READY, "Готов"),
                      (STATUS_FAILED, "Не получился")]

    uid = models.CharField(max_length=32, unique=True, default=_uid, editable=False)
    user = models.ForeignKey(USER_MODEL, on_delete=models.CASCADE,
                             related_name="creative_characters", verbose_name="Пользователь")
    name = models.CharField(max_length=60, verbose_name="Имя")
    provider_id = models.CharField(max_length=64, blank=True, default="", db_index=True,
                                   verbose_name="ID у поставщика")
    model_version = models.CharField(max_length=8, default="v2", verbose_name="Версия")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_TRAINING,
                              db_index=True, verbose_name="Состояние")
    thumb_path = models.CharField(max_length=255, blank=True, default="", verbose_name="Превью")
    job = models.ForeignKey(CreativeJob, on_delete=models.SET_NULL, null=True, blank=True,
                            related_name="characters", verbose_name="Задача обучения")
    deleted_at = models.DateTimeField(null=True, blank=True, verbose_name="Скрыт")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Создан")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Изменён")

    class Meta:
        verbose_name = "Персонаж Creative Studio"
        verbose_name_plural = "Персонажи Creative Studio"
        indexes = [models.Index(fields=["user", "deleted_at"], name="cs_char_user")]

    def __str__(self):
        return self.name or f"Персонаж {self.uid[:8]}"

    @property
    def thumb_url(self) -> str:
        return _media_url(self.thumb_path)


class CreativeWebhookEvent(models.Model):
    """Доставка вебхука поставщика: дубли отсекаются по event_key (webhook-id)."""

    event_key = models.CharField(max_length=64, unique=True, verbose_name="Ключ события")
    provider_request_id = models.CharField(max_length=64, blank=True, default="", db_index=True,
                                           verbose_name="ID у поставщика")
    status = models.CharField(max_length=16, blank=True, default="", verbose_name="Статус")
    # Только белый список полей: без ссылок на файлы и текстов поставщика.
    payload = models.JSONField(default=dict, blank=True, verbose_name="Данные")
    processed = models.BooleanField(default=False, verbose_name="Обработано")
    received_at = models.DateTimeField(auto_now_add=True, verbose_name="Получено")

    class Meta:
        verbose_name = "Вебхук Creative Studio"
        verbose_name_plural = "Вебхуки Creative Studio"

    def __str__(self):
        return f"{self.provider_request_id} {self.status}"
