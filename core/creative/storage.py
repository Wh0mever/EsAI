"""Файлы Creative Studio в default_storage.

  creative/uploads/<user_id>/<uid>.<ext>      загрузки людей (+ <uid>_t.jpg превью)
  creative/<user_id>/<job_uid>/<n>.<ext>      результаты (+ <n>_t.jpg превью/кадр)
  creative/catalog/<kind>/<hash>.<ext>        превью каталогов (копии с сервера поставщика)

Имена файлов нейтральные (номер результата), без имени поставщика и модели.
Каталоги заводятся через vstudio.assets.make_dirs (права chmod, а не umask:
core работает от root, воркер — appuser, урок 09.10.2026).
"""
from __future__ import annotations

import logging

from django.core.files.storage import FileSystemStorage, default_storage

logger = logging.getLogger(__name__)

ROOT = "creative"


def uploads_dir(user_id) -> str:
    return f"{ROOT}/uploads/{user_id}"


def results_dir(user_id, job_uid: str) -> str:
    return f"{ROOT}/{user_id}/{job_uid}"


def catalog_dir(kind: str) -> str:
    return f"{ROOT}/catalog/{kind}"


def ensure_dir(name: str) -> None:
    """Завести каталог в default_storage с правами через chmod. Не бросает."""
    if not isinstance(default_storage, FileSystemStorage):
        return
    try:
        from vstudio.assets import make_dirs

        make_dirs(default_storage.path(name), default_storage.directory_permissions_mode)
    except Exception:
        logger.warning("creative: каталог %s не создан заранее", name, exc_info=True)


def delete_files(*paths: str) -> None:
    """Стереть файлы, не падая: зовётся из отката и у проигравшего гонку."""
    for path in paths:
        if not path:
            continue
        try:
            default_storage.delete(path)
        except Exception:
            logger.warning("creative: не удалось удалить %s", path, exc_info=True)


def storage_ready(user_id) -> tuple[bool, str]:
    """Сохранит ли этот процесс результат человека: проба записи и свободное место.

    Те же проверки, что у видеостудии (vstudio.storage_check), но в каталоге
    Creative Studio. Никогда не бросает.
    """
    try:
        from django.core.files.base import ContentFile

        from vstudio import storage_check as sc

        directory = f"{ROOT}/{user_id}"
        if isinstance(default_storage, FileSystemStorage):
            path = default_storage.path(directory)
            ok, reason = sc._probe_disk(path, default_storage.directory_permissions_mode)
            if ok:
                reason = sc._low_space(path)
            return not reason, reason
        name = default_storage.save(f"{directory}/{sc._probe_name()}", ContentFile(sc.PROBE))
        default_storage.delete(name)
        return True, ""
    except Exception as exc:
        logger.exception("creative: проверка хранилища упала user=%s", user_id)
        return False, f"{type(exc).__name__}: {exc}"


__all__ = ["uploads_dir", "results_dir", "catalog_dir", "ensure_dir", "delete_files",
           "storage_ready", "ROOT"]
