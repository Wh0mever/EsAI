"""ffmpeg склейки: привести каждый фрагмент к одному виду и соединить.

Почему в два шага, а не через ai.video_edit.concat_videos. Тот работает с
байтами в памяти (тридцать роликов — сотни мегабайт в воркере media) и
перекодирует всё ещё раз. Здесь каждый фрагмент один раз перекодируется в общий
вид — кадр, 30 к/с, звук 48 кГц стерео, одни и те же настройки x264/AAC, — и
после этого части одинаковы до байта в параметрах потока: соединение идёт
concat-демуксером без перекодирования. Демуксер опасен ровно на разных
параметрах (так в video_edit), поэтому при его сбое — запасной путь: один граф
concat-фильтра с перекодированием.

Все команды — списки аргументов (без shell), у каждой свой потолок времени:
битый файл не подвесит воркер.

Свои видео людей (Build MU) — чужие файлы, поэтому ffmpeg и ffprobe читают
их строже: демуксер задан явно (mov или matroska — по первым байтам при
загрузке), протоколы — только file, путь — с префиксом file:, декодеры —
только из списка (config.UPLOAD_DECODERS). Плейлист, ссылка или «concat»
внутри файла так не откроются. Поворот с телефона ffmpeg применяет сам
(autorotate), HDR приводится к SDR 8 бит, переменная частота кадров — к
ровным 30 к/с (фильтр fps).

Звук (Build MA) — третий шаг после соединения, только если он нужен (есть
голос или музыка, или звук роликов тише/выключен): картинка склеенного ролика
копируется как есть, звук сводится заново (mix_cmd). Без звука склейки
команды те же до байта, что и до Build MA.
"""
from __future__ import annotations

import json
import logging
import math
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from typing import Callable

from .config import (AUDIO_DECODERS, AUDIO_TRACK_CODECS, FIT_CROP, TARGETS, UPLOAD_AUDIO_CODECS,
                     UPLOAD_DECODERS)

logger = logging.getLogger(__name__)

FPS = 30
CRF = 21
AUDIO_RATE = 48000
AUDIO_BITRATE = "128k"
# Два потока на ffmpeg: в media три слота на двух ядрах, оплаченные съёмки
# мультстудии не должны ждать склейку.
THREADS = "2"
NICENESS = "10"
PROBE_TIMEOUT_S = 30
# Разбор чужого файла: сколько читать на поиск потоков (байт и мкс) и потолок
# времени. Заголовок любого честного ролика укладывается с большим запасом.
UPLOAD_PROBE_SIZE = "10000000"
UPLOAD_ANALYZE_US = "10000000"
UPLOAD_PROBE_TIMEOUT_S = 20
UPLOAD_POSTER_TIMEOUT_S = 30
UPLOAD_FORMATS = ("mov", "matroska")
HDR_TRANSFERS = ("smpte2084", "arib-std-b67")
# HDR (PQ, HLG — так снимают iPhone и флагманы Android) → SDR bt709 8 бит.
# zscale есть в ffmpeg Debian; если фильтра нет — запасной граф без него.
TONEMAP = ("zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,"
           "tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p")
# Запасной путь HDR: только сменить метку кадра на bt709. Метку берёт кодер из
# кадра, а не из -color_trc (ffmpeg 7.1 проверен вживую): без этого PQ/HLG
# первой части досталась бы всей склейке.
RELABEL_BT709 = "setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709"
JOIN_TIMEOUT_S = 300
POSTER_TIMEOUT_S = 60
# Потолок на один фрагмент: минимум две минуты, дальше — десять секунд работы
# на секунду ролика (размытый фон на двух ядрах укладывается с запасом).
FRAGMENT_MIN_TIMEOUT_S = 120
FRAGMENT_TIMEOUT_PER_S = 10
POSTER_WIDTH = 480

# Сведение звука (Build MA). Картинка копируется, работа — только звук: на
# двух ядрах это секунды на минуту ролика. Потолок с большим запасом; он же
# вычитается из срока склейки заранее, чтобы фрагменты не съели время сведения.
MIX_MIN_TIMEOUT_S = 60
MIX_TIMEOUT_PER_S = 0.5
# Музыка под голосом: −12 дБ (четверть громкости), спуск за 0,3 с до голоса и
# подъём за 0,5 с после него; вступление и концовка музыки — по 1 с.
DUCK_GAIN = 0.25
DUCK_DOWN_S = 0.3
DUCK_UP_S = 0.5
# Огибающая (volume eval=frame) меняет громкость раз в кадр звука: кадры по 1024
# сэмпла (21 мс) давали ступеньки ~0,6 дБ на спуске и подъёме — на ровном тоне
# слышно «шуршание». Кадры по 256 (5 мс) делают ступеньки в четыре раза мельче.
DUCK_FRAME = 256
MUSIC_FADE_S = 1.0
# Голос, музыка и звук роликов вместе могут перешагнуть 0 дБ: ограничитель
# срезает пики мягко, без треска (level=0 — не поднимать громкость сам;
# latency=1 — без задержки на заглядывание вперёд: иначе весь звук, и роликов
# тоже, отставал бы от картинки на 5 мс, а последние 5 мс терялись).
LIMIT = 0.95
# Наши mp3 (save_audio мультстудии): демуксер и декодеры заданы, протокол — только file.
TRACK_DECODERS = ("mp3float", "mp3")
# Звук склеенного ролика — по меткам времени. Соединение копией теряет у частей
# (кроме первой) пропуск первого кадра AAC: на каждом стыке декодер отдаёт ~39 мс
# лишних сэмплов при верных метках, и amix, который сводит подряд по сэмплам, уводил
# голос на ~20 мс за каждый стык (проверено на 7.1: голос с 4-го фрагмента — на 57 мс
# раньше картинки). aresample с жёсткой подгонкой по меткам (больше 5 мс — срезать
# или добить тишиной) возвращает звук роликов на его время.
CLIP_ALIGN = "min_comp=0.001:min_hard_comp=0.005:first_pts=0"
# Звук своего видео: сколько сэмплов сверх длины картинки пропускать (audio_graph cap_s).
AUDIO_CAP_SLACK_S = 1.0

