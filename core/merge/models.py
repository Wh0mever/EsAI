"""Склейка (/merge): готовые ролики человека → один ролик.

Источники — только свои видео человека: готовые ролики EsAI (дубли
видеостудии, сцены и мультфильмы мультстудии, видео чата) и загруженные им
самим файлы (MergeUpload, Build MU: до 90 МБ и 60 с, хранятся 30 дней).

Деньги — как в видеостудии: при запуске цена встаёт в резерв (credits_reserved
у строки в очереди или в работе), списание — только за готовый ролик, сбой
снимает резерв тем же UPDATE, что закрывает склейку. Все переходы — условные
UPDATE: вторая копия задачи или уборка не спишут и не закроют второй раз.
"""
from __future__ import annotations

import uuid
from datetime import timedelta

from django.conf import settings
from django.core.files.storage import default_storage
from django.db import models
from django.db.models import Q
from django.utils import timezone

from .config import ASPECTS, FIT_PAD, FITS, UPLOAD_RETENTION_DAYS

STATUS_DRAFT = "draft"
STATUS_QUEUED = "queued"
STATUS_RENDERING = "rendering"
STATUS_READY = "ready"
STATUS_FAILED = "failed"
STATUS_EXPIRED = "expired"
# В очереди или в работе: держит резерв, править и удалять нельзя.
ACTIVE = (STATUS_QUEUED, STATUS_RENDERING)
# Можно менять фрагменты и запускать: готовую склейку не переделываем —
# за неё уже заплачено, новая — это новая строка.
EDITABLE = (STATUS_DRAFT, STATUS_FAILED, STATUS_EXPIRED)
DELETABLE = (STATUS_DRAFT, STATUS_READY, STATUS_FAILED, STATUS_EXPIRED)


def _uid() -> str:
    return uuid.uuid4().hex


class MergeProject(models.Model):
    """Склейка человека: упорядоченный список фрагментов и итоговый ролик."""

    STATUS_DRAFT = STATUS_DRAFT
    STATUS_QUEUED = STATUS_QUEUED
    STATUS_RENDERING = STATUS_RENDERING
    STATUS_READY = STATUS_READY
    STATUS_FAILED = STATUS_FAILED
    STATUS_EXPIRED = STATUS_EXPIRED
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Черновик"),
        (STATUS_QUEUED, "В очереди"),
        (STATUS_RENDERING, "Склеивается"),
        (STATUS_READY, "Готова"),
        (STATUS_FAILED, "Не получилась"),
        (STATUS_EXPIRED, "Срок хранения истёк"),
    ]
    ACTIVE = ACTIVE
    EDITABLE = EDITABLE
    DELETABLE = DELETABLE

    ASPECT_CHOICES = [(a, a) for a in ASPECTS]
    FIT_CHOICES = [("pad", "Поля (размытый фон)"), ("crop", "Обрезать по центру")]

    # Публичный идентификатор — только uid: чужая склейка неотличима от несуществующей.
    uid = models.CharField(max_length=32, unique=True, default=_uid, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="merge_projects", verbose_name="Пользователь")
    title = models.CharField(max_length=140, blank=True, default="", verbose_name="Название")
    aspect = models.CharField(max_length=5, choices=ASPECT_CHOICES, default="16:9",
                              verbose_name="Формат")
    fit = models.CharField(max_length=4, choices=FIT_CHOICES, default=FIT_PAD,
                           verbose_name="Заполнение")
    # [{type, id, title, subtitle, file, poster, duration_s, width, height}] —
    # ссылка на источник (type + id) и снимок его карточки на момент сохранения:
    # опрос готовой склейки не перечитывает тридцать источников раз в три секунды.
    items = models.JSONField(default=list, blank=True, verbose_name="Фрагменты")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_DRAFT,
                              db_index=True, verbose_name="Состояние")
    error = models.TextField(blank=True, default="", verbose_name="Ошибка")
    # Код ошибки и номер фрагмента (с 1): интерфейс переводит по коду, а
    # русский текст error — его запасной вариант.
    error_code = models.CharField(max_length=40, blank=True, default="", verbose_name="Код ошибки")
    error_fragment = models.PositiveSmallIntegerField(null=True, blank=True,
                                                      verbose_name="Фрагмент с ошибкой")
    # Ход склейки для экрана ожидания: queued | preparing | normalizing | joining | saving.
    progress_stage = models.CharField(max_length=16, blank=True, default="", verbose_name="Шаг")
    progress_done = models.PositiveSmallIntegerField(default=0, verbose_name="Готово фрагментов")
    progress_total = models.PositiveSmallIntegerField(default=0, verbose_name="Всего фрагментов")
    # Пути в default_storage: merge/<user_id>/<uid>-<hex>.mp4 и обложка .jpg.
    result_video = models.CharField(max_length=512, blank=True, default="", verbose_name="Ролик")
    poster = models.CharField(max_length=512, blank=True, default="", verbose_name="Обложка")
    duration_s = models.FloatField(null=True, blank=True, verbose_name="Длительность, с")
    credits_reserved = models.PositiveIntegerField(default=0, verbose_name="В резерве, кр")
    credits_charged = models.PositiveIntegerField(default=0, verbose_name="Списано, кр")
    queued_at = models.DateTimeField(null=True, blank=True, verbose_name="Поставлена в очередь")
    # Отметка своего запуска: итог пишет только задача, которая его начала.
    render_started_at = models.DateTimeField(null=True, blank=True, verbose_name="Склейка началась")
    finished_at = models.DateTimeField(null=True, blank=True, verbose_name="Закончена")
    expires_at = models.DateTimeField(null=True, blank=True, db_index=True,
                                      verbose_name="Хранится до")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Создана")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Изменена")

    class Meta:
        verbose_name = "Склейка"
        verbose_name_plural = "Склейки"
        constraints = [
            # Резерв бывает только у склейки в очереди или в работе. Ошибка в
            # коде перехода станет IntegrityError, а не «вечным резервом».
            models.CheckConstraint(name="merge_reserve_only_active",
                                   condition=Q(status__in=ACTIVE) | Q(credits_reserved=0)),
            # Одна склейка в работе на человека: замок строки пользователя
            # выстраивает запуски в очередь, индекс страхует от гонки.
            models.UniqueConstraint(fields=["user"], condition=Q(status__in=ACTIVE),
                                    name="merge_one_active_per_user"),
        ]
        indexes = [models.Index(fields=["user", "-updated_at"], name="merge_user_upd")]

    def __str__(self):
        return self.title or f"Склейка {self.uid[:8]}"

    @property
    def is_active(self) -> bool:
        return self.status in ACTIVE

    @property
    def result_url(self) -> str:
        return default_storage.url(self.result_video) if self.result_video else ""

    @property
    def poster_url(self) -> str:
        return default_storage.url(self.poster) if self.poster else ""


