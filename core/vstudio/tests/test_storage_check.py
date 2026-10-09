"""Проба хранилища перед платным запросом (инцидент 09.10.2026).

Провайдер снял два ролика и взял за них деньги, а выдача упала на правах
каталога: vstudio/<user_id>/ создал core от root, писал в него воркер от
appuser. Здесь проверяется обе половины исправления:

- настройки: новые каталоги media открыты обоим пользователям контейнеров,
  а общий файл журнала не мешает процессу стартовать;
- проба storage_check.storage_ready — что она видит отказ ОС и хранилища,
  нехватку места, ничего после себя не оставляет и никогда не бросает;
- загрузка фото: каталог человека создаётся заранее и открывается через chmod,
  а не через umask процесса;
- конвейер: проба не прошла — провайдер НЕ вызывается, дубль закрыт без
  списания; прошла — всё идёт как раньше.

Права каталогов есть только на POSIX: такие тесты на Windows пропускаются и
идут на сервере.
"""
import errno
import logging
import os
import stat
import tempfile
from types import SimpleNamespace
from unittest import mock, skipIf

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import InMemoryStorage, default_storage
from django.db import OperationalError
from django.test import SimpleTestCase, override_settings
from django.utils import timezone
from django.utils.module_loading import import_string

from ai import media_provider as mp
from ai.models import GenerationLog
from users.models import Notification
from vstudio import delivery, pipeline, storage_check
from vstudio.assets import AssetError, asset_paths, store_image_bytes, user_dir
from vstudio.models import Take
from vstudio.tests import factories as f
from vstudio.tests.test_pipeline import PipelineCase, accepted, png_b64, ready, write_mp4

