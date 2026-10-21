"""Цена и пределы склейки.

Цена — runtime-ключ merge_price_credits (правится в админке без выкладки):
20 кр — цифра клиента из ТЗ 29.09, 0 — склейка бесплатна. Списывается только
за готовый ролик: до него цена лежит в резерве.
"""
from __future__ import annotations

import logging

from django.db import transaction

logger = logging.getLogger(__name__)

PRICE_KEY = "merge_price_credits"
DEFAULT_PRICE = 20
MAX_PRICE = 100000

MIN_FRAGMENTS = 2
MAX_FRAGMENTS = 30
MAX_TOTAL_S = 300
# Сколько дней хранится готовая склейка (ТЗ: «Мои видео → Склейки» 30 дней).
RETENTION_DAYS = 30
# Черновиков и склеек у одного человека — с запасом на любую работу, но не
# бесконечно: строка хранит до тридцати фрагментов со снимком карточки.
# Истёкшие не считаются: файлов у них нет, а новую работу они бы запирали.
MAX_PROJECTS = 100
# Готовых склеек у человека одновременно. Ролик хранится 30 дней и весит до
# ~150 МБ: без предела один аккаунт (при цене 0 — бесплатно) занял бы десятки
# гигабайт, а полный диск — отказ всего сайта, не только склейки.
MAX_READY = 20

# Кадр 720p-класса под каждый формат: 1:1 — 960, чтобы квадрат не был мельче
# горизонтального кадра по площади.
TARGETS = {"16:9": (1280, 720), "9:16": (720, 1280), "1:1": (960, 960)}
ASPECTS = tuple(TARGETS)
FIT_PAD = "pad"
FIT_CROP = "crop"
FITS = (FIT_PAD, FIT_CROP)


MB = 1024 * 1024
# Свои видео (Build MU). Тело запроса у Cloudflare Free — до 100 МБ, в nginx
# location загрузки — 95 МБ: файл до 90 МБ проходит обе стены с запасом на
# обёртку multipart.
UPLOAD_MAX_BYTES = 90 * MB
UPLOAD_MIN_DURATION_S = 0.5
UPLOAD_MAX_DURATION_S = 60
# Обрезка до «1:00» в галерее телефона даёт 60,03 с — это ещё минута.
UPLOAD_DURATION_TOLERANCE_S = 0.5
UPLOAD_MAX_SIDE = 4096
UPLOAD_MAX_PER_PROJECT = 3
# Сколько своих видео хранится у человека разом: сервер на двух ядрах и одном
# диске, а загрузка бесплатна.
UPLOAD_MAX_FILES = 10
UPLOAD_MAX_TOTAL_BYTES = 600 * MB
UPLOAD_RETENTION_DAYS = 30
UPLOAD_EXTENSIONS = ("mp4", "mov", "m4v", "webm")
UPLOAD_ACCEPT = "video/mp4,video/quicktime,video/webm,.mp4,.mov,.m4v,.webm"
# Видеокодеки, которые ffmpeg сервера точно разбирает; прочее (ProRes, DNxHD,
# MJPEG с камер) — отказ при загрузке, а не сбой склейки потом.
UPLOAD_CODECS = ("h264", "hevc", "vp8", "vp9", "av1", "mpeg4")
# Кадров в секунду в среднем (пакеты видеодорожки / длина). Цена нормализации
# растёт с числом кадров: крошечный файл на тысячи к/с держал слот media до
# потолка фрагмента, а склейка падала too_slow без списания — бесплатно и без
# конца. 120 — замедленная съёмка телефонов (4K120 у iPhone) ещё проходит.
UPLOAD_MAX_FPS = 120
# Запас на округление длины и лишние пакеты в начале и конце дорожки.
UPLOAD_FPS_SLACK_FRAMES = 30
# Звук своего видео, который склейка декодирует; прочий — как немой (тишина).
# Имена — codec_name ffprobe.
UPLOAD_AUDIO_CODECS = ("aac", "mp3", "mp2", "opus", "vorbis", "ac3", "eac3", "alac", "flac",
                       "amr_nb", "amr_wb", "pcm_s16le", "pcm_s16be", "pcm_s24le", "pcm_s24be",
                       "pcm_s32le", "pcm_s32be", "pcm_f32le", "pcm_f32be", "pcm_u8", "pcm_alaw",
                       "pcm_mulaw")
