"""Куда ложится склейка и примет ли её хранилище.

Каталог merge/<user_id>/ создаёт core (root, gunicorn) при запуске, а пишет в
него воркер media (appuser). 09.10.2026 ровно на этом видеостудия потеряла два
оплаченных ролика: каталог с правами 755 от root. Поэтому каталог создаётся
через make_dirs видеостудии (chmod по FILE_UPLOAD_DIRECTORY_PERMISSIONS, а не
umask процесса), и проба перед резервом — та же, что у студии: создать каталог,
записать и стереть файл, проверить свободное место (≥ 1 ГБ).
"""
from __future__ import annotations

import logging
import os

from django.core.files.storage import FileSystemStorage, default_storage

logger = logging.getLogger(__name__)


def user_dir(user_id) -> str:
    return f"merge/{user_id}"


def ensure_user_dir(user_id) -> None:
    """Завести каталог человека с правильными правами. Не бросает."""
    if not isinstance(default_storage, FileSystemStorage):
        return
    from vstudio.assets import make_dirs

    try:
        make_dirs(default_storage.path(user_dir(user_id)), default_storage.directory_permissions_mode)
    except Exception:
        logger.warning("склейка: каталог %s не создан заранее", user_dir(user_id), exc_info=True)


def storage_ready(user_id) -> tuple[bool, str]:
    """(True, "") — результат человека ляжет; иначе (False, причина для лога).

    Проба — функциями storage_check видеостудии, чтобы правило «каталог, файл,
    место» было одно на оба приложения. Никогда не бросает.
    """
    from vstudio import storage_check

    try:
        directory = user_dir(user_id)
        if isinstance(default_storage, FileSystemStorage):
            path = default_storage.path(directory)
            ok, reason = storage_check._probe_disk(path, default_storage.directory_permissions_mode)
            if ok:
                reason = storage_check._low_space(path)
            return not reason, reason
        return storage_check._probe_storage(directory)
    except Exception as exc:
        logger.exception("склейка: проверка хранилища упала user=%s", user_id)
        return False, f"{type(exc).__name__}: {exc}"


def result_names(user_id, project_uid: str, token: str) -> tuple[str, str]:
    """Имена ролика и обложки: свой хвост у каждого запуска — повторная склейка
    не перезапишет файл, который, может быть, ещё скачивают."""
    base = f"{user_dir(user_id)}/{project_uid}-{token}"
    return f"{base}.mp4", f"{base}.jpg"


def save_file(name: str, path: str) -> str:
    """Положить готовый файл в хранилище потоком (без чтения в память)."""
    from django.core.files import File

    # Диск кончился посреди записи — недописанный файл остался бы сиротой: его
    # имя до вызывающего не доходит. Чужое (уже лежавшее под этим именем) не трогаем.
    try:
        existed = default_storage.exists(name)
    except Exception:
        existed = True
    try:
        with open(path, "rb") as fh:
            return default_storage.save(name, File(fh, name=os.path.basename(name)))
    except Exception:
        if not existed:
            delete_files(name)
        raise


def delete_files(*names: str) -> None:
    for name in names:
        if not name:
            continue
        try:
            default_storage.delete(name)
        except Exception:
            logger.warning("склейка: не удалось удалить %s", name, exc_info=True)


__all__ = ["user_dir", "ensure_user_dir", "storage_ready", "result_names", "save_file",
           "delete_files"]