MSG_UNREADABLE = "Фрагмент №{n} не читается — уберите его из склейки и попробуйте снова."
MSG_NO_VIDEO = "Во фрагменте №{n} нет видео — уберите его из склейки и попробуйте снова."
MSG_FRAGMENT_FAILED = "Не получилось обработать фрагмент №{n} — попробуйте ещё раз или уберите его."
MSG_JOIN_FAILED = "Не получилось склеить фрагменты — попробуйте ещё раз."
MSG_TOO_SLOW = "Склейка заняла слишком долго — кредиты не списаны, попробуйте ещё раз."
MSG_MIX_FAILED = "Не получилось свести звук — кредиты не списаны, попробуйте ещё раз."


class RenderError(Exception):
    """Склейка не удалась. message — для человека (по-русски), detail — в лог,
    code — по нему интерфейс переводит текст, fragment — номер фрагмента (с 1)."""

    def __init__(self, message: str, detail: str = "", *, code: str = "failed",
                 fragment: int | None = None):
        super().__init__(message)
        self.message = message
        self.detail = detail
        self.code = code
        self.fragment = fragment


@dataclass(frozen=True)
class Probe:
    duration: float | None
    width: int | None
    height: int | None
    audio: bool
    video: bool
    # Подробности — из полного разбора (-show_streams): у своих видео людей.
    codec: str = ""
    video_streams: int = 0          # без обложек (attached_pic)
    video_index: int | None = None  # номер потока картинки в файле
    audio_index: int | None = None  # первый звук, который ffmpeg умеет читать
    rotation: int = 0               # 0, 90, 180, 270 — по часовой
    hdr: bool = False
    # Пакетов в дорожке картинки — сосчитаны чтением файла (-count_packets), а
    # не взяты из заголовка: заголовок пишет кто угодно. None — не считали.
    frames: int | None = None
    # Длительность контейнера (format.duration): по ней concat кладёт следующую
    # часть — с ней совпадает начало фрагмента в склеенном ролике.
    container_duration: float | None = None

    @property
    def display_width(self) -> int | None:
        return self.height if self.rotation in (90, 270) else self.width

    @property
    def display_height(self) -> int | None:
        return self.width if self.rotation in (90, 270) else self.height


@dataclass(frozen=True)
class Input:
    """Файл фрагмента; fmt — демуксер для своего видео человека ("" — наш файл)."""

    path: str
    fmt: str = ""


@dataclass(frozen=True)
class Rendered:
    path: str
    duration: float


def nice_prefix() -> list[str]:
    """«nice -n 10» перед ffmpeg на Linux, если nice есть; иначе пусто.

    Склейка — чистая работа процессора на двух ядрах рядом с API и базой:
    -threads ограничивает только кодер, а разбор и фильтры берут все ядра.
    Со сниженным приоритетом ffmpeg забирает только то, что сайту не нужно.
    """
    if os.name != "posix":
        return []
    path = shutil.which("nice")
    return [path, "-n", NICENESS] if path else []


def _run(cmd: list[str], timeout: float) -> subprocess.CompletedProcess:
    # ffprobe не трогаем: он короткий и идёт и в запросах API.
    if cmd and cmd[0] == "ffmpeg":
        cmd = nice_prefix() + cmd
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          timeout=max(1.0, float(timeout)), check=False)


def _tail(raw) -> str:
    return (raw or b"")[-400:].decode("utf-8", "replace")


# ---------------------------------------------------------------- probe

def probe_cmd(path: str) -> list[str]:
    return ["ffprobe", "-v", "error",
            "-show_entries", "stream=codec_type,width,height,duration:format=duration",
            "-of", "json", path]


def input_args(fmt: str) -> list[str]:
    """Опции чтения своего видео человека: только локальный файл, заданный
    демуксер и декодеры из списка — чужой файл не запустит редкий декодер,
    в котором могла бы найтись дыра."""
    if fmt not in UPLOAD_FORMATS:
        raise ValueError(f"unknown upload format {fmt!r}")
    return ["-protocol_whitelist", "file", "-codec_whitelist", ",".join(UPLOAD_DECODERS),
            "-f", fmt]


def input_path(path: str, fmt: str = "") -> str:
    # file: — чтобы имя никогда не читалось как протокол или опция.
    return f"file:{path}" if fmt else path


def upload_probe_cmd(path: str, fmt: str) -> list[str]:
    """Полный разбор чужого файла: потоки, обложки, поворот, цвет — с пределами.

    -count_packets пересчитывает пакеты каждой дорожки чтением файла (без
    декодирования, на 90 МБ — доли секунды): число кадров в заголовке может
    быть любым, а по нему решается, не слишком ли файл дорог для склейки.
    """
    return ["ffprobe", "-v", "error", "-hide_banner",
            "-probesize", UPLOAD_PROBE_SIZE, "-analyzeduration", UPLOAD_ANALYZE_US,
            *input_args(fmt), "-count_packets", "-show_streams", "-show_format", "-of", "json",
            input_path(path, fmt)]


