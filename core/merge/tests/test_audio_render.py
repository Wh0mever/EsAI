"""Звук склейки в ffmpeg (Build MA): команды сведения, время голоса, бюджет — без настоящего ffmpeg.

Настоящий ffmpeg гоняет scratch-скрипт VS2/scratch/MA/real_mix_check.py (не часть тестов).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from unittest.mock import patch

from django.test import SimpleTestCase

from merge import render

GOLDEN = os.path.join(os.path.dirname(__file__), "golden_no_sound.json")


def _cp(cmd, rc=0, out=b"", err=b""):
    return subprocess.CompletedProcess(cmd, rc, out, err)


def _strip_nice(cmd):
    cmd = list(cmd)
    return cmd[3:] if cmd and os.path.basename(cmd[0]) == "nice" else cmd


class NoSoundPipelineTests(SimpleTestCase):
    """Без звука склейки и со звуком роликов «как есть» — команды до байта те же, что до Build MA.

    golden_no_sound.json снят с render.py из HEAD 20fa0205 (до правок MA1) скриптом
    VS2/scratch/MA/golden_commands.py: те же входы, те же ответы ffprobe.
    """

    @staticmethod
    def _probe_json(name, strict):
        # Те же ответы, что в golden_commands.py.
        if strict:
            return {"streams": [{"index": 0, "codec_type": "video", "codec_name": "h264", "width": 1920,
                                 "height": 1080, "duration": "4.000", "nb_read_packets": "120"},
                                {"index": 1, "codec_type": "audio", "codec_name": "aac"}],
                    "format": {"duration": "4.021"}}
        audio = not name.endswith("b.mp4")
        streams = [{"codec_type": "video", "width": 1280, "height": 720, "duration": "5.000"}]
        if audio:
            streams.append({"codec_type": "audio", "duration": "5.021"})
        return {"streams": streams, "format": {"duration": "5.021" if audio else "5.000"}}

    def _run(self, **kw):
        workdir = tempfile.mkdtemp(prefix="merge-golden-")
        self.addCleanup(shutil.rmtree, workdir, True)
        calls = []

        def fake(cmd, **kwargs):
            cmd = _strip_nice(cmd)
            calls.append([[a.replace(workdir, "<W>").replace("\\", "/") for a in cmd], kwargs.get("timeout")])
            if cmd[0] == "ffprobe":
                return _cp(cmd, 0, json.dumps(self._probe_json(cmd[-1], "-show_streams" in cmd)).encode())
            with open(cmd[-1], "wb") as fh:
                fh.write(b"mp4")
            return _cp(cmd)

        srcs = [os.path.join(workdir, "a.mp4"), os.path.join(workdir, "b.mp4"),
                render.Input(os.path.join(workdir, "c.mp4"), "mov")]
        with patch("merge.render.subprocess.run", side_effect=fake):
            result = render.render(srcs, workdir=workdir, **kw)
        self.assertTrue(result.path.endswith("merged.mp4"))
        return calls

    @staticmethod
    def _with_upload_cap(golden):
        """Единственная намеренная разница с HEAD: звук своего видео (c.mp4, -f mov) получает
        потолок по сэмплам перед apad (MA_FIX2: метки времени файла могут врать). Строгий разбор
        отвечает 4,0 с → (4 + 1) × 48000 сэмплов."""
        out = {}
        for name, calls in golden.items():
            fixed = []
            for cmd, timeout in calls:
                if cmd[0] == "ffmpeg" and "-filter_complex" in cmd and "file:<W>/c.mp4" in cmd:
                    cmd = list(cmd)
                    i = cmd.index("-filter_complex") + 1
                    cmd[i] = cmd[i].replace("channel_layouts=stereo,apad[a]",
                                            "channel_layouts=stereo,atrim=end_sample=240000,apad[a]")
                fixed.append([cmd, timeout])
            out[name] = fixed
        return out

    def test_commands_are_byte_identical_to_the_pre_change_builder(self):
        with open(GOLDEN, encoding="utf-8") as fh:
            raw = json.load(fh)
        golden = self._with_upload_cap(raw)
        # Разница — ровно в одной команде на сценарий (нормализация своего видео), остальное до байта.
        for name in raw:
            changed = [a for a, b in zip(raw[name], golden[name]) if a != b]
            self.assertEqual(len(changed), 1, name)
        for name, shape in (("pad_16x9", dict(aspect="16:9", fit="pad")),
                            ("crop_9x16", dict(aspect="9:16", fit="crop"))):
            for extra in ({}, {"audio": None}, {"audio": render.AudioMix()},
                          {"audio": render.AudioMix(clip_volume=1.0, music_volume=0.9)}):
                with self.subTest(scenario=name, audio=extra):
                    self.assertEqual(self._run(**shape, **extra), golden[name])


class FakeFFmpeg:
    """ffprobe отвечает по имени файла, ffmpeg «пишет» выход; всё записывается."""

    def __init__(self, *, part_lengths=None, merged=12.0, head="0.021333", mixed_audio=True, fail=None,
                 timeout=None, part_fail=()):
        self.calls = []
        self.part_lengths = part_lengths or {}
        self.merged = merged
        self.head = head
        self.mixed_audio = mixed_audio
        self.fail = fail or (lambda cmd: False)
        self.timeout = timeout or (lambda cmd: False)
        self.part_fail = part_fail

    def __call__(self, cmd, **kwargs):
        cmd = _strip_nice(cmd)
        self.calls.append((cmd, kwargs.get("timeout")))
        if self.timeout(cmd):
            raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout"))
        if cmd[0] == "ffprobe":
            name = os.path.basename(cmd[-1])
            if "stream=start_time" in cmd:
                return _cp(cmd, 0, json.dumps({"streams": [{"start_time": self.head}]}).encode())
            if name in self.part_fail:
                return _cp(cmd, 1, b"", b"Invalid data")
            video = {"codec_type": "video", "width": 1280, "height": 720, "duration": "4.000"}
            audio = {"codec_type": "audio", "duration": "4.021"}
            fmt = "4.021"
            if name.startswith("part"):
                fmt = str(self.part_lengths.get(name, 4.021))
            elif name == "merged.mp4":
                video["duration"], fmt = str(self.merged), str(self.merged + 0.02)
            elif name == "mixed.mp4":
                video["duration"], fmt = str(self.merged), str(self.merged + 0.02)
                if not self.mixed_audio:
                    return _cp(cmd, 0, json.dumps({"streams": [video], "format": {"duration": fmt}}).encode())
            return _cp(cmd, 0, json.dumps({"streams": [video, audio], "format": {"duration": fmt}}).encode())
        if self.fail(cmd):
            return _cp(cmd, 1, b"", b"boom")
        with open(cmd[-1], "wb") as fh:
            fh.write(b"mp4")
        return _cp(cmd)

    def ffmpeg(self):
        return [c for c, _ in self.calls if c[0] == "ffmpeg"]

    def mix(self):
        return next(c for c in self.ffmpeg() if c[-1].endswith("mixed.mp4"))


def _graph(cmd):
    return cmd[cmd.index("-filter_complex") + 1]


class MixCommandTests(SimpleTestCase):
    VIDEO, DST = "/w/merged.mp4", "/w/mixed.mp4"

    def test_clip_only_quiet_has_no_mix_inputs(self):
        cmd = render.mix_cmd(self.VIDEO, self.DST, duration=10.0, mix=render.AudioMix(clip_volume=0.3))
        self.assertEqual(cmd[:8], ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i",
                                   self.VIDEO])
        self.assertEqual(cmd.count("-i"), 1)
        self.assertEqual(_graph(cmd), "[0:a]aresample=48000:min_comp=0.001:min_hard_comp=0.005:first_pts=0,"
                                      "aformat=sample_fmts=fltp:channel_layouts=stereo,volume=0.300[aout]")
        self.assertEqual(cmd[cmd.index("-c:v") + 1], "copy")
        maps = [cmd[i + 1] for i, a in enumerate(cmd) if a == "-map"]
        self.assertEqual(maps, ["0:v:0", "[aout]"])
        for flag, value in (("-c:a", "aac"), ("-b:a", "128k"), ("-ar", "48000"), ("-ac", "2"),
                            ("-t", "10.000")):
            self.assertEqual(cmd[cmd.index(flag) + 1], value)
        self.assertEqual(cmd[-3:], ["-movflags", "+faststart", self.DST])

    def test_clip_off_is_silence_of_the_same_length(self):
        cmd = render.mix_cmd(self.VIDEO, self.DST, duration=7.5, mix=render.AudioMix(clip_volume=0.0))
        self.assertIn("volume=0.000[aout]", _graph(cmd))
        self.assertEqual(cmd[cmd.index("-t") + 1], "7.500")

    def test_voice_only(self):
        mix = render.AudioMix(voice="/a/v.mp3", voice_volume=1.5, voice_duration=3.0, voice_fragment=2)
        cmd = render.mix_cmd(self.VIDEO, self.DST, duration=12.0, mix=mix, voice_start=6.5213)
        # Трек читается строго: только файл, демуксер mp3, декодеры mp3, путь file:.
        i = cmd.index("file:/a/v.mp3")
        self.assertEqual(cmd[i - 7:i + 1], ["-protocol_whitelist", "file", "-codec_whitelist", "mp3float,mp3",
                                            "-f", "mp3", "-i", "file:/a/v.mp3"])
        self.assertNotIn("-stream_loop", cmd)
        graph = _graph(cmd)
        self.assertIn("[1:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,asetpts=N/SR/TB,"
                      "volume=1.500,adelay=delays=6521:all=1[voice]", graph)
        self.assertIn("[clip][voice]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,"
                      "alimiter=limit=0.95:level=0:latency=1[aout]", graph)
        self.assertNotIn("eval=frame", graph)
        self.assertNotIn("asetnsamples", graph)

    def test_voice_from_the_start_has_no_delay(self):
        mix = render.AudioMix(voice="/a/v.mp3", voice_duration=3.0)
        graph = _graph(render.mix_cmd(self.VIDEO, self.DST, duration=12.0, mix=mix, voice_start=0.0))
        self.assertNotIn("adelay", graph)

    def test_music_only_loops_trims_fades_without_ducking(self):
        mix = render.AudioMix(music="/a/m.mp3", music_volume=0.35)
        cmd = render.mix_cmd(self.VIDEO, self.DST, duration=10.0, mix=mix)
        i = cmd.index("file:/a/m.mp3")
        self.assertEqual(cmd[i - 9:i + 1], ["-protocol_whitelist", "file", "-codec_whitelist", "mp3float,mp3",
                                            "-f", "mp3", "-stream_loop", "-1", "-i", "file:/a/m.mp3"])
        graph = _graph(cmd)
        self.assertIn("[1:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,asetpts=N/SR/TB,"
                      "atrim=duration=10.000,afade=t=in:st=0:d=1.000,afade=t=out:st=9.000:d=1.000,"
                      "volume=0.350[music]", graph)
        self.assertIn("[clip][music]amix=inputs=2", graph)
        # Без голоса огибающей нет — и мелкие кадры ей не нужны.
        self.assertNotIn("asetnsamples", graph)

    def test_voice_and_music_duck_the_music_under_the_voice(self):
        mix = render.AudioMix(clip_volume=0.0, voice="/a/v.mp3", voice_duration=3.0, music="/a/m.mp3",
                              music_volume=0.5)
        cmd = render.mix_cmd(self.VIDEO, self.DST, duration=12.0, mix=mix, voice_start=6.5)
        self.assertEqual([a for a in cmd if a.startswith("file:")], ["file:/a/v.mp3", "file:/a/m.mp3"])
        graph = _graph(cmd)
        self.assertIn("[2:a]", graph)
        # Огибающая — по кадрам в 256 сэмплов (5 мс): спуск и подъём без ступенек.
        self.assertIn("afade=t=out:st=11.000:d=1.000,asetnsamples=n=256:p=0,"
                      "volume=volume='0.500*(1-0.750*clip((t-(6.200))/0.3,0,1)"
                      "*clip(((10.000)-t)/0.5,0,1))':eval=frame[music]", graph)
        self.assertIn("[clip][voice][music]amix=inputs=3", graph)
        # Ограничитель без задержки: звук не отстаёт от картинки на 5 мс.
        self.assertTrue(graph.endswith("alimiter=limit=0.95:level=0:latency=1[aout]"))

    def test_voice_past_the_end_is_cut_and_ducking_follows(self):
        mix = render.AudioMix(voice="/a/v.mp3", voice_duration=5.0, music="/a/m.mp3")
        graph = _graph(render.mix_cmd(self.VIDEO, self.DST, duration=10.0, mix=mix, voice_start=8.0))
        # Голос режется по концу ролика: окно приглушения — до 10,0 с, подъём уже за концом.
        self.assertIn("clip(((10.500)-t)/0.5,0,1)", graph)

    def test_short_merge_shortens_the_fades(self):
        graph = _graph(render.mix_cmd(self.VIDEO, self.DST, duration=1.2, mix=render.AudioMix(music="/m.mp3")))
        self.assertIn("afade=t=in:st=0:d=0.600,afade=t=out:st=0.600:d=0.600", graph)

    def test_ducking_envelope_values(self):
        expr = render.music_volume_expr(0.4, (5.0, 8.0))
        body = expr.split("'")[1]

        def at(t):
            return eval(body, {"clip": lambda x, lo, hi: max(lo, min(hi, x)), "t": t})  # noqa: S307

        self.assertAlmostEqual(at(0.0), 0.4)
        self.assertAlmostEqual(at(4.69), 0.4)
        self.assertAlmostEqual(at(4.85), 0.4 * (1 - 0.75 * 0.5))
        self.assertAlmostEqual(at(5.0), 0.1)
        self.assertAlmostEqual(at(7.9), 0.1)
        self.assertAlmostEqual(at(8.25), 0.4 * (1 - 0.75 * 0.5))
        self.assertAlmostEqual(at(8.6), 0.4)
        self.assertEqual(render.music_volume_expr(0.4, None), "volume=0.400")

    def test_no_user_strings_only_known_arguments(self):
        mix = render.AudioMix(clip_volume=0.3, voice="/a/v.mp3", voice_duration=2.0, music="/a/m.mp3")
        cmd = render.mix_cmd(self.VIDEO, self.DST, duration=10.0, mix=mix, voice_start=1.0)
        free = [a for a in cmd if not a.startswith("-") and a not in (
            "ffmpeg", "error", "file", "mp3float,mp3", "mp3", "copy", "aac", "128k", "48000", "2", "+faststart",
            "0:v:0", "[aout]", render.THREADS, "10.000", self.VIDEO, self.DST, "file:/a/v.mp3", "file:/a/m.mp3")]
        self.assertEqual(free, [_graph(cmd)])
        self.assertTrue(set(_graph(cmd)) <= set("[]0123456789:abcdefghijklmnopqrstuvwxyz_=,.;()*-/+'NSRTB"))

    def test_mix_timeout(self):
        self.assertEqual(render.mix_timeout(10), 60)
        self.assertEqual(render.mix_timeout(300), 150)

    def test_needed(self):
        self.assertFalse(render.AudioMix().needed)
        self.assertTrue(render.AudioMix(clip_volume=0.3).needed)
        self.assertTrue(render.AudioMix(voice="v").needed)
        self.assertTrue(render.AudioMix(music="m").needed)


class RenderMixRunTests(SimpleTestCase):
    def setUp(self):
        self.workdir = tempfile.mkdtemp(prefix="merge-mix-")
        self.addCleanup(shutil.rmtree, self.workdir, True)
        self.srcs = []
        for name in ("a.mp4", "b.mp4", "c.mp4"):
            path = os.path.join(self.workdir, name)
            with open(path, "wb") as fh:
                fh.write(b"src")
            self.srcs.append(path)

    def _render(self, fake, mix, **kw):
        with patch("merge.render.subprocess.run", side_effect=fake):
            return render.render(self.srcs, aspect="16:9", fit="pad", workdir=self.workdir, audio=mix, **kw)

    def test_voice_starts_at_the_first_frame_of_its_fragment(self):
        fake = FakeFFmpeg(part_lengths={"part000.mp4": 4.021, "part001.mp4": 3.517}, merged=12.0)
        stages = []
        mix = render.AudioMix(clip_volume=0.3, voice="/a/v.mp3", voice_duration=3.0, voice_fragment=2,
                              music="/a/m.mp3", expected_s=12.0)
        result = self._render(fake, mix, progress=lambda *a: stages.append(a))
        self.assertEqual(result.path, os.path.join(self.workdir, "mixed.mp4"))
        self.assertEqual(result.duration, 12.0)
        self.assertEqual(stages[-2:], [("joining", 3, 3), ("mixing", 3, 3)])
        probed = [os.path.basename(c[-1]) for c, _ in fake.calls if c[0] == "ffprobe"]
        self.assertEqual(probed, ["a.mp4", "b.mp4", "c.mp4", "merged.mp4", "merged.mp4", "part000.mp4",
                                  "part001.mp4", "mixed.mp4"])
        graph = _graph(fake.mix())
        # 0,021333 (первый кадр ролика) + 4,021 + 3,517 = 7,559333 с.
        self.assertIn("adelay=delays=7559:all=1", graph)
        self.assertIn("clip((t-(7.259))/0.3,0,1)*clip(((11.059)-t)/0.5,0,1)", graph)
        # Длина — до конца картинки: её первый кадр + её длина.
        self.assertEqual(fake.mix()[fake.mix().index("-t") + 1], "12.021")
        self.assertEqual(fake.mix()[fake.mix().index("-i") + 1], os.path.join(self.workdir, "merged.mp4"))

    def test_voice_from_fragment_one_needs_no_part_probes(self):
        fake = FakeFFmpeg(head="0.021333")
        self._render(fake, render.AudioMix(voice="/a/v.mp3", voice_duration=2.0))
        probed = [os.path.basename(c[-1]) for c, _ in fake.calls if c[0] == "ffprobe"]
        self.assertNotIn("part000.mp4", probed)
        self.assertIn("adelay=delays=21:all=1", _graph(fake.mix()))

    def test_fragment_past_the_end_means_the_last_one(self):
        fake = FakeFFmpeg(part_lengths={"part000.mp4": 4.0, "part001.mp4": 4.0}, head="0")
        self._render(fake, render.AudioMix(voice="/a/v.mp3", voice_duration=2.0, voice_fragment=9))
        self.assertIn("adelay=delays=8000:all=1", _graph(fake.mix()))

    def test_unreadable_part_falls_back_to_its_cut_length(self):
        fake = FakeFFmpeg(part_lengths={"part000.mp4": 4.5}, part_fail=("part001.mp4",), head="0")
        self._render(fake, render.AudioMix(voice="/a/v.mp3", voice_duration=2.0, voice_fragment=2))
        # Часть 2 не разобралась — её длина та, что резала нормализация (-t 4,000).
        self.assertIn("adelay=delays=8500:all=1", _graph(fake.mix()))

    def test_broken_start_time_counts_as_zero(self):
        for head in ("N/A", "inf", "-3", "12"):
            with self.subTest(head=head):
                fake = FakeFFmpeg(part_lengths={"part000.mp4": 4.0}, head=head)
                self._render(fake, render.AudioMix(voice="/a/v.mp3", voice_duration=1.0, voice_fragment=1))
                self.assertIn("adelay=delays=4000:all=1", _graph(fake.mix()))

    def test_mix_failure_is_named(self):
        fake = FakeFFmpeg(fail=lambda cmd: cmd[-1].endswith("mixed.mp4"))
        with self.assertRaises(render.RenderError) as ctx:
            self._render(fake, render.AudioMix(music="/a/m.mp3"))
        self.assertEqual((ctx.exception.code, ctx.exception.message), ("mix_failed", render.MSG_MIX_FAILED))
        self.assertEqual(render.MSG_MIX_FAILED,
                         "Не получилось свести звук — кредиты не списаны, попробуйте ещё раз.")

    def test_mix_without_sound_in_the_result_is_a_failure(self):
        fake = FakeFFmpeg(mixed_audio=False)
        with self.assertRaises(render.RenderError) as ctx:
            self._render(fake, render.AudioMix(clip_volume=0.0))
        self.assertEqual(ctx.exception.code, "mix_failed")

    def test_mix_timeout_is_too_slow(self):
        fake = FakeFFmpeg(timeout=lambda cmd: cmd[-1].endswith("mixed.mp4"))
        with self.assertRaises(render.RenderError) as ctx:
            self._render(fake, render.AudioMix(music="/a/m.mp3"))
        self.assertEqual((ctx.exception.code, ctx.exception.message), ("too_slow", render.MSG_TOO_SLOW))

    def test_mix_time_is_reserved_from_the_deadline(self):
        fake = FakeFFmpeg()
        mix = render.AudioMix(music="/a/m.mp3", expected_s=300.0)
        with patch("merge.render.subprocess.run", side_effect=fake), \
                patch("merge.render.time.monotonic", return_value=0.0):
            render.render(self.srcs, aspect="16:9", fit="crop", workdir=self.workdir, audio=mix, deadline=200.0)
        timeouts = {os.path.basename(c[-1]): t for c, t in fake.calls if c[0] == "ffmpeg"}
        # Фрагментам и соединению — срок минус оценка сведения 5 минут (150 с).
        self.assertEqual(timeouts["part000.mp4"], 50.0)
        self.assertEqual(timeouts["merged.mp4"], 50.0)
        # Сведению — его потолок по длине ролика, но не дальше общего срока.
        self.assertEqual(timeouts["mixed.mp4"], 60.0)

    def _render_at_mix(self, fake, now_at_mix):
        """Склейка, в которой к сведению часы показывают now_at_mix (общий срок — 200 с)."""
        clock = {"now": 0.0}

        def progress(stage, done, total):
            if stage == "mixing":
                clock["now"] = now_at_mix

        mix = render.AudioMix(voice="/a/v.mp3", voice_duration=2.0, voice_fragment=2, expected_s=10.0)
        with patch("merge.render.subprocess.run", side_effect=fake), \
                patch("merge.render.time.monotonic", side_effect=lambda: clock["now"]):
            return render.render(self.srcs, aspect="16:9", fit="pad", workdir=self.workdir, audio=mix,
                                 deadline=200.0, progress=progress)

    def test_probes_before_the_mix_stay_inside_the_deadline(self):
        fake = FakeFFmpeg(part_lengths={"part000.mp4": 4.0, "part001.mp4": 4.0}, head="0")
        self._render_at_mix(fake, 188.0)
        mixing = fake.calls[fake.calls.index(next(c for c in fake.calls if "stream=start_time" in c[0])):]
        probes = [(os.path.basename(c[-1]), t) for c, t in mixing if c[0] == "ffprobe"]
        # До конца срока 12 с: разборы перед сведением и после него — не дольше (обычный потолок 30 с).
        self.assertEqual(probes, [("merged.mp4", 12.0), ("part000.mp4", 12.0), ("part001.mp4", 12.0),
                                  ("mixed.mp4", 12.0)])
        self.assertEqual(fake.calls[-2][1], 12.0)

    def test_no_time_left_for_the_mix_is_too_slow_before_any_probe(self):
        fake = FakeFFmpeg(head="0")
        with self.assertRaises(render.RenderError) as ctx:
            self._render_at_mix(fake, 199.5)
        self.assertEqual(ctx.exception.code, "too_slow")
        self.assertFalse(any("stream=start_time" in c for c, _ in fake.calls))
        self.assertFalse(any(c[-1].endswith("mixed.mp4") for c, _ in fake.calls))

    def test_without_sound_the_deadline_is_untouched(self):
        fake = FakeFFmpeg()
        with patch("merge.render.subprocess.run", side_effect=fake), \
                patch("merge.render.time.monotonic", return_value=0.0):
            render.render(self.srcs, aspect="16:9", fit="crop", workdir=self.workdir, deadline=200.0,
                          audio=render.AudioMix(expected_s=300.0))
        timeouts = {os.path.basename(c[-1]): t for c, t in fake.calls if c[0] == "ffmpeg"}
        self.assertEqual(timeouts["part000.mp4"], 120.0)
        self.assertNotIn("mixed.mp4", timeouts)


class AudioProbeTests(SimpleTestCase):
    def test_probe_command_is_strict(self):
        cmd = render.audio_probe_cmd("/tmp/in.wav", "wav")
        self.assertEqual(cmd[-1], "file:/tmp/in.wav")
        for flag, value in (("-protocol_whitelist", "file"), ("-f", "wav"), ("-probesize", "10000000"),
                            ("-analyzeduration", "10000000")):
            self.assertEqual(cmd[cmd.index(flag) + 1], value)
        decoders = cmd[cmd.index("-codec_whitelist") + 1].split(",")
        self.assertTrue({"mp3float", "aac", "flac", "opus", "wmav2", "pcm_s16le", "mjpeg", "h264"} <= set(decoders))
        self.assertIn("-show_streams", cmd)
        for bad in ("hls", "concat", "lavfi", "image2", ""):
            with self.assertRaises(ValueError):
                render.audio_probe_cmd("/x", bad)

    def test_parse(self):
        raw = json.dumps({"streams": [{"codec_type": "video", "codec_name": "mjpeg"},
                                      {"codec_type": "audio", "codec_name": "dts", "duration": "9"},
                                      {"codec_type": "audio", "codec_name": "aac", "duration": "61.2"}],
                          "format": {"duration": "61.25"}})
        info = render.parse_audio_probe(raw)
        self.assertEqual((info.audio, info.codec, info.duration), (True, "aac", 61.25))
        raw = json.dumps({"streams": [{"codec_type": "audio", "codec_name": "mp3", "duration": "12.5"}],
                          "format": {}})
        self.assertEqual(render.parse_audio_probe(raw).duration, 12.5)
        raw = json.dumps({"streams": [{"codec_type": "audio", "codec_name": "dts"}], "format": {"duration": "3"}})
        self.assertFalse(render.parse_audio_probe(raw).audio)
        self.assertIsNone(render.parse_audio_probe(json.dumps({"format": {"duration": "inf"}})).duration)

    def test_parse_rate_and_channels_of_every_audio_stream(self):
        # ffmpeg сам выберет дорожку (с наибольшим числом каналов) — проверяется наибольшее по всем.
        raw = json.dumps({"streams": [{"codec_type": "audio", "codec_name": "aac", "sample_rate": "44100",
                                       "channels": 2},
                                      {"codec_type": "audio", "codec_name": "flac", "sample_rate": "384000",
                                       "channels": 12},
                                      {"codec_type": "video", "codec_name": "mjpeg", "channels": 99}],
                          "format": {"duration": "6"}})
        info = render.parse_audio_probe(raw)
        self.assertEqual((info.codec, info.sample_rate, info.channels), ("aac", 384000, 12))
        raw = json.dumps({"streams": [{"codec_type": "audio", "codec_name": "mp3", "sample_rate": "junk"}],
                          "format": {"duration": "6"}})
        info = render.parse_audio_probe(raw)
        self.assertEqual((info.sample_rate, info.channels), (None, None))

    def test_probe_failures_are_none(self):
        for result in (_cp([], 1, b"", b"x"), _cp([], 0, b"not json")):
            with self.subTest(result=result), patch("merge.render._run", return_value=result):
                self.assertIsNone(render.probe_audio("/x.wav", "wav"))
        with patch("merge.render._run", side_effect=subprocess.TimeoutExpired("ffprobe", 20)):
            self.assertIsNone(render.probe_audio("/x.wav", "wav"))

    def test_container_duration_is_parsed(self):
        raw = json.dumps({"streams": [{"codec_type": "video", "width": 2, "height": 2, "duration": "4.000"}],
                          "format": {"duration": "4.021"}})
        info = render.parse_probe(raw)
        self.assertEqual((info.duration, info.container_duration), (4.0, 4.021))
        raw = json.dumps({"streams": [{"codec_type": "video", "duration": "inf"}], "format": {"duration": "nan"}})
        info = render.parse_probe(raw)
        self.assertEqual((info.duration, info.container_duration), (None, None))