DENIED = "каталог не создаётся: PermissionError: [Errno 13] Permission denied: '/app/media/vstudio/49'"
IN_MEMORY = {"default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
             "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}}
IS_ROOT = getattr(os, "geteuid", lambda: -1)() == 0
MB = storage_check.MB
ROOMY = 10 * storage_check.MIN_FREE_BYTES


def denied(path="/app/media/vstudio/49"):
    return PermissionError(errno.EACCES, "Permission denied", path)


def disk_full():
    return OSError(errno.ENOSPC, "No space left on device")


def same_path(a, b) -> bool:
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def roomy(case):
    """Места «с запасом», сколько бы его ни было на машине, где идут тесты.

    Порог свободного места проверяют свои тесты (FreeSpaceTests и конвейер);
    остальные не должны зависеть от диска разработчика или сервера.
    """
    return case.enterContext(mock.patch("vstudio.storage_check._free_bytes", return_value=ROOMY))


# ---------------------------------------------------------------- настройки

class SettingsTests(SimpleTestCase):
    def test_new_media_directories_are_open_to_both_container_users(self):
        self.assertEqual(settings.FILE_UPLOAD_DIRECTORY_PERMISSIONS, 0o777)
        self.assertEqual(default_storage.directory_permissions_mode, 0o777)

    def test_files_stay_readable_but_not_writable_by_others(self):
        self.assertEqual(settings.FILE_UPLOAD_PERMISSIONS, 0o644)
        self.assertEqual(default_storage.file_permissions_mode, 0o644)

    def test_storage_asks_the_os_for_open_directories_on_every_save(self):
        # Идёт и на Windows: сами права там не проверить, но видно, что хранилище
        # просит у ОС 777 для всех недостающих каталогов (umask 0 на время
        # makedirs) и возвращает umask процесса на место.
        self.enterContext(f.media_root())
        calls = []
        real_makedirs = os.makedirs

        def umask(mask):
            calls.append(("umask", mask))
            return 0o022

        def makedirs(name, mode=0o777, exist_ok=False):
            calls.append(("makedirs", mode, exist_ok))
            return real_makedirs(name, mode, exist_ok=exist_ok)

        with mock.patch("django.core.files.storage.filesystem.os.umask", side_effect=umask), \
                mock.patch("django.core.files.storage.filesystem.os.makedirs", side_effect=makedirs):
            default_storage.save("vstudio/49/clip.mp4", ContentFile(b"mp4"))
        self.assertEqual((calls[0], calls[-1]), (("umask", 0), ("umask", 0o022)))
        # Между ними — только создание каталогов (makedirs зовёт себя и для верхних).
        self.assertEqual(set(calls[1:-1]), {("makedirs", 0o777, True)})

    def log_handler(self, filename):
        # Так же обработчик собирает logging.config.dictConfig внутри django.setup().
        conf = dict(settings.LOGGING["handlers"]["file"], filename=filename)
        cls = import_string(conf.pop("class"))
        for key in ("level", "formatter"):
            conf.pop(key)
        handler = cls(**conf)
        self.addCleanup(handler.close)
        return handler

    def warning(self, text="строка журнала"):
        return logging.makeLogRecord({"name": "django", "levelno": logging.WARNING,
                                      "levelname": "WARNING", "msg": text})

    def test_log_file_that_cannot_be_opened_does_not_stop_the_process_from_starting(self):
        # django.log после ротации, сделанной core, принадлежит root, и воркер
        # (appuser) открыть его не может. Здесь файл лежит в каталоге, которого
        # нет: ОС отказывает в открытии так же, и тест идёт на любой системе.
        media = self.enterContext(f.media_root())
        handler = self.log_handler(os.path.join(media, "нет", "django.log"))
        record = self.warning()
        with mock.patch.object(handler, "handleError") as failed:
            handler.handle(record)
        # Запись не удалась — это забота самого журнала, а не падение процесса.
        failed.assert_called_once_with(record)

    def test_log_file_is_opened_by_the_first_record_and_written_as_before(self):
        media = self.enterContext(f.media_root())
        path = os.path.join(media, "django.log")
        handler = self.log_handler(path)
        self.assertFalse(os.path.exists(path))
        handler.handle(self.warning("ролик не сохранён"))
        handler.close()
        with open(path, encoding="utf-8") as fh:
            self.assertIn("ролик не сохранён", fh.read())


# ---------------------------------------------------------------- проба: локальный диск

class DiskProbeTests(SimpleTestCase):
    USER = 49

    def setUp(self):
        self.media = self.enterContext(f.media_root())
        self.dir = os.path.join(self.media, "vstudio", str(self.USER))
        roomy(self)

    def files(self):
        out = []
        for root, _dirs, names in os.walk(self.media):
            out += [os.path.join(root, name) for name in names]
        return out

    def test_ready_on_a_fresh_media_root_and_leaves_only_the_directory(self):
        self.assertEqual(storage_check.storage_ready(self.USER), (True, ""))
        self.assertTrue(os.path.isdir(self.dir))
        self.assertEqual(self.files(), [])

    def test_ready_next_to_existing_files_and_does_not_touch_them(self):
        name = default_storage.save(f"{user_dir(self.USER)}/photo.jpg", ContentFile(b"jpeg"))
        self.assertEqual(storage_check.storage_ready(self.USER), (True, ""))
        self.assertEqual(storage_check.storage_ready(self.USER), (True, ""))
        self.assertEqual(os.listdir(self.dir), ["photo.jpg"])
        with default_storage.open(name, "rb") as fh:
            self.assertEqual(fh.read(), b"jpeg")

    def test_probes_the_directory_uploads_and_delivery_write_to(self):
        self.assertTrue(same_path(storage_check.storage_path(self.USER), self.dir))
        file_path, thumb_path = asset_paths(self.USER, "a" * 32, "jpg")
        for path in (file_path, thumb_path):
            self.assertEqual(path.rsplit("/", 1)[0], user_dir(self.USER))
        stored = store_image_bytes(self.USER, "b" * 32, f.image_bytes(640, 480))
        self.assertTrue(same_path(os.path.dirname(default_storage.path(stored.file)), self.dir))

    def test_directory_that_cannot_be_created_is_not_ready(self):
        # Сам инцидент: vstudio/ создал root, воркеру не дают сделать в нём каталог.
        with mock.patch("vstudio.storage_check.os.mkdir", side_effect=denied()) as mkdir:
            ok, reason = storage_check.storage_ready(self.USER)
        self.assertFalse(ok)
        mkdir.assert_called()
        self.assertTrue(reason.startswith("каталог не создаётся: PermissionError"), reason)
        self.assertIn("Permission denied", reason)
        self.assertEqual(self.files(), [])

    def test_directory_created_by_another_process_meanwhile_is_fine(self):
        real = os.mkdir

        def raced(path, *args, **kwargs):
            real(path, *args, **kwargs)
            raise FileExistsError(errno.EEXIST, "File exists", path)

        with mock.patch("vstudio.storage_check.os.mkdir", side_effect=raced), \
                mock.patch("vstudio.storage_check.os.chmod") as chmod:
            self.assertEqual(storage_check.storage_ready(self.USER), (True, ""))
        # Чужому каталогу права не меняем: его владелец выставил их сам.
        chmod.assert_not_called()
        self.assertEqual(self.files(), [])

    def test_only_directories_created_here_get_the_mode(self):
        os.makedirs(os.path.join(self.media, "vstudio"))
        with mock.patch("vstudio.storage_check.os.chmod") as chmod:
            self.assertEqual(storage_check.storage_ready(self.USER), (True, ""))
        chmod.assert_called_once()
        path, mode = chmod.call_args.args
        self.assertTrue(same_path(path, self.dir), path)
        self.assertEqual(mode, 0o777)
        with mock.patch("vstudio.storage_check.os.chmod") as chmod:
            self.assertEqual(storage_check.storage_ready(self.USER), (True, ""))
        chmod.assert_not_called()

    def test_file_that_cannot_be_created_is_not_ready(self):
        # Второе лицо инцидента: каталог человека есть (root, 755), писать в него нельзя.
        os.makedirs(self.dir)
        with mock.patch("vstudio.storage_check.os.open", side_effect=denied(self.dir)):
            ok, reason = storage_check.storage_ready(self.USER)
        self.assertFalse(ok)
        self.assertTrue(reason.startswith("файл не создаётся: PermissionError"), reason)
        self.assertEqual(self.files(), [])

    def test_full_disk_is_not_ready_and_the_probe_file_is_removed(self):
        with mock.patch("vstudio.storage_check.os.write", side_effect=disk_full()) as write:
            ok, reason = storage_check.storage_ready(self.USER)
        self.assertFalse(ok)
        write.assert_called_once()
        self.assertTrue(reason.startswith("файл не пишется: OSError"), reason)
        self.assertIn("No space left on device", reason)
        self.assertEqual(self.files(), [])

    def test_error_on_close_is_a_write_failure_too(self):
        real = os.close

        def close(fd):
            real(fd)
            raise disk_full()

        with mock.patch("vstudio.storage_check.os.close", side_effect=close):
            ok, reason = storage_check.storage_ready(self.USER)
        self.assertFalse(ok)
        self.assertTrue(reason.startswith("файл не пишется"), reason)
        self.assertEqual(self.files(), [])

    def test_probe_that_cannot_be_deleted_is_not_ready_and_logged(self):
        with mock.patch("vstudio.storage_check.os.remove", side_effect=denied(self.dir)) as remove, \
                self.assertLogs("vstudio.storage_check", "ERROR") as logs:
            ok, reason = storage_check.storage_ready(self.USER)
        self.assertFalse(ok)
        self.assertTrue(reason.startswith("пробный файл не удаляется: PermissionError"), reason)
        left = remove.call_args.args[0]
        self.assertTrue(same_path(os.path.dirname(left), self.dir))
        self.assertTrue(any(left in line for line in logs.output), logs.output)

    def test_write_failure_wins_over_delete_failure_in_the_reason(self):
        with mock.patch("vstudio.storage_check.os.write", side_effect=disk_full()), \
                mock.patch("vstudio.storage_check.os.remove", side_effect=denied(self.dir)), \
                self.assertLogs("vstudio.storage_check", "ERROR"):
            ok, reason = storage_check.storage_ready(self.USER)
        self.assertFalse(ok)
        self.assertTrue(reason.startswith("файл не пишется"), reason)

    def test_probe_file_is_removed_even_when_the_worker_is_interrupted(self):
        with mock.patch("vstudio.storage_check.os.write", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                storage_check.storage_ready(self.USER)
        self.assertEqual(self.files(), [])

    def test_probe_names_are_unique_and_recognisable(self):
        first, second = storage_check._probe_name(), storage_check._probe_name()
        self.assertNotEqual(first, second)
        self.assertTrue(first.startswith(".probe-"))

    def test_never_raises(self):
        with mock.patch("vstudio.storage_check.user_dir", side_effect=RuntimeError("boom")), \
                self.assertLogs("vstudio.storage_check", "ERROR"):
            self.assertEqual(storage_check.storage_ready(self.USER), (False, "RuntimeError: boom"))
        # Имя, выходящее из media, отвергает само хранилище — тоже без исключения.
        with self.assertLogs("vstudio.storage_check", "ERROR"):
            ok, reason = storage_check.storage_ready("../../etc")
        self.assertFalse(ok)
        self.assertIn("SuspiciousFileOperation", reason)


# ---------------------------------------------------------------- проба: свободное место

class FreeSpaceTests(SimpleTestCase):
    """Пробные 4 байта запишутся и на почти полный диск, а оплаченный ролик — нет."""

    USER = 49

    def setUp(self):
        self.media = self.enterContext(f.media_root())
        self.dir = os.path.join(self.media, "vstudio", str(self.USER))
        self.tmp = tempfile.gettempdir()

    def space(self, media=ROOMY, tmp=ROOMY):
        """Подменить свободное место в каталоге человека и во временном каталоге."""
        measured = []

        def free(path):
            measured.append(path)
            if same_path(path, self.dir):
                return media
            if same_path(path, self.tmp):
                return tmp
            raise AssertionError(f"мерили не то место: {path}")

        self.enterContext(mock.patch("vstudio.storage_check._free_bytes", side_effect=free))
        return measured

    def files(self):
        out = []
        for root, _dirs, names in os.walk(self.media):
            out += [os.path.join(root, name) for name in names]
        return out

    def test_ready_when_both_places_have_room(self):
        measured = self.space()
        self.assertEqual(storage_check.storage_ready(self.USER), (True, ""))
        # Оба места, где ляжет ролик: каталог человека и каталог скачивания.
        self.assertEqual(len(measured), 2, measured)
        self.assertTrue(same_path(measured[0], self.dir), measured)
        self.assertTrue(same_path(measured[1], self.tmp), measured)

    def test_exactly_the_floor_is_enough(self):
        self.space(media=storage_check.MIN_FREE_BYTES, tmp=storage_check.MIN_FREE_BYTES)
        self.assertEqual(storage_check.storage_ready(self.USER), (True, ""))

    def test_low_space_in_media_is_not_ready(self):
        self.space(media=412 * MB + 5)
        ok, reason = storage_check.storage_ready(self.USER)
        self.assertFalse(ok)
        # Числа и место — чтобы по строке журнала было ясно, что и где чистить.
        self.assertEqual(reason, f"мало места: 412 МБ свободно в "
                                 f"{storage_check.storage_path(self.USER)}, нужно 1024 МБ")
        self.assertEqual(self.files(), [])

    def test_low_space_where_the_clip_is_downloaded_is_not_ready(self):
        self.space(tmp=storage_check.MIN_FREE_BYTES - 1)
        ok, reason = storage_check.storage_ready(self.USER)
        self.assertFalse(ok)
        self.assertEqual(reason, f"мало места: 1023 МБ свободно в {self.tmp}, нужно 1024 МБ")
        self.assertEqual(self.files(), [])

    def test_delivery_downloads_into_the_measured_directory(self):
        # Если выдача начнёт скачивать в другое место, мерить надо будет его.
        seen = {}

        def download(url, dest, **kw):
            seen["dest"] = dest
            return write_mp4(url, dest, **kw)

        take = SimpleNamespace(uid="t" * 32, user_id=self.USER)
        with mock.patch("ai.media_provider.download_to_file", side_effect=download), \
                mock.patch("ai.video_edit.probe_video", return_value={}), \
                mock.patch("ai.video_edit.extract_poster", return_value=None):
            saved = delivery.fetch_video(take, "https://openrouter.ai/api/v1/videos/gen-1/content")
        self.assertTrue(same_path(os.path.dirname(seen["dest"]), self.tmp), seen)
        self.assertTrue(same_path(os.path.dirname(default_storage.path(saved.file)), self.dir))

    def test_floor_is_compared_with_the_free_space_the_os_reports(self):
        with mock.patch("vstudio.storage_check.shutil.disk_usage",
                        return_value=SimpleNamespace(total=ROOMY, used=ROOMY - MB, free=MB)) as usage:
            ok, reason = storage_check.storage_ready(self.USER)
        self.assertFalse(ok)
        self.assertTrue(reason.startswith("мало места: 1 МБ свободно в "), reason)
        self.assertTrue(same_path(usage.call_args.args[0], self.dir), usage.call_args)
        with mock.patch("vstudio.storage_check.shutil.disk_usage",
                        return_value=SimpleNamespace(total=ROOMY, used=0, free=ROOMY)):
            self.assertEqual(storage_check.storage_ready(self.USER), (True, ""))

    def test_space_that_cannot_be_measured_is_not_ready(self):
        # Не знаем, сколько места, — не знаем и влезет ли ролик: провайдеру не платим.
        with mock.patch("vstudio.storage_check._free_bytes",
                        side_effect=OSError(errno.EIO, "Input/output error")):
            ok, reason = storage_check.storage_ready(self.USER)
        self.assertFalse(ok)
        self.assertTrue(reason.startswith("свободное место не измеряется: OSError"), reason)
        self.assertEqual(self.files(), [])

    def test_failed_probe_is_reported_and_the_space_is_not_measured(self):
        measured = self.space(media=0, tmp=0)
        with mock.patch("vstudio.storage_check.os.mkdir", side_effect=denied()):
            ok, reason = storage_check.storage_ready(self.USER)
        self.assertFalse(ok)
        self.assertTrue(reason.startswith("каталог не создаётся"), reason)
        self.assertEqual(measured, [])


# ---------------------------------------------------------------- загрузка: каталог человека

class UploadDirectoryTests(SimpleTestCase):
    """Каталог человека первой загрузкой создаёт core — root в потоках gunicorn.

    umask у процесса один на все потоки, и FileSystemStorage, меняя его на
    время makedirs, может получить каталог с 755 (воркеру туда нельзя).
    Поэтому загрузка заводит каталог сама и права ставит через chmod.
    """

    USER = 49

    def setUp(self):
        self.media = self.enterContext(f.media_root())
        self.vstudio = os.path.join(self.media, "vstudio")
        self.dir = os.path.join(self.vstudio, str(self.USER))

    def test_directory_exists_before_the_storage_gets_to_create_it(self):
        seen = []
        real = os.makedirs

        def makedirs(name, mode=0o777, exist_ok=False):
            seen.append((name, os.path.isdir(name)))
            return real(name, mode, exist_ok=exist_ok)

        with mock.patch("django.core.files.storage.filesystem.os.makedirs", side_effect=makedirs):
            stored = store_image_bytes(self.USER, "d" * 32, f.image_bytes(640, 480))
        # По разу на файл и превью, и оба раза создавать хранилищу было нечего.
        self.assertEqual(len(seen), len(stored.paths), seen)
        for name, existed in seen:
            self.assertTrue(same_path(name, self.dir), name)
            self.assertTrue(existed, name)

    def test_new_directories_are_opened_by_chmod_when_the_umask_trick_is_lost(self):
        # Гонка потоков: umask(0), выставленный хранилищем на время makedirs,
        # соседний поток вернул к 022. Права здесь считаем сами, как их выдала
        # бы ОС, — тест идёт и на Windows; настоящие права — в DirectoryModeTests.
        modes = {}
        real_mkdir, real_chmod = os.mkdir, os.chmod

        def key(path):
            return os.path.normcase(os.path.abspath(path))

        def mkdir(path, mode=0o777, **kw):
            real_mkdir(path, mode, **kw)
            modes[key(path)] = mode & ~0o022

        def chmod(path, mode, **kw):
            real_chmod(path, mode, **kw)
            modes[key(path)] = mode

        with mock.patch("django.core.files.storage.filesystem.os.umask", return_value=0o022), \
                mock.patch("vstudio.assets.os.mkdir", side_effect=mkdir), \
                mock.patch("vstudio.assets.os.chmod", side_effect=chmod):
            stored = store_image_bytes(self.USER, "d" * 32, f.image_bytes(640, 480))
        self.assertEqual(modes[key(self.vstudio)], 0o777)
        self.assertEqual(modes[key(self.dir)], 0o777)
        for name in stored.paths:
            self.assertEqual(modes[key(default_storage.path(name))], 0o644)

    def test_refused_image_leaves_no_directory(self):
        with self.assertRaises(AssetError):
            store_image_bytes(self.USER, "e" * 32, b"not an image")
        self.assertEqual(os.listdir(self.media), [])

    def test_failure_to_prepare_the_directory_does_not_fail_the_upload(self):
        # Не вышло заранее — сохранение идёт как раньше и создаёт каталог само.
        with mock.patch("vstudio.assets.make_dirs", side_effect=denied(self.dir)) as prepare, \
                self.assertLogs("vstudio.assets", "WARNING") as logs:
            stored = store_image_bytes(self.USER, "f" * 32, f.image_bytes(640, 480))
        prepare.assert_called_once()
        path, mode = prepare.call_args.args
        self.assertTrue(same_path(path, self.dir), path)
        self.assertEqual(mode, 0o777)
        for name in stored.paths:
            self.assertTrue(default_storage.exists(name), name)
        self.assertTrue(any(user_dir(self.USER) in line for line in logs.output), logs.output)

    def test_refusal_of_the_os_reaches_the_caller_as_before(self):
        with mock.patch("vstudio.assets.os.mkdir", side_effect=denied(self.dir)), \
                self.assertLogs("vstudio.assets", "WARNING"):
            with self.assertRaises(PermissionError):
                store_image_bytes(self.USER, "a" * 32, f.image_bytes(640, 480))
        self.assertEqual(os.listdir(self.media), [])

    def test_storage_that_is_not_a_local_disk_is_left_alone(self):
        # path() есть и у хранилища в памяти — на диске из-за него ничего не появляется.
        with override_settings(STORAGES=IN_MEMORY), \
                mock.patch("vstudio.assets.make_dirs") as prepare:
            stored = store_image_bytes(self.USER, "b" * 32, f.image_bytes(640, 480))
            self.assertTrue(default_storage.exists(stored.file))
        prepare.assert_not_called()
        self.assertEqual(os.listdir(self.media), [])


# ---------------------------------------------------------------- проба: права (POSIX)

@skipIf(os.name == "nt", "права каталогов есть только на POSIX — тест идёт на сервере")
class DirectoryModeTests(SimpleTestCase):
    def setUp(self):
        self.media = self.enterContext(f.media_root())
        # Как у процессов в контейнерах: без настройки каталог вышел бы 755.
        self.addCleanup(os.umask, os.umask(0o022))
        roomy(self)

    def path(self, *parts):
        return os.path.join(self.media, *parts)

    def mode(self, *parts):
        return stat.S_IMODE(os.stat(self.path(*parts)).st_mode)

    def test_storage_save_opens_every_new_directory_and_keeps_the_file_read_only(self):
        name = default_storage.save("vstudio/49/deep/clip.mp4", ContentFile(b"mp4"))
        self.assertEqual(self.mode("vstudio"), 0o777)
        self.assertEqual(self.mode("vstudio", "49"), 0o777)
        self.assertEqual(self.mode("vstudio", "49", "deep"), 0o777)
        self.assertEqual(self.mode(*name.split("/")), 0o644)
        # umask процесса хранилище вернуло на место.
        current = os.umask(0o022)
        self.assertEqual(current, 0o022)

    def test_upload_path_of_the_studio_gets_the_same_modes(self):
        stored = store_image_bytes(49, "c" * 32, f.image_bytes(640, 480))
        self.assertEqual(self.mode("vstudio"), 0o777)
        self.assertEqual(self.mode("vstudio", "49"), 0o777)
        for name in stored.paths:
            self.assertEqual(self.mode(*name.split("/")), 0o644)

    def test_upload_directory_is_open_even_when_the_storage_loses_its_umask(self):
        # Гонка потоков gunicorn: пока хранилище создаёт каталог, соседний поток
        # вернул umask процесса к 022 — umask(0) хранилища как не было. Каталог
        # человека всё равно открыт воркеру: загрузка ставит права через chmod.
        with mock.patch("django.core.files.storage.filesystem.os.umask", return_value=0o022):
            stored = store_image_bytes(49, "d" * 32, f.image_bytes(640, 480))
        self.assertEqual(self.mode("vstudio"), 0o777)
        self.assertEqual(self.mode("vstudio", "49"), 0o777)
        for name in stored.paths:
            self.assertEqual(self.mode(*name.split("/")), 0o644)

    def test_existing_directory_keeps_its_mode(self):
        # Настройка чинит только новые каталоги. Старые перевладевает entrypoint
        # при старте core — поэтому после выкладки core обязательно пересоздаётся.
        os.makedirs(self.path("vstudio", "45"), 0o755)
        default_storage.save("vstudio/45/clip.mp4", ContentFile(b"mp4"))
        self.assertEqual(self.mode("vstudio", "45"), 0o755)

    def test_probe_creates_directories_open_to_both_users(self):
        self.assertEqual(storage_check.storage_ready(49), (True, ""))
        self.assertEqual(self.mode("vstudio"), 0o777)
        self.assertEqual(self.mode("vstudio", "49"), 0o777)
        self.assertEqual(os.listdir(self.path("vstudio", "49")), [])

    def test_probe_file_is_private_while_it_exists(self):
        seen = {}
        real = os.write

        def spy(fd, data):
            seen["mode"] = stat.S_IMODE(os.fstat(fd).st_mode)
            return real(fd, data)

        with mock.patch("vstudio.storage_check.os.write", side_effect=spy):
            self.assertEqual(storage_check.storage_ready(49), (True, ""))
        self.assertEqual(seen["mode"], 0o600)

    @skipIf(IS_ROOT, "root пишет в любой каталог — отказа не будет")
    def test_closed_parent_directory_refuses_like_the_incident(self):
        os.makedirs(self.path("vstudio"))
        os.chmod(self.path("vstudio"), 0o555)
        self.addCleanup(os.chmod, self.path("vstudio"), 0o755)
        ok, reason = storage_check.storage_ready(49)
        self.assertFalse(ok)
        self.assertTrue(reason.startswith("каталог не создаётся: PermissionError"), reason)
        self.assertIn(self.path("vstudio", "49"), reason)

    @skipIf(IS_ROOT, "root пишет в любой каталог — отказа не будет")
    def test_closed_user_directory_refuses_like_the_incident(self):
        os.makedirs(self.path("vstudio", "45"))
        os.chmod(self.path("vstudio", "45"), 0o555)
        self.addCleanup(os.chmod, self.path("vstudio", "45"), 0o755)
        ok, reason = storage_check.storage_ready(45)
        self.assertFalse(ok)
        self.assertTrue(reason.startswith("файл не создаётся: PermissionError"), reason)
        self.assertEqual(os.listdir(self.path("vstudio", "45")), [])


# ---------------------------------------------------------------- проба: не локальный диск

class StorageApiProbeTests(SimpleTestCase):
    USER = 49

    def setUp(self):
        # В setUp, а не на классе: у каждого теста своё пустое хранилище.
        self.enterContext(override_settings(STORAGES=IN_MEMORY))

    def listing(self):
        return default_storage.listdir(user_dir(self.USER))

    def test_ready_through_save_and_delete_and_nothing_is_left(self):
        self.assertIsInstance(default_storage, InMemoryStorage)
        with mock.patch.object(InMemoryStorage, "save", autospec=True,
                               side_effect=InMemoryStorage.save) as save, \
                mock.patch.object(InMemoryStorage, "delete", autospec=True,
                                  side_effect=InMemoryStorage.delete) as delete:
            self.assertEqual(storage_check.storage_ready(self.USER), (True, ""))
        name, content = save.call_args.args[1:3]
        self.assertTrue(name.startswith(f"{user_dir(self.USER)}/.probe-"), name)
        content.seek(0)
        self.assertEqual(content.read(), storage_check.PROBE)
        delete.assert_called_once()
        self.assertEqual(delete.call_args.args[1], name)
        self.assertEqual(self.listing(), ([], []))

    def test_storage_without_local_paths_is_named_in_the_log_by_its_key(self):
        # Так отвечает любое облачное хранилище: путей на диске у него нет.
        with mock.patch.object(InMemoryStorage, "path", side_effect=NotImplementedError):
            self.assertEqual(storage_check.storage_path(self.USER), user_dir(self.USER))

    def test_failed_write_is_not_ready(self):
        for error in (denied(), disk_full()):
            with self.subTest(error=error), \
                    mock.patch.object(InMemoryStorage, "save", side_effect=error):
                ok, reason = storage_check.storage_ready(self.USER)
                self.assertFalse(ok)
                self.assertTrue(reason.startswith(f"файл не пишется: {type(error).__name__}"), reason)

    def test_half_written_probe_is_cleaned_up(self):
        real = InMemoryStorage.save

        def half(storage, name, content, max_length=None):
            real(storage, name, content, max_length=max_length)
            raise disk_full()

        with mock.patch.object(InMemoryStorage, "save", autospec=True, side_effect=half):
            ok, reason = storage_check.storage_ready(self.USER)
        self.assertFalse(ok)
        self.assertTrue(reason.startswith("файл не пишется"), reason)
        self.assertEqual(self.listing(), ([], []))

    def test_probe_that_cannot_be_deleted_is_not_ready_and_logged(self):
        with mock.patch.object(InMemoryStorage, "delete", side_effect=denied()), \
                self.assertLogs("vstudio.storage_check", "ERROR") as logs:
            ok, reason = storage_check.storage_ready(self.USER)
        self.assertFalse(ok)
        self.assertTrue(reason.startswith("пробный файл не удаляется: PermissionError"), reason)
        self.assertTrue(any(".probe-" in line for line in logs.output), logs.output)

    def test_free_space_floor_is_for_the_local_disk_only(self):
        # У хранилища без диска мерить нечего: за него отвечает проба save/delete.
        with mock.patch("vstudio.storage_check._free_bytes", return_value=0) as free:
            self.assertEqual(storage_check.storage_ready(self.USER), (True, ""))
        free.assert_not_called()


# ---------------------------------------------------------------- конвейер: видео

class SubmitStorageTests(PipelineCase):
    def setUp(self):
        super().setUp()
        self.free = roomy(self)

    def old_take(self, **kw):
        # Старше минуты — иначе уведомление не шлётся (человек ещё на странице).
        return self.set(self.video_take(**kw), created_at=self.ago(minutes=5))

    def test_provider_is_not_called_when_the_result_cannot_be_stored(self):
        take = self.old_take()
        with self.provider(submit=accepted()) as p, \
                mock.patch("vstudio.storage_check.storage_ready",
                           return_value=(False, DENIED)) as probe, \
                self.assertLogs("vstudio.pipeline", "ERROR") as logs:
            self.assertEqual(pipeline.submit(take.pk), "failed")
        p.mocks["submit"].assert_not_called()
        probe.assert_called_once_with(self.user.pk)
        take.refresh_from_db()
        self.assertEqual((take.status, take.error_code), ("failed", "service_misconfigured"))
        self.assertEqual(take.error, pipeline.ERRORS["service_misconfigured"])
        self.assertIn("не списаны", take.error)
        self.assertEqual((take.charge_state, take.credits_charged), ("released", 0))
        self.assertIsNotNone(take.finished_at)
        self.assertEqual((take.provider_id, take.polling_url), ("", ""))
        row = GenerationLog.objects.get(pk=take.genlog_id)
        self.assertEqual(row.status, "failed")
        self.assertEqual(row.error, f"хранилище недоступно: {DENIED}")
        self.assertFalse(row.needs_review)
        self.assertEqual(row.credits_charged, 0)
        self.assertNotIn("sending", [s["stage"] for s in row.stages])
        # Лог — с дублем и каталогом: по нему чинят.
        line = next(m for m in logs.output if "хранилище недоступно" in m)
        self.assertIn(f"take={take.uid}", line)
        self.assertIn(storage_check.storage_path(self.user.pk), line)
        self.assertIn(DENIED, line)
        self.assertEqual(self.ledger(), [])
        self.assertEqual(self.enqueued, [])
        self.user.refresh_from_db()
        self.assertEqual(self.user.token_balance, 500)
        self.assert_money_invariant()

    def test_owner_is_notified_once(self):
        take = self.old_take()
        with self.provider(submit=accepted()), \
                mock.patch("vstudio.storage_check.storage_ready", return_value=(False, DENIED)):
            pipeline.submit(take.pk)
            # Вторая копия задачи ничего не делает и второй раз не уведомляет.
            self.assertEqual(pipeline.submit(take.pk), "skip")
        self.assertEqual(self.notified, [take.pk])
        self.push.assert_called_once()
        self.assertEqual(self.push.call_args.args[1], "Видео не получилось")
        self.assertIn("Кредиты не списаны", self.push.call_args.args[2])
        note = Notification.objects.get()
        self.assertEqual(list(note.recipients.all()), [self.user])

    def test_real_os_refusal_stops_the_take_before_the_provider(self):
        take = self.video_take()
        with self.provider(submit=accepted()) as p, \
                mock.patch("vstudio.storage_check.os.mkdir", side_effect=denied()), \
                self.assertLogs("vstudio.pipeline", "ERROR"):
            self.assertEqual(pipeline.submit(take.pk), "failed")
        p.mocks["submit"].assert_not_called()
        take.refresh_from_db()
        self.assertEqual((take.status, take.error_code, take.charge_state),
                         ("failed", "service_misconfigured", "released"))
        error = GenerationLog.objects.get(pk=take.genlog_id).error
        self.assertTrue(error.startswith("хранилище недоступно: каталог не создаётся"), error)
        self.assertEqual(self.studio_files(), [])
        self.assert_money_invariant()

    def test_full_disk_stops_the_take_before_the_provider(self):
        take = self.video_take()
        with self.provider(submit=accepted()) as p, \
                mock.patch("vstudio.storage_check.os.write", side_effect=disk_full()), \
                self.assertLogs("vstudio.pipeline", "ERROR"):
            self.assertEqual(pipeline.submit(take.pk), "failed")
        p.mocks["submit"].assert_not_called()
        self.assertIn("No space left on device",
                      GenerationLog.objects.get(source="vstudio").error)
        self.assertEqual(self.studio_files(), [])

    def test_low_space_in_media_stops_the_take_before_the_provider(self):
        # Пробные 4 байта записались бы; не влез бы сам ролик — уже оплаченный.
        take = self.video_take()
        self.free.return_value = 412 * MB
        with self.provider(submit=accepted()) as p, \
                self.assertLogs("vstudio.pipeline", "ERROR") as logs:
            self.assertEqual(pipeline.submit(take.pk), "failed")
        p.mocks["submit"].assert_not_called()
        take.refresh_from_db()
        self.assertEqual((take.status, take.error_code), ("failed", "service_misconfigured"))
        self.assertEqual((take.charge_state, take.credits_charged), ("released", 0))
        self.assertEqual((take.provider_id, take.polling_url), ("", ""))
        row = GenerationLog.objects.get(pk=take.genlog_id)
        self.assertEqual(row.status, "failed")
        self.assertEqual(row.error, f"хранилище недоступно: мало места: 412 МБ свободно в "
                                    f"{storage_check.storage_path(self.user.pk)}, нужно 1024 МБ")
        self.assertFalse(row.needs_review)
        self.assertTrue(any(f"take={take.uid}" in m and "мало места" in m for m in logs.output),
                        logs.output)
        self.assertEqual(self.ledger(), [])
        self.assertEqual(self.enqueued, [])
        self.assertEqual(self.studio_files(), [])
        self.assert_money_invariant()

    def test_low_space_in_the_download_directory_stops_the_take_before_the_provider(self):
        take = self.video_take()
        tmp = tempfile.gettempdir()
        self.free.side_effect = lambda path: 5 * MB if same_path(path, tmp) else ROOMY
        with self.provider(submit=accepted()) as p, self.assertLogs("vstudio.pipeline", "ERROR"):
            self.assertEqual(pipeline.submit(take.pk), "failed")
        p.mocks["submit"].assert_not_called()
        take.refresh_from_db()
        self.assertEqual((take.status, take.error_code, take.charge_state),
                         ("failed", "service_misconfigured", "released"))
        self.assertEqual(GenerationLog.objects.get(pk=take.genlog_id).error,
                         f"хранилище недоступно: мало места: 5 МБ свободно в {tmp}, нужно 1024 МБ")
        self.assert_money_invariant()

    def test_probe_runs_after_the_journal_and_before_the_provider(self):
        take = self.video_take()
        order = []
        real = storage_check.storage_ready

        def probe(user_id):
            # Дубль уже ссылается на запись журнала: причину отказа будет куда записать.
            row = Take.objects.get(pk=take.pk)
            order.append(("probe", row.status, row.genlog.status))
            return real(user_id)

        def send(body, **kw):
            order.append(("provider",))
            return accepted()

        with self.provider(submit=send), \
                mock.patch("vstudio.storage_check.storage_ready", side_effect=probe) as probe_mock:
            self.assertEqual(pipeline.submit(take.pk), "running")
        self.assertEqual(order, [("probe", "submitting", "submitting"), ("provider",)])
        probe_mock.assert_called_once_with(self.user.pk)

    def test_ready_storage_changes_nothing(self):
        take = self.video_take()
        with self.provider(submit=accepted()) as p:
            self.assertEqual(pipeline.submit(take.pk), "running")
        self.assertEqual(p.mocks["submit"].call_count, 1)
        take.refresh_from_db()
        self.assertEqual((take.status, take.charge_state, take.error_code),
                         ("running", "reserved", ""))
        self.assertEqual(take.provider_id, "gen-1")
        self.assertEqual(GenerationLog.objects.get(pk=take.genlog_id).status, "submitted")
        self.assertEqual(self.enqueued, [("poll_take", take.pk, 15, {})])
        # Проба оставила каталог человека и ни одного файла.
        self.assertTrue(os.path.isdir(os.path.join(self.media, "vstudio", str(self.user.pk))))
        self.assertEqual(self.studio_files(), [])
        self.assert_money_invariant()

    def test_journal_is_checked_first_and_the_disk_is_not_touched_without_it(self):
        take = self.video_take()
        with self.provider(submit=accepted()) as p, \
                mock.patch("vstudio.storage_check.storage_ready") as probe, \
                mock.patch.object(GenerationLog.objects, "create",
                                  side_effect=OperationalError("journal down")):
            self.assertEqual(pipeline.submit(take.pk), "failed")
        probe.assert_not_called()
        p.mocks["submit"].assert_not_called()
        self.assertEqual(Take.objects.get(pk=take.pk).error_code, "journal_unavailable")

    def test_delivery_writes_into_the_probed_directory(self):
        take = self.video_take(status="saving", genlog=True)
        self.set(take, lease_until=timezone.now(), submitted_at=self.ago(minutes=2),
                 created_at=self.ago(minutes=3))
        with self.provider(poll=ready()):
            self.assertEqual(pipeline.finalize(take.pk), "done")
        take.refresh_from_db()
        probed = storage_check.storage_path(self.user.pk)
        for name in (take.result_asset.file, take.result_asset.thumb):
            self.assertTrue(same_path(os.path.dirname(default_storage.path(name)), probed), name)


# ---------------------------------------------------------------- конвейер: картинка

class ImageStorageTests(PipelineCase):
    def setUp(self):
        super().setUp()
        self.free = roomy(self)

    def ok(self):
        return mp.Images(items=[mp.ImageItem(b64=png_b64(), media_type="image/jpeg")], cost=0.039,
                         status_code=200)

    def test_provider_is_not_called_when_the_result_cannot_be_stored(self):
        take, pending = self.image_take()
        self.set(take, created_at=self.ago(minutes=5))
        with self.provider(image=self.ok()) as p, \
                mock.patch("vstudio.storage_check.storage_ready",
                           return_value=(False, DENIED)) as probe, \
                self.assertLogs("vstudio.pipeline", "ERROR") as logs:
            self.assertEqual(pipeline.run_image(take.pk), "failed")
        p.mocks["image"].assert_not_called()
        probe.assert_called_once_with(self.user.pk)
        take.refresh_from_db()
        pending.refresh_from_db()
        self.assertEqual((take.status, take.error_code), ("failed", "service_misconfigured"))
        self.assertEqual(take.error, pipeline.ERRORS["service_misconfigured"])
        self.assertEqual((take.charge_state, take.credits_charged), ("released", 0))
        # Чип в лотке краснеет, а не висит «в работе».
        self.assertEqual((pending.status, pending.error_code), ("failed", "service_misconfigured"))
        row = GenerationLog.objects.get(pk=take.genlog_id)
        self.assertEqual((row.kind, row.status), ("image", "failed"))
        self.assertEqual(row.error, f"хранилище недоступно: {DENIED}")
        self.assertFalse(row.needs_review)
        self.assertTrue(any(f"take={take.uid}" in m for m in logs.output), logs.output)
        self.assertEqual(self.ledger(), [])
        self.assertEqual(self.studio_files(), [])
        self.assertEqual(self.notified, [take.pk])
        self.push.assert_called_once()
        self.assertEqual(self.push.call_args.args[1], "Картинка не получилась")
        self.assertEqual(Notification.objects.count(), 1)
        self.assert_money_invariant()

    def test_real_os_refusal_stops_the_take_before_the_provider(self):
        take, pending = self.image_take()
        with self.provider(image=self.ok()) as p, \
                mock.patch("vstudio.storage_check.os.open", side_effect=denied()), \
                self.assertLogs("vstudio.pipeline", "ERROR"):
            self.assertEqual(pipeline.run_image(take.pk), "failed")
        p.mocks["image"].assert_not_called()
        take.refresh_from_db()
        self.assertEqual((take.status, take.error_code, take.charge_state),
                         ("failed", "service_misconfigured", "released"))
        error = GenerationLog.objects.get(pk=take.genlog_id).error
        self.assertTrue(error.startswith("хранилище недоступно: файл не создаётся"), error)
        self.assert_money_invariant()

    def test_low_disk_space_stops_the_take_before_the_provider(self):
        # Порог у картинки тот же, что у ролика: один на всю студию.
        take, pending = self.image_take()
        self.free.return_value = storage_check.MIN_FREE_BYTES - 1
        with self.provider(image=self.ok()) as p, self.assertLogs("vstudio.pipeline", "ERROR"):
            self.assertEqual(pipeline.run_image(take.pk), "failed")
        p.mocks["image"].assert_not_called()
        take.refresh_from_db()
        pending.refresh_from_db()
        self.assertEqual((take.status, take.error_code, take.charge_state),
                         ("failed", "service_misconfigured", "released"))
        self.assertEqual((pending.status, pending.error_code), ("failed", "service_misconfigured"))
        error = GenerationLog.objects.get(pk=take.genlog_id).error
        self.assertTrue(error.startswith("хранилище недоступно: мало места: 1023 МБ свободно в "),
                        error)
        self.assertEqual(self.ledger(), [])
        self.assertEqual(self.studio_files(), [])
        self.assert_money_invariant()

    def test_probe_runs_after_the_journal_and_before_the_provider(self):
        take, _pending = self.image_take()
        order = []
        real = storage_check.storage_ready

        def probe(user_id):
            row = Take.objects.get(pk=take.pk)
            order.append(("probe", row.status, row.genlog.status))
            return real(user_id)

        def send(body, **kw):
            order.append(("provider",))
            return self.ok()

        with self.provider(image=send), \
                mock.patch("vstudio.storage_check.storage_ready", side_effect=probe) as probe_mock:
            self.assertEqual(pipeline.run_image(take.pk), "done")
        self.assertEqual(order, [("probe", "running", "submitting"), ("provider",)])
        probe_mock.assert_called_once_with(self.user.pk)

    def test_ready_storage_changes_nothing(self):
        take, pending = self.image_take()
        with self.provider(image=self.ok()) as p:
            self.assertEqual(pipeline.run_image(take.pk), "done")
        self.assertEqual(p.mocks["image"].call_count, 1)
        take.refresh_from_db()
        pending.refresh_from_db()
        self.assertEqual((take.status, take.charge_state, take.credits_charged), ("done", "charged", 6))
        self.assertEqual(pending.status, "ready")
        self.assertEqual([(t.delta, t.reason) for t in self.ledger()], [(-6, "vstudio_image")])
        # Только картинка и её превью — пробы на диске нет.
        self.assertEqual(sorted(os.path.basename(path) for path in self.studio_files()),
                         sorted(os.path.basename(name) for name in (pending.file, pending.thumb)))
        self.assertTrue(same_path(os.path.dirname(default_storage.path(pending.file)),
                                  storage_check.storage_path(self.user.pk)))
        self.assert_money_invariant()

    def test_journal_is_checked_first(self):
        take, _pending = self.image_take()
        with self.provider(image=self.ok()) as p, \
                mock.patch("vstudio.storage_check.storage_ready") as probe, \
                mock.patch.object(GenerationLog.objects, "create",
                                  side_effect=OperationalError("journal down")):
            self.assertEqual(pipeline.run_image(take.pk), "failed")
        probe.assert_not_called()
        p.mocks["image"].assert_not_called()
        self.assertEqual(Take.objects.get(pk=take.pk).error_code, "journal_unavailable")