def upload_header_cmd(path: str, fmt: str) -> list[str]:
    """Только заголовки контейнера — без декодеров (-nofind_stream_info).

    Нужен, когда строгий разбор не открыл файл: ffprobe со списком декодеров
    падает на дорожке вне списка (ProRes с айфона), и без этого человек прочёл
    бы «файл повреждён» вместо «формат видео не подходит».
    """
    if fmt not in UPLOAD_FORMATS:
        raise ValueError(f"unknown upload format {fmt!r}")
    return ["ffprobe", "-v", "error", "-hide_banner",
            "-probesize", UPLOAD_PROBE_SIZE, "-analyzeduration", UPLOAD_ANALYZE_US,
            "-protocol_whitelist", "file", "-f", fmt, "-nofind_stream_info",
            "-show_entries", "stream=codec_type,codec_name", "-of", "json", input_path(path, fmt)]


def upload_video_codecs(path: str, fmt: str) -> list[str] | None:
    """Кодеки видеодорожек по заголовкам; None — не читаются и заголовки."""
    try:
        result = _run(upload_header_cmd(path, fmt), UPLOAD_PROBE_TIMEOUT_S)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    try:
        data = json.loads(result.stdout or b"{}") or {}
        return [str(s.get("codec_name") or "") for s in data.get("streams") or []
                if isinstance(s, dict) and s.get("codec_type") == "video"]
    except (ValueError, TypeError, AttributeError):
        return None


def _rotation(stream: dict) -> int:
    """Поворот для показа по часовой (0/90/180/270): матрица кадра, иначе старый тег rotate."""
    value = None
    for item in stream.get("side_data_list") or []:
        if isinstance(item, dict) and item.get("rotation") is not None:
            try:
                # ffprobe пишет угол матрицы против часовой (iPhone вертикально: -90).
                value = -float(item["rotation"])
            except (TypeError, ValueError):
                continue
            break
    if value is None:
        try:
            value = float((stream.get("tags") or {}).get("rotate"))
        except (TypeError, ValueError):
            return 0
    # Тег rotate — любая строка файла: «inf» уронил бы int() с OverflowError.
    if not math.isfinite(value):
        return 0
    return int(round(value / 90.0)) * 90 % 360


def _count(value) -> int | None:
    """Целое неотрицательное число из ответа ffprobe (там числа — строками)."""
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _cover(stream: dict) -> bool:
    disposition = stream.get("disposition") or {}
    return isinstance(disposition, dict) and bool(disposition.get("attached_pic"))


def parse_probe(raw: bytes | str, *, strict: bool = False) -> Probe:
    """Разбор ответа ffprobe. Длительность — видеопотока, иначе контейнера:
    звук бывает длиннее картинки, а по нему следующий фрагмент встал бы позже.

    Обложка (attached_pic) — не видео. strict — полный разбор (-show_streams)
    своего видео человека: звук берётся только с кодеком из списка
    (UPLOAD_AUDIO_CODECS), прочий — как нет звука: фрагмент получит тишину, а
    не сбой, и чужой декодер не запустится. frames — пакеты картинки из
    -count_packets.
    """
    data = json.loads(raw or b"{}") or {}
    streams = [s for s in data.get("streams") or [] if isinstance(s, dict)]
    videos = [s for s in streams if s.get("codec_type") == "video" and not _cover(s)]
    video = videos[0] if videos else None
    audios = [s for s in streams if s.get("codec_type") == "audio"
              and (not strict or str(s.get("codec_name") or "") in UPLOAD_AUDIO_CODECS)]
    audio_stream = audios[0] if audios else None
    duration = None
    for value in ((video or {}).get("duration"), (data.get("format") or {}).get("duration")):
        number = _seconds(value)
        if number:
            duration = number
            break
    width = int(video["width"]) if video and video.get("width") else None
    height = int(video["height"]) if video and video.get("height") else None

    def index(stream):
        value = (stream or {}).get("index")
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None

    return Probe(duration=duration, width=width, height=height, audio=audio_stream is not None,
                 video=video is not None, codec=str((video or {}).get("codec_name") or ""),
                 video_streams=len(videos), video_index=index(video),
                 audio_index=index(audio_stream), rotation=_rotation(video or {}),
                 hdr=str((video or {}).get("color_transfer") or "") in HDR_TRANSFERS,
                 frames=_count((video or {}).get("nb_read_packets")) if strict else None,
                 container_duration=_seconds((data.get("format") or {}).get("duration")))


