"""Склейка (/merge): готовые ролики человека → один ролик.

Источники — только свои видео человека: готовые ролики EsAI (дубли
видеостудии, сцены и мультфильмы мультстудии, видео чата) и загруженные им
самим файлы (MergeUpload, Build MU: до 90 МБ и 60 с, хранятся 30 дней).

Деньги — как в видеостудии: при запуске цена встаёт в резерв (credits_reserved
у строки в очереди или в работе), списание — только за готовый ролик, сбой
снимает резерв тем же UPDATE, что закрывает склейку. Все переходы — условные
UPDATE: вторая копия задачи или уборка не спишут и не закроют второй раз.

Звук (Build MA) — MergeAudio: голос за кадром и фоновая музыка склейки, тем же
правилом денег (резерв строки → списание только за готовый звук).
"""
from __future__ import annotations

import uuid
from datetime import timedelta

from django.conf import settings
from django.core.files.storage import default_storage
from django.db import models
from django.db.models import Q
from django.utils import timezone

from .config import (ASPECTS, AUDIO_RETENTION_DAYS, CLIP_KEEP, CLIP_OFF, CLIP_QUIET, FIT_PAD, FITS,
                     MUSIC_VOLUME_DEFAULT, UPLOAD_RETENTION_DAYS, VOICE_VOLUME_DEFAULT)

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
    CLIP_SOUND_CHOICES = [(CLIP_KEEP, "Оставить"), (CLIP_QUIET, "Тише"), (CLIP_OFF, "Выключить")]

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
    # Звук (Build MA): что делать со звуком самих роликов и громкости дорожек
    # MergeAudio. Сводится при склейке; оставить звук без дорожек — прежняя склейка.
    clip_sound = models.CharField(max_length=5, choices=CLIP_SOUND_CHOICES, default=CLIP_KEEP,
                                  verbose_name="Звук роликов")
    music_volume = models.FloatField(default=MUSIC_VOLUME_DEFAULT, verbose_name="Громкость музыки")
    voice_volume = models.FloatField(default=VOICE_VOLUME_DEFAULT, verbose_name="Громкость голоса")
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


def _audio_expiry():
    return timezone.now() + timedelta(days=AUDIO_RETENTION_DAYS)