# Декодеры (имена AVCodec, -codec_whitelist), которые ffprobe и ffmpeg вообще
# откроют в чужом файле: видео из списка выше, звук из списка выше, обложки
# (mjpeg, png) и текстовые субтитры — их телефоны и дроны кладут рядом с видео.
# Поток с другим декодером ffprobe не откроет, и файл не пройдёт разбор.
UPLOAD_DECODERS = ("h264", "hevc", "vp8", "vp9", "av1", "libdav1d", "libaom-av1", "mpeg4",
                   "aac", "aac_fixed", "mp3float", "mp3", "mp2float", "mp2", "opus", "libopus",
                   "vorbis", "libvorbis", "ac3", "ac3_fixed", "eac3", "alac", "flac",
                   "amrnb", "amrwb", "libopencore_amrnb", "libopencore_amrwb",
                   "pcm_s16le", "pcm_s16be", "pcm_s24le", "pcm_s24be", "pcm_s32le", "pcm_s32be",
                   "pcm_f32le", "pcm_f32be", "pcm_u8", "pcm_alaw", "pcm_mulaw",
                   "mjpeg", "png", "mov_text", "subrip", "ass", "ssa", "webvtt", "text")


def price_credits() -> int:
    """Цена одной склейки в кредитах (0 — бесплатно). Никогда не бросает.

    Чтение — в savepoint: сбой запроса к настройкам на Postgres иначе сломал
    бы всю транзакцию запроса.
    """
    value = DEFAULT_PRICE
    try:
        from adminapi.runtime import get_runtime

        with transaction.atomic():
            value = int(get_runtime(PRICE_KEY, DEFAULT_PRICE))
    except Exception:
        logger.warning("склейка: цена не прочиталась, беру %s", DEFAULT_PRICE, exc_info=True)
        value = DEFAULT_PRICE
    return min(MAX_PRICE, max(0, value))


def limits() -> dict:
    """Пределы для интерфейса: те же числа, что проверяет сервер."""
    return {"min_fragments": MIN_FRAGMENTS, "max_fragments": MAX_FRAGMENTS,
            "max_total_s": MAX_TOTAL_S, "retention_days": RETENTION_DAYS}


def upload_limits() -> dict:
    """Пределы своих видео для интерфейса (подсказки и проверки до загрузки)."""
    return {
        "max_bytes": UPLOAD_MAX_BYTES,
        "max_mb": UPLOAD_MAX_BYTES // MB,
        "min_duration_s": UPLOAD_MIN_DURATION_S,
        "max_duration_s": UPLOAD_MAX_DURATION_S,
        "max_side": UPLOAD_MAX_SIDE,
        "max_fps": UPLOAD_MAX_FPS,
        "max_per_project": UPLOAD_MAX_PER_PROJECT,
        "max_files": UPLOAD_MAX_FILES,
        "max_total_bytes": UPLOAD_MAX_TOTAL_BYTES,
        "max_total_mb": UPLOAD_MAX_TOTAL_BYTES // MB,
        "retention_days": UPLOAD_RETENTION_DAYS,
        "extensions": list(UPLOAD_EXTENSIONS),
        "accept": UPLOAD_ACCEPT,
    }


# Подпись по умолчанию на языке запроса: сервер подставляет её, когда клиент
# названия не прислал (склейка без названия, ролик без промпта).
DEFAULT_TITLE = {"ru": "Склейка {date}", "en": "Merge {date}", "kg": "Бириктирүү {date}"}


def localized(table: dict, lang: str) -> str:
    return table.get(lang) or table["ru"]
