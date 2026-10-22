"""Цена и пределы склейки.

Цена — runtime-ключ merge_price_credits (правится в админке без выкладки):
20 кр — цифра клиента из ТЗ 29.09, 0 — склейка бесплатна. Списывается только
за готовый ролик: до него цена лежит в резерве.
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.db import transaction

logger = logging.getLogger(__name__)

PRICE_KEY = "merge_price_credits"
DEFAULT_PRICE = 20
MAX_PRICE = 100000
# Бесплатная склейка (цена 0) — это минуты работы двух ядер сервера на каждый
# запуск: без предела один аккаунт склеивал бы по кругу и занимал очередь media,
# общую с оплаченными съёмками. Runtime-ключ, правится без выкладки; 0 — без предела.
FREE_DAILY_KEY = "merge_free_daily_limit"
FREE_DAILY_DEFAULT = 10
FREE_DAILY_MAX = 1000

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


# Звук склейки (Build MA): голос за кадром, фоновая музыка, звук самих роликов.
CLIP_KEEP, CLIP_QUIET, CLIP_OFF = "keep", "quiet", "off"
CLIP_SOUNDS = (CLIP_KEEP, CLIP_QUIET, CLIP_OFF)
# «Тише» — речь роликов ещё слышна, но не спорит с голосом и музыкой.
CLIP_VOLUMES = {CLIP_KEEP: 1.0, CLIP_QUIET: 0.3, CLIP_OFF: 0.0}
MUSIC_VOLUME_DEFAULT = 0.35
MUSIC_VOLUME_MAX = 1.0
VOICE_VOLUME_DEFAULT = 1.0
# Как у дорожек мультстудии: тихую запись можно поднять вдвое.
VOICE_VOLUME_MAX = 2.0
# Музыка — на всю склейку, а склейка не длиннее пяти минут (это и потолок ElevenLabs).
MUSIC_MAX_S = MAX_TOTAL_S
MUSIC_PROMPT_MIN, MUSIC_PROMPT_MAX = 3, 400
# Свой трек: бесплатный, поэтому с пределами; в хранилище ложится mp3 (до ~6 МБ за 5 минут).
AUDIO_UPLOAD_MAX_BYTES = 20 * MB
AUDIO_UPLOAD_MAX_S = MAX_TOTAL_S
# «5:00» из редактора бывает 300,04 с — это ещё пять минут.
AUDIO_UPLOAD_TOLERANCE_S = 1.0
# Потолок длины считает секунды, а работа пересборки растёт с частотой × каналами:
# FLAC тишины в 200 КБ на 8 каналов и 655 кГц пересобирается в 3–4 раза дольше
# честного стерео той же длины, а частоту и каналы файл пишет какие угодно.
# Выше студийных 192 кГц и 7.1 честной музыки не бывает.
AUDIO_UPLOAD_MAX_RATE = 192_000
AUDIO_UPLOAD_MAX_CHANNELS = 8
AUDIO_RETENTION_DAYS = 30
# Голос за кадром склейки — до 2000 знаков (у мультстудии на сцену — 1000): текст
# идёт на всю склейку, до пяти минут. Цена — та же формула озвучки.
VOICE_MAX_CHARS = 2000
# Музыка склейки по описанию: сколько заказов делается разом на весь сайт. Очередь
# media — три места на двух ядрах, общие с видео чата, сценами мультстудии и самими
# склейками, а заказ музыки держит место до 540 с ожидания ElevenLabs: без предела
# три заказа разом заняли бы её целиком. Runtime-ключ — правится без выкладки;
# без него — settings.MERGE_MUSIC_CONCURRENCY (env), без того — 2.
MUSIC_CONCURRENCY_KEY = "merge_music_concurrency"
MUSIC_CONCURRENCY_DEFAULT = 2
MUSIC_CONCURRENCY_MAX = 8
# Звук, который ffmpeg сводит из своего трека (codec_name ffprobe): как у своих видео
# плюс то, что пишут диктофоны и старые плееры (WMA, ADPCM, 8-битный PCM).
AUDIO_TRACK_CODECS = UPLOAD_AUDIO_CODECS + ("wmav1", "wmav2", "pcm_s8", "adpcm_ima_qt",
                                            "adpcm_ima_wav", "adpcm_ms")
# Декодеры для строгого разбора трека: звук выше, а ещё картинка (обложка mp3/m4a, видео
# в mp4/webm — звук из ролика тоже годится) — иначе ffprobe не откроет такой файл.
AUDIO_DECODERS = UPLOAD_DECODERS + ("wmav1", "wmav2", "pcm_s8", "adpcm_ima_qt", "adpcm_ima_wav",
                                    "adpcm_ms")


def audio_volumes(clip_sound: str, music_volume, voice_volume) -> tuple[float, float, float]:
    """Громкости сведения в допустимых пределах: (ролики, музыка, голос)."""
    def clamp(value, default: float, top: float) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return default
        return min(top, max(0.0, number)) if number == number else default

    return (CLIP_VOLUMES.get(clip_sound, 1.0), clamp(music_volume, MUSIC_VOLUME_DEFAULT, MUSIC_VOLUME_MAX),
            clamp(voice_volume, VOICE_VOLUME_DEFAULT, VOICE_VOLUME_MAX))


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


def music_concurrency() -> int:
    """Сколько музык склейки делается разом (1…8). Никогда не бросает; чтение — в
    savepoint, как у цены."""
    value = getattr(settings, "MERGE_MUSIC_CONCURRENCY", MUSIC_CONCURRENCY_DEFAULT)
    try:
        value = int(value)
    except (TypeError, ValueError):
        value = MUSIC_CONCURRENCY_DEFAULT
    try:
        from adminapi.runtime import get_runtime

        with transaction.atomic():
            value = int(get_runtime(MUSIC_CONCURRENCY_KEY, value))
    except Exception:
        logger.warning("склейка: предел музыки не прочитался, беру %s", value, exc_info=True)
    return min(MUSIC_CONCURRENCY_MAX, max(1, value))


def free_daily_limit() -> int:
    """Сколько бесплатных склеек (цена 0) человек запускает за сутки; 0 — без предела.

    При цене больше нуля предел не действует: склейку ограничивает баланс. Никогда
    не бросает; чтение — в savepoint, как у цены.
    """
    value = FREE_DAILY_DEFAULT
    try:
        from adminapi.runtime import get_runtime

        with transaction.atomic():
            value = int(get_runtime(FREE_DAILY_KEY, FREE_DAILY_DEFAULT))
    except Exception:
        logger.warning("склейка: суточный предел не прочитался, беру %s", FREE_DAILY_DEFAULT,
                       exc_info=True)
        value = FREE_DAILY_DEFAULT
    return min(FREE_DAILY_MAX, max(0, value))


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