def _upload_expiry():
    return timezone.now() + timedelta(days=UPLOAD_RETENTION_DAYS)


class MergeUpload(models.Model):
    """Своё видео человека для склейки (вкладка «Мои файлы»).

    Файл лежит под именем, которое придумал сервер (uid), — имя с телефона
    остаётся только подписью. Отклонённая загрузка (rejected) — строка без
    файла: видно, что и почему не приняли.
    """

    STATUS_READY = "ready"
    STATUS_REJECTED = "rejected"
    STATUS_CHOICES = [(STATUS_READY, "Готово"), (STATUS_REJECTED, "Отклонено")]

    # Публичный идентификатор и имя файла: чужое видео неотличимо от несуществующего.
    uid = models.CharField(max_length=32, unique=True, default=_uid, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="merge_uploads", verbose_name="Пользователь")
    title = models.CharField(max_length=80, blank=True, default="", verbose_name="Подпись")
    # Пути в default_storage: merge/uploads/<user_id>/<uid>.mp4|webm и обложка .jpg.
    file = models.CharField(max_length=512, blank=True, default="", verbose_name="Файл")
    poster = models.CharField(max_length=512, blank=True, default="", verbose_name="Обложка")
    size = models.PositiveBigIntegerField(default=0, verbose_name="Размер, байт")
    duration_s = models.FloatField(null=True, blank=True, verbose_name="Длительность, с")
    # Размер кадра в файле и на экране: телефон пишет вертикальное видео
    # горизонтальным кадром с пометкой «повернуть» — показываем по повороту.
    width = models.PositiveIntegerField(null=True, blank=True, verbose_name="Ширина в файле")
    height = models.PositiveIntegerField(null=True, blank=True, verbose_name="Высота в файле")
    display_width = models.PositiveIntegerField(null=True, blank=True, verbose_name="Ширина")
    display_height = models.PositiveIntegerField(null=True, blank=True, verbose_name="Высота")
    rotation = models.SmallIntegerField(default=0, verbose_name="Поворот, °")
    has_audio = models.BooleanField(default=False, verbose_name="Есть звук")
    video_codec = models.CharField(max_length=16, blank=True, default="", verbose_name="Кодек")
    hdr = models.BooleanField(default=False, verbose_name="HDR")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_READY,
                              db_index=True, verbose_name="Состояние")
    # Почему отклонено (код отказа API) — для разбора, человеку отвечает API.
    error_code = models.CharField(max_length=40, blank=True, default="", verbose_name="Код отказа")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Загружено")
    # 30 дней с загрузки; склейка, в которую видео вошло, продлевает его до
    # своего срока хранения (уборка не трогает видео идущей склейки).
    expires_at = models.DateTimeField(default=_upload_expiry, db_index=True,
                                      verbose_name="Хранится до")

    class Meta:
        verbose_name = "Своё видео"
        verbose_name_plural = "Свои видео"
        indexes = [models.Index(fields=["user", "status", "-created_at"], name="merge_upload_user")]

    def __str__(self):
        return self.title or f"Видео {self.uid[:8]}"

    @property
    def container(self) -> str:
        """Демуксер ffmpeg для файла: тип определён по первым байтам при загрузке."""
        return "matroska" if self.file.endswith(".webm") else "mov"


__all__ = ["MergeProject", "MergeUpload", "ACTIVE", "EDITABLE", "DELETABLE", "FITS"]
