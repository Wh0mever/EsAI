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
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from typing import Callable

from .config import FIT_CROP, TARGETS

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


def parse_probe(raw: bytes | str) -> Probe:
    """Разбор ответа ffprobe. Длительность — видеопотока, иначе контейнера:
    звук бывает длиннее картинки, а по нему следующий фрагмент встал бы позже."""
    data = json.loads(raw or b"{}") or {}
    streams = data.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = any(s.get("codec_type") == "audio" for s in streams)
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
    return Probe(duration=duration, width=width, height=height, audio=audio, video=video is not None)


def probe(path: str) -> Probe | None:
    """Что лежит в файле. None — ffprobe не смог его прочитать."""
    try:
        result = _run(probe_cmd(path), PROBE_TIMEOUT_S)
    except (OSError, subprocess.TimeoutExpired):
        logger.warning("склейка: ffprobe не отработал на %s", path, exc_info=True)
        return None
    if result.returncode != 0:
        logger.warning("склейка: ffprobe rc=%s на %s: %s", result.returncode, path, _tail(result.stderr))
        return None
    try:
        return parse_probe(result.stdout)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------- команды

def video_graph(fit: str, width: int, height: int) -> str:
    """Граф картинки одного фрагмента: [0:v] → [v] нужного размера, 30 к/с.

    crop — заполнить кадр и срезать лишнее по центру. pad — вписать целиком, а
    поля закрыть тем же кадром, растянутым и размытым: чёрные полосы на
    вертикальном ролике в горизонтальной склейке смотрятся браком. Фон
    размывается в восьмую долю размера и растягивается обратно — в разы
    дешевле размытия полного кадра, а на глаз то же.
    """
    if fit == FIT_CROP:
        return (f"[0:v]fps={FPS},scale={width}:{height}:force_original_aspect_ratio=increase,"
                f"crop={width}:{height},setsar=1,format=yuv420p[v]")
    small_w, small_h = width // 8, height // 8
    return (f"[0:v]fps={FPS},setsar=1,split=2[bgsrc][fgsrc];"
            f"[bgsrc]scale={small_w}:{small_h}:force_original_aspect_ratio=increase,"
            f"crop={small_w}:{small_h},boxblur=8:2,scale={width}:{height},setsar=1[bg];"
            f"[fgsrc]scale={width}:{height}:force_original_aspect_ratio=decrease,setsar=1[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2,format=yuv420p[v]")


def audio_graph() -> str:
    """Звук фрагмента в общий вид; apad + -t добивают тишиной до конца картинки."""
    return (f"[0:a]aresample={AUDIO_RATE},aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"apad[a]")


def _encode_args() -> list[str]:
    # Одинаковые настройки у всех частей — условие склейки без перекодирования.
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(CRF),
            "-profile:v", "high", "-level:v", "4.0", "-pix_fmt", "yuv420p", "-g", str(FPS * 2),
            "-c:a", "aac", "-b:a", AUDIO_BITRATE, "-ar", str(AUDIO_RATE), "-ac", "2",
            "-threads", THREADS]


def normalize_cmd(src: str, dst: str, *, aspect: str, fit: str, duration: float,
                  has_audio: bool) -> list[str]:
    """Один фрагмент → часть склейки: кадр формата, 30 к/с, звук 48 кГц стерео.

    Немому фрагменту добавляется тишина (второй вход anullsrc): у всех частей
    должна быть звуковая дорожка, иначе соединение без перекодирования
    невозможно, а concat-фильтр с a=1 падает. -t — по длине картинки: звук
    длиннее режется, короче — добивается тишиной.
    """
    width, height = TARGETS[aspect]
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", src]
    graph = video_graph(fit, width, height)
    if has_audio:
        graph += ";" + audio_graph()
        maps = ["-map", "[v]", "-map", "[a]"]
    else:
        cmd += ["-f", "lavfi", "-i", f"anullsrc=r={AUDIO_RATE}:cl=stereo"]
        maps = ["-map", "[v]", "-map", "1:a:0"]
    return cmd + ["-filter_complex", graph, *maps, "-t", f"{float(duration):.3f}",
                  *_encode_args(), "-movflags", "+faststart", dst]


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


def poster_cmd(src: str, dst: str, *, at: float = 0.5) -> list[str]:
    return ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-ss", f"{at:.2f}", "-i", src, "-frames:v", "1",
            "-vf", f"scale={POSTER_WIDTH}:-2", "-q:v", "3", dst]


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


def render(paths: list[str], *, aspect: str, fit: str, workdir: str,
           progress: Callable[[str, int, int], None] | None = None,
           deadline: float | None = None) -> Rendered:
    """Склеить файлы по порядку в workdir/merged.mp4. Бросает RenderError.

    progress(stage, done, total) зовётся перед каждым фрагментом и перед
    соединением; deadline — time.monotonic(), после которого склейку бросаем.
    """
    if aspect not in TARGETS:
        raise ValueError(f"unknown aspect {aspect!r}")
    total = len(paths)
    parts: list[str] = []
    for index, src in enumerate(paths):
        n = index + 1
        if progress:
            progress("normalizing", index, total)
        info = probe(src)
        if info is None or not info.duration:
            raise RenderError(MSG_UNREADABLE.format(n=n), f"ffprobe: {src}",
                              code="fragment_unreadable", fragment=n)
        if not info.video:
            raise RenderError(MSG_NO_VIDEO.format(n=n), f"нет видеопотока: {src}",
                              code="fragment_no_video", fragment=n)
        name = f"part{index:03d}.mp4"
        dst = os.path.join(workdir, name)
        cmd = normalize_cmd(src, dst, aspect=aspect, fit=fit, duration=info.duration,
                            has_audio=info.audio)
        try:
            result = _run(cmd, _left(deadline, fragment_timeout(info.duration)))
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


__all__ = ["RenderError", "Probe", "Rendered", "probe", "parse_probe", "render", "make_poster",
           "video_graph", "audio_graph", "normalize_cmd", "join_copy_cmd", "join_reencode_cmd",
           "poster_cmd", "concat_list", "fragment_timeout"]
