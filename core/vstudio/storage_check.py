"""Примет ли хранилище результат дубля — проверка ДО платного запроса провайдеру.

09.10.2026 провайдер снял два ролика и взял за них деньги, а выдача пять раз
подряд упала на «Permission denied»: каталог vstudio/<user_id>/ создал core
(root, права 755), а пишет в него воркер студии (appuser). Ролики пропали.

Поэтому воркер перед отправкой сам делает то, что потом сделает выдача: создаёт
каталог человека, если его нет, кладёт в него файл и стирает. Не вышло — дубль
закрывается без обращения к провайдеру (pipeline.submit и pipeline.run_image),
так же, как при недоступном журнале.

Проба идёт в то же хранилище и в тот же каталог, что и выдача (assets.user_dir):
на локальном диске — напрямую через ОС, в любом другом хранилище — его же save
и delete.

На локальном диске после пробы смотрим ещё и свободное место (MIN_FREE_BYTES):
четыре пробных байта запишутся и на почти полный диск, а ролик — уже нет.
"""
from __future__ import annotations

import logging
import os
import shutil
import tempfile
import uuid

from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage, default_storage

from .assets import make_dirs, user_dir

logger = logging.getLogger(__name__)

PROBE = b"esai"
MB = 1024 * 1024
# Меньше этого на диске media или во временном каталоге — платный запрос не
# отправляем. Ролик при выдаче лежит на диске дважды (временный файл и копия в
# media), а воркер студии выдаёт до четырёх роликов разом
# (CELERY_VSTUDIO_CONCURRENCY): 1 ГБ — это 4 × 2 × 128 МБ, обычный ролик весит
# десятки мегабайт. Порог сужает окно, а не закрывает его: ролик приходит через
# минуты после проверки. Кончится место за это время — остаются повторы выдачи
# и «Довезти». Картинкам порог тот же: диск с таким остатком чинят в любом
# случае, а второе число пришлось бы помнить.
MIN_FREE_BYTES = 1024 * MB


def _why(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"


def _probe_name() -> str:
    # Случайный хвост — пробы двух воркеров не встретятся; по имени с точкой
    # видно, что это не материал человека, если процесс убили посреди пробы.
    return f".probe-{uuid.uuid4().hex}"


def storage_path(user_id) -> str:
    """Куда ляжет результат человека — для лога: путь на диске или имя в хранилище."""
    name = user_dir(user_id)
    try:
        return default_storage.path(name)
    except Exception:
        return name


def _probe_disk(directory: str, mode) -> tuple[bool, str]:
    try:
        make_dirs(directory, mode)
    except OSError as exc:
        return False, f"каталог не создаётся: {_why(exc)}"
    path = os.path.join(directory, _probe_name())
    try:
        # 0600: файл лежит под /media/, отдавать его наружу незачем.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
                     0o600)
    except OSError as exc:
        return False, f"файл не создаётся: {_why(exc)}"
    reason = ""
    try:
        try:
            os.write(fd, PROBE)
        finally:
            os.close(fd)
    except OSError as exc:
        # Сюда приходит и полный диск: место под данные занимается при записи.
        reason = f"файл не пишется: {_why(exc)}"
    finally:
        try:
            os.remove(path)
        except OSError as exc:
            # Создать смогли, а стереть нет — с таким каталогом выдача не уберёт
            # за собой и проигравшую гонку: считаем хранилище неготовым.
            logger.error("vstudio: проба хранилища не удалилась: %s (%s)", path, _why(exc))
            reason = reason or f"пробный файл не удаляется: {_why(exc)}"
    return not reason, reason


def _free_bytes(path: str) -> int:
    # На POSIX это место, доступное не-root: столько и достанется воркеру.
    return shutil.disk_usage(path).free


def _low_space(directory: str) -> str:
    """Причина отказа, если места меньше MIN_FREE_BYTES; хватает — пустая строка.

    Смотрим оба места, куда ляжет ролик: каталог человека и временный каталог,
    в который выдача его скачивает (delivery.fetch_video, tempfile.mkstemp).
    """
    try:
        for path in (directory, tempfile.gettempdir()):
            free = _free_bytes(path)
            if free < MIN_FREE_BYTES:
                return (f"мало места: {free // MB} МБ свободно в {path}, "
                        f"нужно {MIN_FREE_BYTES // MB} МБ")
    except OSError as exc:
        # Не знаем, сколько места, — не знаем и влезет ли оплаченный ролик.
        return f"свободное место не измеряется: {_why(exc)}"
    return ""


def _probe_storage(directory: str) -> tuple[bool, str]:
    wanted = f"{directory}/{_probe_name()}"
    name = ""
    reason = ""
    try:
        name = default_storage.save(wanted, ContentFile(PROBE))
    except Exception as exc:
        reason = f"файл не пишется: {_why(exc)}"
    finally:
        try:
            # Запись могла оборваться на полпути — стираем и то, что не дописалось.
            default_storage.delete(name or wanted)
        except Exception as exc:
            if name:
                logger.error("vstudio: проба хранилища не удалилась: %s (%s)", name, _why(exc))
            reason = reason or f"пробный файл не удаляется: {_why(exc)}"
    return not reason, reason


def storage_ready(user_id) -> tuple[bool, str]:
    """(True, "") — этот процесс сохранит результат человека; иначе (False, причина).

    Никогда не бросает. После себя оставляет только каталог человека: он нужен
    выдаче, а стирать его нельзя — рядом может идти сохранение другого процесса.
    """
    try:
        directory = user_dir(user_id)
        if isinstance(default_storage, FileSystemStorage):
            path = default_storage.path(directory)
            ok, reason = _probe_disk(path, default_storage.directory_permissions_mode)
            if ok:
                # После пробы: каталог уже есть, место в нём можно измерить.
                reason = _low_space(path)
            return not reason, reason
        return _probe_storage(directory)
    except Exception as exc:
        logger.exception("vstudio: проверка хранилища упала user=%s", user_id)
        return False, _why(exc)


__all__ = ["storage_ready", "storage_path", "PROBE", "MIN_FREE_BYTES"]