def _seconds(value) -> float | None:
    """Положительная конечная длительность из ответа ffprobe (там числа — строками) или None."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return round(number, 3) if math.isfinite(number) and number > 0 else None


def probe(path: str, fmt: str = "", timeout: float | None = None) -> Probe | None:
    """Что лежит в файле. None — ffprobe не смог его прочитать.

    fmt — своё видео человека: полный разбор с заданным демуксером и пределами.
    timeout — меньше обычного потолка, когда общий срок склейки уже близко.
    """
    if fmt:
        cmd, limit = upload_probe_cmd(path, fmt), UPLOAD_PROBE_TIMEOUT_S
    else:
        cmd, limit = probe_cmd(path), PROBE_TIMEOUT_S
    try:
        result = _run(cmd, limit if timeout is None else min(limit, timeout))
    except (OSError, subprocess.TimeoutExpired):
        logger.warning("склейка: ffprobe не отработал на %s", path, exc_info=True)
        return None
    if result.returncode != 0:
        logger.warning("склейка: ffprobe rc=%s на %s: %s", result.returncode, path, _tail(result.stderr))
        return None
    try:
        return parse_probe(result.stdout, strict=bool(fmt))
    except (ValueError, TypeError, AttributeError, OverflowError):
        # Ответ разбора — данные чужого файла: что бы в них ни было, это «не
        # читается», а не 500 загрузки.
        return None


# ---------------------------------------------------------------- свой трек (Build MA)

# Демуксеры своего трека (музыка склейки): выбираются по первым байтам файла
# (merge.audio.sniff), список закрытый — плейлист и «concat» не откроются.
AUDIO_FORMATS = ("mp3", "aac", "mov", "wav", "ogg", "matroska", "flac", "aiff", "caf", "asf", "amr")


@dataclass(frozen=True)
class AudioProbe:
    duration: float | None
    audio: bool
    codec: str = ""
    # Наибольшие частота и число каналов среди звуковых дорожек (None — не сказано).
    sample_rate: int | None = None
    channels: int | None = None


def audio_input_args(fmt: str) -> list[str]:
    """Чтение своего трека: заданный демуксер и декодеры из списка. Одни и те же
    у строгого разбора и у пересборки в mp3 (cartoon save_audio, input_options):
    иначе пересборка сама угадала бы формат и могла бы прочитать файл иначе,
    чем его проверили."""
    if fmt not in AUDIO_FORMATS:
        raise ValueError(f"unknown audio format {fmt!r}")
    return ["-codec_whitelist", ",".join(AUDIO_DECODERS), "-f", fmt]


def audio_probe_cmd(path: str, fmt: str) -> list[str]:
    """Строгий разбор своего трека: тот же вид, что у своих видео (пределы,
    протокол file, заданный демуксер, декодеры из списка, путь file:)."""
    return ["ffprobe", "-v", "error", "-hide_banner",
            "-probesize", UPLOAD_PROBE_SIZE, "-analyzeduration", UPLOAD_ANALYZE_US,
            "-protocol_whitelist", "file", *audio_input_args(fmt),
            "-show_streams", "-show_format", "-of", "json", f"file:{path}"]


def parse_audio_probe(raw: bytes | str) -> AudioProbe:
    """Звук трека: первая дорожка с кодеком из списка; длина — контейнера, иначе дорожки."""
    data = json.loads(raw or b"{}") or {}
    streams = [s for s in data.get("streams") or [] if isinstance(s, dict)]
    audios = [s for s in streams if s.get("codec_type") == "audio"
              and str(s.get("codec_name") or "") in AUDIO_TRACK_CODECS]
    stream = audios[0] if audios else {}
    duration = _seconds((data.get("format") or {}).get("duration")) or _seconds(stream.get("duration"))
    # Частота и каналы — по всем звуковым дорожкам: пересборка сама выбирает дорожку
    # (у ffmpeg — с наибольшим числом каналов), и проверять надо любую из них.
    sounds = [s for s in streams if s.get("codec_type") == "audio"]
    rates = [r for r in (_count(s.get("sample_rate")) for s in sounds) if r is not None]
    channels = [c for c in (_count(s.get("channels")) for s in sounds) if c is not None]
    return AudioProbe(duration=duration, audio=bool(audios), codec=str(stream.get("codec_name") or ""),
                      sample_rate=max(rates) if rates else None, channels=max(channels) if channels else None)


def probe_audio(path: str, fmt: str) -> AudioProbe | None:
    """Что в своём треке. None — ffprobe его не прочитал."""
    try:
        result = _run(audio_probe_cmd(path, fmt), UPLOAD_PROBE_TIMEOUT_S)
    except (OSError, subprocess.TimeoutExpired):
        logger.warning("склейка: ffprobe трека не отработал", exc_info=True)
        return None
    if result.returncode != 0:
        logger.info("склейка: трек не читается rc=%s: %s", result.returncode, _tail(result.stderr))
        return None
    try:
        return parse_audio_probe(result.stdout)
    except (ValueError, TypeError, AttributeError, OverflowError):
        return None


# ---------------------------------------------------------------- команды

def video_graph(fit: str, width: int, height: int, *, stream: str = "0:v",
                tonemap: bool = False, relabel: bool = False) -> str:
    """Граф картинки одного фрагмента: [0:v] → [v] нужного размера, 30 к/с.

    crop — заполнить кадр и срезать лишнее по центру. pad — вписать целиком, а
    поля закрыть тем же кадром, растянутым и размытым: чёрные полосы на
    вертикальном ролике в горизонтальной склейке смотрятся браком. Фон
    размывается в восьмую долю размера и растягивается обратно — в разы
    дешевле размытия полного кадра, а на глаз то же.

    stream — какой поток картинки брать (у своих видео — номер из разбора:
    обложка в файле может стоять раньше видео); tonemap — HDR в SDR; relabel —
    HDR без перевода, только метка bt709 (запасной путь).
    fps выдаёт ровные 30 кадров в секунду и из переменной частоты телефона.

    HDR переводится уже после fps и уменьшения кадра до размера склейки:
    tonemap считает в плавающей точке, и 4K60 с iPhone на полном кадре и
    полной частоте шло втрое дольше — минута такого ролика подбиралась к
    потолку фрагмента, а три — к сроку всей склейки.
    """
    head = f"[{stream}]fps={FPS},"
    if tonemap or relabel:
        mode = "increase" if fit == FIT_CROP else "decrease"
        head += (f"scale={width}:{height}:force_original_aspect_ratio={mode},"
                 + (TONEMAP if tonemap else RELABEL_BT709) + ",")
    if fit == FIT_CROP:
        return (f"{head}scale={width}:{height}:force_original_aspect_ratio=increase,"
                f"crop={width}:{height},setsar=1,format=yuv420p[v]")
    small_w, small_h = width // 8, height // 8
    return (f"{head}setsar=1,split=2[bgsrc][fgsrc];"
            f"[bgsrc]scale={small_w}:{small_h}:force_original_aspect_ratio=increase,"
            f"crop={small_w}:{small_h},boxblur=8:2,scale={width}:{height},setsar=1[bg];"
            f"[fgsrc]scale={width}:{height}:force_original_aspect_ratio=decrease,setsar=1[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2,format=yuv420p[v]")


def audio_graph(stream: str = "0:a", cap_s: float | None = None) -> str:
    """Звук фрагмента в общий вид; apad + -t добивают тишиной до конца картинки.

    cap_s — потолок звука своего видео человека по счёту сэмплов. -t режет по
    меткам времени, а их пишет файл: в Matroska с обнулёнными метками кластеров
    или в mov с нулевыми шагами stts звук часами не доходит до -t (полчаса Opus
    в 10-секундном ролике — 47 с работы и 28 МБ части вместо секунды). Сэмплы
    считает atrim=end_sample, метки он не трогает: у честного файла сдвиг звука
    от картинки остаётся как был (asetpts=N/SR/TB сдвинул бы его к нулю).
    """
    cap = f"atrim=end_sample={int(math.ceil(float(cap_s) * AUDIO_RATE))}," if cap_s else ""
    return (f"[{stream}]aresample={AUDIO_RATE},aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"{cap}apad[a]")


def _encode_args() -> list[str]:
    # Одинаковые настройки у всех частей — условие склейки без перекодирования.
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(CRF),
            "-profile:v", "high", "-level:v", "4.0", "-pix_fmt", "yuv420p", "-g", str(FPS * 2),
            "-c:a", "aac", "-b:a", AUDIO_BITRATE, "-ar", str(AUDIO_RATE), "-ac", "2",
            "-threads", THREADS]


def normalize_cmd(src: str, dst: str, *, aspect: str, fit: str, duration: float,
                  has_audio: bool, fmt: str = "", video_index: int | None = None,
                  audio_index: int | None = None, hdr: bool = False,
                  tonemap: bool = True) -> list[str]:
    """Один фрагмент → часть склейки: кадр формата, 30 к/с, звук 48 кГц стерео.

    Немому фрагменту добавляется тишина (второй вход anullsrc): у всех частей
    должна быть звуковая дорожка, иначе соединение без перекодирования
    невозможно, а concat-фильтр с a=1 падает. -t — по длине картинки: звук
    длиннее режется, короче — добивается тишиной.

    fmt — своё видео человека (строгое чтение, см. input_args); HDR-часть
    помечается как bt709 (и в кадре, и в параметрах кодера): иначе метка
    PQ/HLG первой части досталась бы всей склейке, и плеер показал бы её с
    чужими цветами.
    """
    width, height = TARGETS[aspect]
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y"]
    if fmt:
        cmd += input_args(fmt)
    cmd += ["-i", input_path(src, fmt)]
    stream = f"0:{video_index}" if video_index is not None else "0:v"
    graph = video_graph(fit, width, height, stream=stream, tonemap=hdr and tonemap,
                        relabel=hdr and not tonemap)
    if has_audio:
        # Своему видео — потолок по сэмплам (секунда сверх -t: честный звук он не режет);
        # наши файлы — команда до байта прежняя.
        graph += ";" + audio_graph(f"0:{audio_index}" if audio_index is not None else "0:a",
                                   float(duration) + AUDIO_CAP_SLACK_S if fmt else None)
        maps = ["-map", "[v]", "-map", "[a]"]
    else:
        cmd += ["-f", "lavfi", "-i", f"anullsrc=r={AUDIO_RATE}:cl=stereo"]
        maps = ["-map", "[v]", "-map", "1:a:0"]
    colors = (["-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709"]
              if hdr else [])
    return cmd + ["-filter_complex", graph, *maps, "-t", f"{float(duration):.3f}",
                  *_encode_args(), *colors, "-movflags", "+faststart", dst]


def concat_list(names: list[str]) -> str:
    """Список для concat-демуксера. Имена — наши (part000.mp4), рядом со списком."""
    return "".join(f"file '{name}'\n" for name in names)


def join_copy_cmd(list_path: str, dst: str) -> list[str]:
    return ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-f", "concat", "-safe", "0", "-i", list_path,
            "-c", "copy", "-movflags", "+faststart", dst]


def join_reencode_cmd(parts: list[str], dst: str) -> list[str]:
    """Запасной путь: один граф concat-фильтра. У всех частей есть звук (normalize_cmd)."""
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y"]
    for part in parts:
        cmd += ["-i", part]
    streams = "".join(f"[{i}:v:0][{i}:a:0]" for i in range(len(parts)))
    graph = f"{streams}concat=n={len(parts)}:v=1:a=1[v][a]"
    return cmd + ["-filter_complex", graph, "-map", "[v]", "-map", "[a]",
                  *_encode_args(), "-movflags", "+faststart", dst]


def poster_cmd(src: str, dst: str, *, at: float = 0.5, fmt: str = "",
               video_index: int | None = None) -> list[str]:
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y"]
    if fmt:
        cmd += input_args(fmt)
    cmd += ["-ss", f"{at:.2f}", "-i", input_path(src, fmt)]
    if video_index is not None:
        cmd += ["-map", f"0:{video_index}"]
    return cmd + ["-frames:v", "1", "-vf", f"scale={POSTER_WIDTH}:-2", "-q:v", "3", dst]


# ---------------------------------------------------------------- звук (Build MA)

@dataclass(frozen=True)
class AudioMix:
    """Звук склейки: звук роликов с громкостью, голос с фрагмента, музыка на всю длину.

    voice и music — пути к нашим mp3 (save_audio), "" — дорожки нет.
    voice_fragment — номер фрагмента (с 0), с начала которого звучит голос.
    expected_s — ожидаемая длина склейки: из неё заранее оценивается сведение.
    """

    clip_volume: float = 1.0
    voice: str = ""
    voice_volume: float = 1.0
    voice_duration: float = 0.0
    voice_fragment: int = 0
    music: str = ""
    music_volume: float = 0.35
    expected_s: float = 0.0

    @property
    def needed(self) -> bool:
        return bool(self.voice or self.music) or self.clip_volume != 1.0


def mix_timeout(duration: float) -> float:
    return max(MIX_MIN_TIMEOUT_S, float(duration or 0) * MIX_TIMEOUT_PER_S)


def _track_input(path: str, *, loop: bool = False) -> list[str]:
    # Свой трек человека уже пересобран в mp3 нашим ffmpeg, но читаем строго,
    # как любой файл на входе склейки.
    return ["-protocol_whitelist", "file", "-codec_whitelist", ",".join(TRACK_DECODERS), "-f", "mp3",
            *(["-stream_loop", "-1"] if loop else []), "-i", f"file:{path}"]


def _num(value: float) -> str:
    return f"{float(value):.3f}"


def music_volume_expr(volume: float, voice_window: tuple[float, float] | None) -> str:
    """Громкость музыки во времени: ровная, а под голосом — четверть (огибающая).

    Почему огибающая, а не sidechaincompress. Голос за кадром идёт фразами с
    паузами: компрессор по голосу отпускал бы музыку в каждой паузе («качели»),
    и глубина приглушения зависела бы от громкости самого голоса (тихий голос
    почти не приглушал бы). Огибающая по окну голоса — как авто-приглушение в
    видеоредакторах: музыка ровно тише всё время, пока звучит голос, с плавным
    спуском и подъёмом. Работает в любом ffmpeg (volume с eval=frame), проверено
    на 7.1 — scratch/MA/real_mix_check.py.
    """
    if voice_window is None:
        return f"volume={float(volume):.3f}"
    start, end = voice_window
    depth = 1.0 - DUCK_GAIN
    return (f"volume=volume='{float(volume):.3f}*(1-{depth:.3f}"
            f"*clip((t-({_num(start - DUCK_DOWN_S)}))/{DUCK_DOWN_S},0,1)"
            f"*clip((({_num(end + DUCK_UP_S)})-t)/{DUCK_UP_S},0,1))':eval=frame")


def mix_cmd(video: str, dst: str, *, duration: float, mix: AudioMix, voice_start: float = 0.0) -> list[str]:
    """Свести звук склеенного ролика: картинка — копией, звук — заново (AAC 48 кГц стерео).

    Длина итога — ровно до конца картинки (duration — от нуля ролика): голос и
    музыка за концом обрезаются, звук роликов задаёт длину смеси (amix
    duration=first). Голос сдвигается adelay на первый кадр своего фрагмента
    (voice_start — от нуля ролика); музыка повторяется по кругу
    (-stream_loop), режется по длине, с вступлением и концовкой по секунде и
    приглушается под голосом (music_volume_expr).
    """
    length = max(0.001, float(duration))
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", video]
    norm = f"aresample={AUDIO_RATE},aformat=sample_fmts=fltp:channel_layouts=stereo"
    # Звук склеенного ролика — по его меткам времени (CLIP_ALIGN), а не подряд по сэмплам.
    chains = [f"[0:a]aresample={AUDIO_RATE}:{CLIP_ALIGN},aformat=sample_fmts=fltp:channel_layouts=stereo,"
              f"volume={float(mix.clip_volume):.3f}"]
    labels = ["[clip]"]
    window = None
    index = 1
    if mix.voice:
        cmd += _track_input(mix.voice)
        start = max(0.0, float(voice_start))
        chain = f"[{index}:a]{norm},asetpts=N/SR/TB,volume={float(mix.voice_volume):.3f}"
        delay = int(round(start * 1000))
        if delay > 0:
            chain += f",adelay=delays={delay}:all=1"
        chains.append(chain)
        labels.append("[voice]")
        window = (start, min(length, start + max(0.0, float(mix.voice_duration or 0))))
        index += 1
    if mix.music:
        cmd += _track_input(mix.music, loop=True)
        fade = min(MUSIC_FADE_S, length / 2)
        chains.append(f"[{index}:a]{norm},asetpts=N/SR/TB,atrim=duration={_num(length)},"
                      f"afade=t=in:st=0:d={_num(fade)},afade=t=out:st={_num(length - fade)}:d={_num(fade)},"
                      + (f"asetnsamples=n={DUCK_FRAME}:p=0," if window else "")
                      + music_volume_expr(mix.music_volume, window))
        labels.append("[music]")
    if len(labels) == 1:
        graph = chains[0] + "[aout]"
    else:
        graph = ";".join(chain + label for chain, label in zip(chains, labels))
        graph += (";" + "".join(labels) + f"amix=inputs={len(labels)}:duration=first:dropout_transition=0"
                  f":normalize=0,alimiter=limit={LIMIT}:level=0:latency=1[aout]")
    return cmd + ["-filter_complex", graph, "-map", "0:v:0", "-map", "[aout]",
                  "-c:v", "copy", "-c:a", "aac", "-b:a", AUDIO_BITRATE, "-ar", str(AUDIO_RATE), "-ac", "2",
                  "-threads", THREADS, "-t", _num(length), "-movflags", "+faststart", dst]


def _part_length(path: str, fallback: float, timeout: float = PROBE_TIMEOUT_S) -> float:
    """Длина готовой части так, как её берёт concat: контейнер, иначе картинка, иначе -t."""
    info = probe(path, timeout=timeout)
    if info is not None:
        return info.container_duration or info.duration or fallback
    return fallback


def video_start_cmd(path: str) -> list[str]:
    return ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=start_time",
            "-of", "json", path]


def video_start(path: str, timeout: float = PROBE_TIMEOUT_S) -> float:
    """Метка первого кадра картинки (с). Соединение копией сдвигает весь ролик на
    задержку кодера AAC первой части (~21 мс): с неё начинается и первый фрагмент."""
    try:
        result = _run(video_start_cmd(path), timeout)
        if result.returncode != 0:
            return 0.0
        streams = (json.loads(result.stdout or b"{}") or {}).get("streams") or [{}]
        value = float(streams[0].get("start_time"))
    except (OSError, subprocess.TimeoutExpired, ValueError, TypeError, AttributeError, IndexError):
        return 0.0
    # Больше пары кадров сдвига не бывает: иное — ошибка разбора, а не начало ролика.
    return value if math.isfinite(value) and 0 <= value < 1 else 0.0


def _mix(out: str, info: Probe, mix: AudioMix, *, workdir: str, parts: list[str], lengths: list[float],
         deadline: float | None) -> Rendered:
    # Голос — с первого кадра своего фрагмента: concat (и демуксер, и запасной
    # фильтр) кладёт каждую часть сразу за длиной предыдущей (свои видео в
    # начале и в конце — такие же части), а весь ролик начинается с метки
    # первого кадра. Номер за концом списка — последний фрагмент.
    # Разборы тоже в общем сроке склейки: обычно это миллисекунды, но время на
    # сведение отложено заранее, и разбор не должен съесть его целиком.
    head = video_start(out, _left(deadline, PROBE_TIMEOUT_S))
    start = head
    if mix.voice and mix.voice_fragment > 0 and parts:
        upto = min(int(mix.voice_fragment), len(parts) - 1)
        start += sum(_part_length(os.path.join(workdir, parts[i]), lengths[i], _left(deadline, PROBE_TIMEOUT_S))
                     for i in range(upto))
    # Конец звука — конец картинки: голос и музыка за ним обрезаются.
    length = head + info.duration
    dst = os.path.join(workdir, "mixed.mp4")
    try:
        result = _run(mix_cmd(out, dst, duration=length, mix=mix, voice_start=round(start, 3)),
                      _left(deadline, mix_timeout(length)))
    except subprocess.TimeoutExpired:
        raise RenderError(MSG_TOO_SLOW, "сведение звука: таймаут ffmpeg", code="too_slow") from None
    if not _ok(result, dst):
        raise RenderError(MSG_MIX_FAILED, f"сведение: rc={result.returncode} {_tail(result.stderr)}",
                          code="mix_failed")
    final = probe(dst, timeout=_left(deadline, PROBE_TIMEOUT_S))
    if final is None or not final.duration or not final.audio:
        raise RenderError(MSG_MIX_FAILED, "итог сведения не читается ffprobe", code="mix_failed")
    return Rendered(path=dst, duration=final.duration)


# ---------------------------------------------------------------- сборка

def _ok(result, dst: str) -> bool:
    return result.returncode == 0 and os.path.isfile(dst) and os.path.getsize(dst) > 0


def fragment_timeout(duration: float) -> float:
    return max(FRAGMENT_MIN_TIMEOUT_S, float(duration) * FRAGMENT_TIMEOUT_PER_S)


def _left(deadline: float | None, wanted: float) -> float:
    """Сколько дать команде: её потолок, но не дальше общего срока склейки."""
    if deadline is None:
        return wanted
    left = deadline - time.monotonic()
    if left <= 1:
        raise RenderError(MSG_TOO_SLOW, "общий срок склейки вышел", code="too_slow")
    return min(wanted, left)


def render(paths: list, *, aspect: str, fit: str, workdir: str,
           progress: Callable[[str, int, int], None] | None = None,
           deadline: float | None = None, audio: AudioMix | None = None) -> Rendered:
    """Склеить файлы по порядку в workdir/merged.mp4. Бросает RenderError.

    paths — пути к нашим файлам или Input (своё видео человека с демуксером).
    progress(stage, done, total) зовётся перед каждым фрагментом, перед
    соединением и перед сведением звука; deadline — time.monotonic(), после
    которого склейку бросаем. audio — звук склейки (Build MA): если он нужен,
    итог — workdir/mixed.mp4, а фрагментам и соединению срок короче на оценку
    сведения (mix_timeout).
    """
    if aspect not in TARGETS:
        raise ValueError(f"unknown aspect {aspect!r}")
    mix = audio if audio is not None and audio.needed else None
    if mix is not None and deadline is not None:
        deadline_video = deadline - mix_timeout(mix.expected_s)
    else:
        deadline_video = deadline
    total = len(paths)
    parts: list[str] = []
    lengths: list[float] = []
    for index, item in enumerate(paths):
        n = index + 1
        src, fmt = (item.path, item.fmt) if isinstance(item, Input) else (item, "")
        if progress:
            progress("normalizing", index, total)
        info = probe(src, fmt)
        if info is None or not info.duration:
            raise RenderError(MSG_UNREADABLE.format(n=n), f"ffprobe: {src}",
                              code="fragment_unreadable", fragment=n)
        if not info.video:
            raise RenderError(MSG_NO_VIDEO.format(n=n), f"нет видеопотока: {src}",
                              code="fragment_no_video", fragment=n)
        name = f"part{index:03d}.mp4"
        dst = os.path.join(workdir, name)
        options = dict(aspect=aspect, fit=fit, duration=info.duration, has_audio=info.audio,
                       fmt=fmt, video_index=info.video_index, audio_index=info.audio_index,
                       hdr=info.hdr)
        try:
            timeout = fragment_timeout(info.duration)
            result = _run(normalize_cmd(src, dst, **options), _left(deadline_video, timeout))
            if info.hdr and not _ok(result, dst):
                # Нет zscale в сборке ffmpeg или он не понял цвет — без перевода
                # в SDR: краски бледнее, но фрагмент в склейке, а не отказ.
                logger.warning("склейка: HDR фрагмента %s без tonemap (rc=%s): %s", n,
                               result.returncode, _tail(result.stderr))
                result = _run(normalize_cmd(src, dst, tonemap=False, **options),
                              _left(deadline_video, timeout))
        except subprocess.TimeoutExpired:
            raise RenderError(MSG_TOO_SLOW, f"фрагмент {n}: таймаут ffmpeg", code="too_slow") from None
        if not _ok(result, dst):
            raise RenderError(MSG_FRAGMENT_FAILED.format(n=n),
                              f"фрагмент {n}: rc={result.returncode} {_tail(result.stderr)}",
                              code="fragment_failed", fragment=n)
        parts.append(name)
        lengths.append(info.duration)

    if progress:
        progress("joining", total, total)
    out = os.path.join(workdir, "merged.mp4")
    list_path = os.path.join(workdir, "parts.txt")
    with open(list_path, "w", encoding="utf-8") as fh:
        fh.write(concat_list(parts))
    try:
        result = _run(join_copy_cmd(list_path, out), _left(deadline_video, JOIN_TIMEOUT_S))
        joined = _ok(result, out)
        if not joined:
            logger.warning("склейка: соединение без перекодирования не вышло (rc=%s): %s",
                           result.returncode, _tail(result.stderr))
            result = _run(join_reencode_cmd([os.path.join(workdir, p) for p in parts], out),
                          _left(deadline_video, JOIN_TIMEOUT_S))
            joined = _ok(result, out)
    except subprocess.TimeoutExpired:
        raise RenderError(MSG_TOO_SLOW, "соединение: таймаут ffmpeg", code="too_slow") from None
    if not joined:
        raise RenderError(MSG_JOIN_FAILED, f"соединение: rc={result.returncode} {_tail(result.stderr)}",
                          code="join_failed")
    info = probe(out)
    if info is None or not info.duration:
        raise RenderError(MSG_JOIN_FAILED, "итог не читается ffprobe", code="join_failed")
    if mix is None:
        return Rendered(path=out, duration=info.duration)
    if progress:
        progress("mixing", total, total)
    return _mix(out, info, mix, workdir=workdir, parts=parts, lengths=lengths, deadline=deadline)


def make_poster(src: str, dst: str, duration: float | None = None) -> bool:
    """Обложка склейки (JPEG 480 px). Осечка обложки не портит готовый ролик."""
    at = 0.5 if not duration or duration > 1 else 0.0
    try:
        return _ok(_run(poster_cmd(src, dst, at=at), POSTER_TIMEOUT_S), dst)
    except (OSError, subprocess.TimeoutExpired):
        logger.warning("склейка: обложка не сделалась", exc_info=True)
        return False


def make_upload_poster(src: str, dst: str, *, fmt: str, video_index: int | None,
                       duration: float | None = None) -> bool:
    """Обложка своего видео (JPEG 480 px) — заодно проверка, что кадр декодируется:
    файл с честным заголовком и битыми кадрами иначе всплыл бы только в склейке."""
    at = 0.5 if not duration or duration > 1 else 0.0
    try:
        return _ok(_run(poster_cmd(src, dst, at=at, fmt=fmt, video_index=video_index),
                        UPLOAD_POSTER_TIMEOUT_S), dst)
    except (OSError, subprocess.TimeoutExpired):
        logger.warning("склейка: обложка своего видео не сделалась", exc_info=True)
        return False


__all__ = ["RenderError", "Probe", "Input", "Rendered", "probe", "parse_probe", "render",
           "make_poster", "make_upload_poster", "video_graph", "audio_graph", "normalize_cmd",
           "join_copy_cmd", "join_reencode_cmd", "poster_cmd", "concat_list", "fragment_timeout",
           "input_args", "upload_probe_cmd", "AudioMix", "AudioProbe", "mix_cmd", "mix_timeout",
           "music_volume_expr", "audio_probe_cmd", "parse_audio_probe",
           "probe_audio"]
