"""Команды ffmpeg склейки и порядок их запуска — без настоящего ffmpeg."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from unittest.mock import patch

from django.test import SimpleTestCase

from merge import render


def _probe_json(duration=5.0, audio=True, video=True, width=1280, height=720):
    streams = []
    if video:
        streams.append({"codec_type": "video", "width": width, "height": height,
                        "duration": str(duration)})
    if audio:
        streams.append({"codec_type": "audio", "duration": str(duration + 0.2)})
    return json.dumps({"streams": streams, "format": {"duration": str(duration + 0.2)}}).encode()


class FakeFFmpeg:
    """Подмена subprocess.run: ffprobe отвечает по таблице, ffmpeg «пишет» выход."""

    def __init__(self, *, durations=None, audio=True, fail=None, timeout=None):
        self.calls = []
        self.durations = durations or {}
        self.audio = audio
        self.fail = fail or (lambda cmd: False)
        self.timeout = timeout or (lambda cmd: False)

    def __call__(self, cmd, **kwargs):
        cmd = list(cmd)
        # На Linux ffmpeg идёт через «nice -n 10» (render.nice_prefix): смотрим на саму команду.
        if cmd and os.path.basename(cmd[0]) == "nice":
            cmd = cmd[3:]
        self.calls.append(cmd)
        if self.timeout(cmd):
            raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout"))
        if cmd[0] == "ffprobe":
            path = cmd[-1]
            duration = self.durations.get(os.path.basename(path), 5.0)
            if duration is None:
                return subprocess.CompletedProcess(cmd, 1, b"", b"Invalid data")
            audio = self.audio(path) if callable(self.audio) else self.audio
            return subprocess.CompletedProcess(cmd, 0, _probe_json(duration, audio=audio), b"")
        if self.fail(cmd):
            return subprocess.CompletedProcess(cmd, 1, b"", b"boom")
        with open(cmd[-1], "wb") as fh:
            fh.write(b"mp4")
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    def ffmpeg(self):
        return [c for c in self.calls if c[0] == "ffmpeg"]


class CommandBuilderTests(SimpleTestCase):
    def test_crop_graph(self):
        graph = render.video_graph("crop", 1280, 720)
        self.assertEqual(graph, "[0:v]fps=30,scale=1280:720:force_original_aspect_ratio=increase,"
                                "crop=1280:720,setsar=1,format=yuv420p[v]")

    def test_pad_graph_blurs_the_background(self):
        graph = render.video_graph("pad", 720, 1280)
        self.assertIn("split=2[bgsrc][fgsrc]", graph)
        self.assertIn("[bgsrc]scale=90:160:force_original_aspect_ratio=increase,crop=90:160,"
                      "boxblur=8:2,scale=720:1280", graph)
        self.assertIn("[fgsrc]scale=720:1280:force_original_aspect_ratio=decrease", graph)
        self.assertTrue(graph.endswith("[bg][fg]overlay=(W-w)/2:(H-h)/2,format=yuv420p[v]"))

    def test_normalize_with_audio(self):
        cmd = render.normalize_cmd("in.mp4", "out.mp4", aspect="1:1", fit="crop", duration=4.04,
                                   has_audio=True)
        self.assertEqual(cmd[:8], ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                                   "-i", "in.mp4"])
        graph = cmd[cmd.index("-filter_complex") + 1]
        self.assertIn("scale=960:960", graph)
        self.assertIn("[0:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,apad[a]",
                      graph)
        self.assertNotIn("anullsrc", " ".join(cmd))
        self.assertEqual(cmd[cmd.index("-t") + 1], "4.040")
        self.assertIn("[a]", cmd[cmd.index("-map", cmd.index("-map") + 1) + 1])
        for flag, value in (("-preset", "veryfast"), ("-c:v", "libx264"), ("-c:a", "aac"),
                            ("-ar", "48000"), ("-ac", "2"), ("-pix_fmt", "yuv420p")):
            self.assertEqual(cmd[cmd.index(flag) + 1], value)
        self.assertEqual(cmd[-1], "out.mp4")
        self.assertIn("+faststart", cmd)

    def test_normalize_silent_fragment_gets_silence(self):
        cmd = render.normalize_cmd("in.mp4", "out.mp4", aspect="16:9", fit="pad", duration=5,
                                   has_audio=False)
        self.assertEqual(cmd[cmd.index("-f") + 1], "lavfi")
        self.assertEqual(cmd[cmd.index("lavfi") + 2], "anullsrc=r=48000:cl=stereo")
        graph = cmd[cmd.index("-filter_complex") + 1]
        self.assertNotIn("[0:a]", graph)
        maps = [cmd[i + 1] for i, a in enumerate(cmd) if a == "-map"]
        self.assertEqual(maps, ["[v]", "1:a:0"])
        self.assertEqual(cmd[cmd.index("-t") + 1], "5.000")

    def test_unknown_aspect_is_a_bug(self):
        with self.assertRaises(KeyError):
            render.normalize_cmd("a", "b", aspect="4:3", fit="pad", duration=1, has_audio=True)

    def test_join_commands(self):
        self.assertEqual(render.concat_list(["part000.mp4", "part001.mp4"]),
                         "file 'part000.mp4'\nfile 'part001.mp4'\n")
        copy = render.join_copy_cmd("list.txt", "out.mp4")
        self.assertIn("concat", copy)
        self.assertEqual(copy[copy.index("-c") + 1], "copy")
        again = render.join_reencode_cmd(["a.mp4", "b.mp4", "c.mp4"], "out.mp4")
        self.assertEqual(again[again.index("-filter_complex") + 1],
                         "[0:v:0][0:a:0][1:v:0][1:a:0][2:v:0][2:a:0]concat=n=3:v=1:a=1[v][a]")

    def test_poster_command(self):
        cmd = render.poster_cmd("in.mp4", "p.jpg", at=0.5)
        self.assertEqual(cmd[cmd.index("-ss") + 1], "0.50")
        self.assertEqual(cmd[cmd.index("-vf") + 1], "scale=480:-2")

    def test_parse_probe(self):
        info = render.parse_probe(_probe_json(6.5, audio=False))
        self.assertEqual((info.duration, info.width, info.height, info.audio, info.video),
                         (6.5, 1280, 720, False, True))
        # Нет длительности у потока — берём контейнер.
        raw = json.dumps({"streams": [{"codec_type": "video"}], "format": {"duration": "3.2"}})
        self.assertEqual(render.parse_probe(raw).duration, 3.2)
        self.assertFalse(render.parse_probe(b"{}").video)

    def test_fragment_timeout(self):
        self.assertEqual(render.fragment_timeout(5), 120)
        self.assertEqual(render.fragment_timeout(30), 300)


class RenderRunTests(SimpleTestCase):
    def setUp(self):
        self.workdir = tempfile.mkdtemp(prefix="merge-render-")
        self.addCleanup(shutil.rmtree, self.workdir, True)
        self.srcs = []
        for name in ("a.mp4", "b.mp4", "c.mp4"):
            path = os.path.join(self.workdir, name)
            with open(path, "wb") as fh:
                fh.write(b"src")
            self.srcs.append(path)

    def _render(self, fake, **kw):
        with patch("merge.render.subprocess.run", side_effect=fake):
            return render.render(self.srcs, aspect=kw.pop("aspect", "16:9"),
                                 fit=kw.pop("fit", "pad"), workdir=self.workdir, **kw)

    def test_normalizes_each_then_joins_without_reencoding(self):
        fake = FakeFFmpeg(durations={"merged.mp4": 15.0})
        stages = []
        result = self._render(fake, progress=lambda *a: stages.append(a))
        self.assertEqual(result.duration, 15.0)
        self.assertEqual(result.path, os.path.join(self.workdir, "merged.mp4"))
        runs = fake.ffmpeg()
        self.assertEqual(len(runs), 4)
        for index, cmd in enumerate(runs[:3]):
            self.assertEqual(cmd[cmd.index("-i") + 1], self.srcs[index])
            self.assertTrue(cmd[-1].endswith(f"part{index:03d}.mp4"))
        self.assertIn("copy", runs[3])
        with open(os.path.join(self.workdir, "parts.txt"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "file 'part000.mp4'\nfile 'part001.mp4'\nfile 'part002.mp4'\n")
        self.assertEqual(stages, [("normalizing", 0, 3), ("normalizing", 1, 3),
                                  ("normalizing", 2, 3), ("joining", 3, 3)])

    def test_silent_fragment_detected_by_probe(self):
        fake = FakeFFmpeg(audio=lambda path: not path.endswith("b.mp4"))
        self._render(fake)
        runs = fake.ffmpeg()
        self.assertNotIn("anullsrc=r=48000:cl=stereo", runs[0])
        self.assertIn("anullsrc=r=48000:cl=stereo", runs[1])

    def test_copy_join_failure_falls_back_to_one_filter_graph(self):
        fake = FakeFFmpeg(fail=lambda cmd: "copy" in cmd)
        self._render(fake)
        last = fake.ffmpeg()[-1]
        self.assertIn("concat=n=3:v=1:a=1[v][a]", last[last.index("-filter_complex") + 1])

    def test_both_joins_fail(self):
        fake = FakeFFmpeg(fail=lambda cmd: cmd[-1].endswith("merged.mp4"))
        with self.assertRaises(render.RenderError) as ctx:
            self._render(fake)
        self.assertEqual(ctx.exception.message, "Не получилось склеить фрагменты — попробуйте ещё раз.")
        self.assertEqual(ctx.exception.code, "join_failed")

    def test_unreadable_fragment_is_named(self):
        fake = FakeFFmpeg(durations={"b.mp4": None})
        with self.assertRaises(render.RenderError) as ctx:
            self._render(fake)
        self.assertEqual(ctx.exception.message,
                         "Фрагмент №2 не читается — уберите его из склейки и попробуйте снова.")
        self.assertEqual((ctx.exception.code, ctx.exception.fragment), ("fragment_unreadable", 2))
        self.assertEqual(len(fake.ffmpeg()), 1)

    def test_failed_fragment_is_named(self):
        fake = FakeFFmpeg(fail=lambda cmd: cmd[-1].endswith("part002.mp4"))
        with self.assertRaises(render.RenderError) as ctx:
            self._render(fake)
        self.assertIn("№3", ctx.exception.message)
        self.assertEqual((ctx.exception.code, ctx.exception.fragment), ("fragment_failed", 3))

    def test_ffmpeg_timeout(self):
        fake = FakeFFmpeg(timeout=lambda cmd: cmd[0] == "ffmpeg")
        with self.assertRaises(render.RenderError) as ctx:
            self._render(fake)
        self.assertEqual(ctx.exception.message, render.MSG_TOO_SLOW)

    def test_deadline_caps_every_command(self):
        fake = FakeFFmpeg()
        with patch("merge.render.subprocess.run", side_effect=fake) as run, \
                patch("merge.render.time.monotonic", return_value=100.0):
            render.render(self.srcs, aspect="16:9", fit="crop", workdir=self.workdir, deadline=150.0)
        timeouts = [c.kwargs["timeout"] for c in run.call_args_list if c.args[0][0] == "ffmpeg"]
        self.assertTrue(all(t <= 50.0 for t in timeouts))

    def test_deadline_passed(self):
        fake = FakeFFmpeg()
        with patch("merge.render.subprocess.run", side_effect=fake), \
                patch("merge.render.time.monotonic", return_value=100.0), \
                self.assertRaises(render.RenderError) as ctx:
            render.render(self.srcs, aspect="16:9", fit="crop", workdir=self.workdir, deadline=100.5)
        self.assertEqual(ctx.exception.message, render.MSG_TOO_SLOW)

    def test_poster(self):
        fake = FakeFFmpeg()
        dst = os.path.join(self.workdir, "p.jpg")
        with patch("merge.render.subprocess.run", side_effect=fake):
            self.assertTrue(render.make_poster(self.srcs[0], dst, 0.4))
        self.assertEqual(fake.calls[0][fake.calls[0].index("-ss") + 1], "0.00")