class MergeAudio(models.Model):
    """Звуковая дорожка склейки: голос за кадром или фоновая музыка (Build MA).

    Голос и созданная музыка оплачиваются только готовыми: пока звук делается,
    его цена — резерв строки (credits_reserved при pending), готово — списание
    в той же транзакции, что делает строку ready; сбой снимает резерв тем же
    UPDATE, что пишет failed. У склейки не больше одной готовой дорожки каждого
    вида: новая заменяет прежнюю (строку и файл).
    """

    KIND_VOICE = "voice"
    KIND_MUSIC = "music"
    KIND_CHOICES = [(KIND_VOICE, "Голос за кадром"), (KIND_MUSIC, "Музыка")]
    SOURCE_GENERATED = "generated"
    SOURCE_UPLOAD = "upload"
    SOURCE_CHOICES = [(SOURCE_GENERATED, "Создано"), (SOURCE_UPLOAD, "Свой трек")]
    STATUS_PENDING = "pending"
    STATUS_READY = "ready"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [(STATUS_PENDING, "Делается"), (STATUS_READY, "Готово"),
                      (STATUS_FAILED, "Не получилось")]

    # Публичный идентификатор: чужая дорожка неотличима от несуществующей.
    uid = models.CharField(max_length=32, unique=True, default=_uid, editable=False)
    project = models.ForeignKey(MergeProject, on_delete=models.CASCADE, related_name="audio_tracks",
                                verbose_name="Склейка")
    kind = models.CharField(max_length=5, choices=KIND_CHOICES, verbose_name="Вид")
    source = models.CharField(max_length=9, choices=SOURCE_CHOICES, default=SOURCE_GENERATED,
                              verbose_name="Откуда")
    status = models.CharField(max_length=7, choices=STATUS_CHOICES, default=STATUS_PENDING,
                              db_index=True, verbose_name="Состояние")
    # mp3 в default_storage (save_audio мультстудии): merge/audio/<user_id>/<uuid>.mp3.
    file = models.CharField(max_length=512, blank=True, default="", verbose_name="Файл")
    duration_s = models.FloatField(null=True, blank=True, verbose_name="Длительность, с")
    text = models.TextField(blank=True, default="", verbose_name="Текст голоса")
    prompt = models.CharField(max_length=400, blank=True, default="", verbose_name="Описание музыки")
    # Подпись своего трека — имя файла без папок и расширения.
    title = models.CharField(max_length=80, blank=True, default="", verbose_name="Название трека")
    voice_id = models.CharField(max_length=64, blank=True, default="", verbose_name="Голос")
    voice_name = models.CharField(max_length=120, blank=True, default="", verbose_name="Имя голоса")
    # С какого фрагмента (номер с 0) звучит голос; 0 — с начала склейки.
    start_fragment = models.PositiveSmallIntegerField(default=0, verbose_name="С фрагмента")
    # Сколько секунд музыки заказано (длина склейки на момент заказа).
    seconds = models.FloatField(null=True, blank=True, verbose_name="Заказано секунд")
    credits_reserved = models.PositiveIntegerField(default=0, verbose_name="В резерве, кр")
    credits_charged = models.PositiveIntegerField(default=0, verbose_name="Списано, кр")
    error = models.CharField(max_length=300, blank=True, default="", verbose_name="Ошибка")
    error_code = models.CharField(max_length=40, blank=True, default="", verbose_name="Код ошибки")
    # Ключ клика: повтор того же запроса (сеть, двойная отправка) отвечает той же
    # дорожкой и второй раз не платится.
    request_id = models.CharField(max_length=64, blank=True, default="", verbose_name="Ключ запроса")
    # Задача музыки взяла работу: вторая копия задачи провайдера не зовёт.
    started_at = models.DateTimeField(null=True, blank=True, verbose_name="Начато")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Создано")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Изменено")
    # 30 дней; склейка, в которую дорожка вошла, продлевает её до своего срока.
    expires_at = models.DateTimeField(default=_audio_expiry, db_index=True, verbose_name="Хранится до")

    class Meta:
        verbose_name = "Звук склейки"
        verbose_name_plural = "Звук склеек"
        constraints = [
            # Резерв — только у дорожки, которая делается.
            models.CheckConstraint(name="merge_audio_reserve_only_pending",
                                   condition=Q(status="pending") | Q(credits_reserved=0)),
            # Один голос и одна музыка на склейку; и не больше одной в работе на вид:
            # второй клик или вторая вкладка не закажут (и не оплатят) звук дважды.
            models.UniqueConstraint(fields=["project", "kind"], condition=Q(status="ready"),
                                    name="merge_audio_one_ready"),
            models.UniqueConstraint(fields=["project", "kind"], condition=Q(status="pending"),
                                    name="merge_audio_one_pending"),
        ]
        indexes = [models.Index(fields=["status", "created_at"], name="merge_audio_status")]

    def __str__(self):
        return f"{self.get_kind_display()} {self.uid[:8]}"


class MergeAudioRequest(models.Model):
    """Ключ заказа звука, чья дорожка ушла: её заменил новый звук того же вида, свой трек
    или её убрали (MA_FIX6-REFIX1).

    Ключ живёт в строке дорожки, а замена строку стирает. Вкладка, у которой ответ на
    заказ не дошёл, повторяет его тем же ключом — и без этой памяти сервер заказал бы
    и списал звук второй раз. Здесь — каким заказ был, когда ушёл (track_json без файла):
    повтор отвечает 200 этим снимком и текущим звуком склейки, ничего не заказывая.
    Хранится столько же, сколько звук (уборка purge).
    """

    project = models.ForeignKey(MergeProject, on_delete=models.CASCADE, related_name="audio_requests",
                                verbose_name="Склейка")
    kind = models.CharField(max_length=5, choices=MergeAudio.KIND_CHOICES, verbose_name="Вид")
    request_id = models.CharField(max_length=64, verbose_name="Ключ запроса")
    track = models.JSONField(default=dict, verbose_name="Дорожка, когда ушла")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name="Ушла")

    class Meta:
        verbose_name = "Ключ ушедшего заказа звука"
        verbose_name_plural = "Ключи ушедших заказов звука"
        constraints = [
            models.UniqueConstraint(fields=["project", "kind", "request_id"], name="merge_audio_request_once"),
        ]

    def __str__(self):
        return f"{self.kind} {self.request_id}"


__all__ = ["MergeProject", "MergeUpload", "MergeAudio", "MergeAudioRequest", "ACTIVE", "EDITABLE", "DELETABLE",
           "FITS"]
