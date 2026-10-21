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

from .config import FIT_CROP, TARGETS, UPLOAD_AUDIO_CODECS, UPLOAD_DECODERS

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

MSG_UNREADABLE = "Фрагмент №{n} не читается — уберите его из склейки и попробуйте снова."
MSG_NO_VIDEO = "Во фрагменте №{n} нет видео — уберите его из склейки и попробуйте снова."
MSG_FRAGMENT_FAILED = "Не получилось обработать фрагмент №{n} — попробуйте ещё раз или уберите его."
MSG_JOIN_FAILED = "Не получилось склеить фрагменты — попробуйте ещё раз."
MSG_TOO_SLOW = "Склейка заняла слишком долго — кредиты не списаны, попробуйте ещё раз."


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
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if number > 0:
            duration = round(number, 3)
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
                 frames=_count((video or {}).get("nb_read_packets")) if strict else None)


def probe(path: str, fmt: str = "") -> Probe | None:
    """Что лежит в файле. None — ffprobe не смог его прочитать.

    fmt — своё видео человека: полный разбор с заданным демуксером и пределами.
    """
    if fmt:
        cmd, timeout = upload_probe_cmd(path, fmt), UPLOAD_PROBE_TIMEOUT_S
    else:
        cmd, timeout = probe_cmd(path), PROBE_TIMEOUT_S
    try:
        result = _run(cmd, timeout)
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


def audio_graph(stream: str = "0:a") -> str:
    """Звук фрагмента в общий вид; apad + -t добивают тишиной до конца картинки."""
    return (f"[{stream}]aresample={AUDIO_RATE},aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"apad[a]")


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
        graph += ";" + audio_graph(f"0:{audio_index}" if audio_index is not None else "0:a")
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
           deadline: float | None = None) -> Rendered:
    """Склеить файлы по порядку в workdir/merged.mp4. Бросает RenderError.

    paths — пути к нашим файлам или Input (своё видео человека с демуксером).
    progress(stage, done, total) зовётся перед каждым фрагментом и перед
    соединением; deadline — time.monotonic(), после которого склейку бросаем.
    """
    if aspect not in TARGETS:
        raise ValueError(f"unknown aspect {aspect!r}")
    total = len(paths)
    parts: list[str] = []
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
            result = _run(normalize_cmd(src, dst, **options), _left(deadline, timeout))
            if info.hdr and not _ok(result, dst):
                # Нет zscale в сборке ffmpeg или он не понял цвет — без перевода
                # в SDR: краски бледнее, но фрагмент в склейке, а не отказ.
                logger.warning("склейка: HDR фрагмента %s без tonemap (rc=%s): %s", n,
                               result.returncode, _tail(result.stderr))
                result = _run(normalize_cmd(src, dst, tonemap=False, **options),
                              _left(deadline, timeout))
        except subprocess.TimeoutExpired:
            raise RenderError(MSG_TOO_SLOW, f"фрагмент {n}: таймаут ffmpeg", code="too_slow") from None
        if not _ok(result, dst):
            raise RenderError(MSG_FRAGMENT_FAILED.format(n=n),
                              f"фрагмент {n}: rc={result.returncode} {_tail(result.stderr)}",
                              code="fragment_failed", fragment=n)
        parts.append(name)

    if progress:
        progress("joining", total, total)
    out = os.path.join(workdir, "merged.mp4")
    list_path = os.path.join(workdir, "parts.txt")
    with open(list_path, "w", encoding="utf-8") as fh:
        fh.write(concat_list(parts))
    try:
        result = _run(join_copy_cmd(list_path, out), _left(deadline, JOIN_TIMEOUT_S))
        joined = _ok(result, out)
        if not joined:
            logger.warning("склейка: соединение без перекодирования не вышло (rc=%s): %s",
                           result.returncode, _tail(result.stderr))
            result = _run(join_reencode_cmd([os.path.join(workdir, p) for p in parts], out),
                          _left(deadline, JOIN_TIMEOUT_S))
            joined = _ok(result, out)
    except subprocess.TimeoutExpired:
        raise RenderError(MSG_TOO_SLOW, "соединение: таймаут ffmpeg", code="too_slow") from None
    if not joined:
        raise RenderError(MSG_JOIN_FAILED, f"соединение: rc={result.returncode} {_tail(result.stderr)}",
                          code="join_failed")
    info = probe(out)
    if info is None or not info.duration:
        raise RenderError(MSG_JOIN_FAILED, "итог не читается ffprobe", code="join_failed")
    return Rendered(path=out, duration=info.duration)


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
           "input_args", "upload_probe_cmd"]
