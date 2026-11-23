"""Голоса сцен в ffmpeg склейки: задержки по настоящим длинам частей, громкость, приглушение
музыки под несколькими голосами, обрезка по концу ролика — без настоящего ffmpeg.

Команды без голосов сцен те же до байта (golden в test_audio_render это и проверяет).
"""
from __future__ import annotations

import os
import shutil
import tempfile
from unittest.mock import patch

from django.test import SimpleTestCase

from merge import render

from .test_audio_render import FakeFFmpeg, _graph

L = render.Line


class LineRenderRunTests(SimpleTestCase):
    def setUp(self):
        self.workdir = tempfile.mkdtemp(prefix="merge-lines-")
        self.addCleanup(shutil.rmtree, self.workdir, True)
        self.srcs = []
        for name in ("a.mp4", "b.mp4", "c.mp4"):
            path = os.path.join(self.workdir, name)
            with open(path, "wb") as fh:
                fh.write(b"src")
            self.srcs.append(path)

    def _render(self, fake, mix):
        with patch("merge.render.subprocess.run", side_effect=fake):
            return render.render(self.srcs, aspect="16:9", fit="pad", workdir=self.workdir, audio=mix)

    def _lines(self):
        return (L("/a/l0.mp3", fragment=0, start=0.0, duration=1.0, volume=1.0),
                L("/a/l1.mp3", fragment=1, start=1.5, duration=1.0, volume=0.5),
                L("/a/l2.mp3", fragment=2, start=2.25, duration=1.0, volume=2.0))

    def test_each_line_starts_at_its_fragment_plus_its_second(self):
        # Части 5,0 · 4,04 · 6,0 с, первый кадр ролика — с нуля:
        # фрагмент 1 @0,0 → 0 мс (без adelay), фрагмент 2 @1,5 → 5,0 + 1,5 = 6500 мс,
        # фрагмент 3 @2,25 → 5,0 + 4,04 + 2,25 = 11290 мс.
        fake = FakeFFmpeg(part_lengths={"part000.mp4": 5.0, "part001.mp4": 4.04, "part002.mp4": 6.0},
                          merged=15.04, head="0")
        result = self._render(fake, render.AudioMix(lines=self._lines(), voice_volume=1.0))
        self.assertTrue(result.path.endswith("mixed.mp4"))
        graph = _graph(fake.mix())
        norm = "aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,asetpts=N/SR/TB"
        self.assertIn(f"[1:a]{norm},volume=1.000[line0]", graph)
        self.assertIn(f"[2:a]{norm},volume=0.500,adelay=delays=6500:all=1[line1]", graph)
        self.assertIn(f"[3:a]{norm},volume=2.000,adelay=delays=11290:all=1[line2]", graph)
        self.assertIn("[clip][line0][line1][line2]amix=inputs=4:duration=first:dropout_transition=0:normalize=0,"
                      "alimiter=limit=0.95:level=0:latency=1[aout]", graph)
        # Картинка — копией: голоса сцен ролик не сдвигают.
        cmd = fake.mix()
        self.assertEqual(cmd[cmd.index("-c:v") + 1], "copy")
        self.assertEqual(cmd[cmd.index("-t") + 1], "15.040")
        # Части разобраны до самого дальнего нужного фрагмента (третьего — его начало не нужно).
        probed = [os.path.basename(c[-1]) for c, _ in fake.calls if c[0] == "ffprobe"]
        self.assertEqual(probed[-4:], ["merged.mp4", "part000.mp4", "part001.mp4", "mixed.mp4"])
        self.assertEqual([a for a in cmd if a.startswith("file:")], ["file:/a/l0.mp3", "file:/a/l1.mp3",
                                                                       "file:/a/l2.mp3"])

    def test_first_frame_offset_is_added_like_for_the_voice(self):
        fake = FakeFFmpeg(part_lengths={"part000.mp4": 5.0, "part001.mp4": 4.04}, merged=15.04, head="0.021333")
        self._render(fake, render.AudioMix(lines=self._lines()))
        graph = _graph(fake.mix())
        self.assertIn("volume=1.000,adelay=delays=21:all=1[line0]", graph)
        self.assertIn("adelay=delays=6521:all=1[line1]", graph)
        self.assertIn("adelay=delays=11311:all=1[line2]", graph)

    def test_global_voice_lines_and_music_together(self):
        fake = FakeFFmpeg(part_lengths={"part000.mp4": 5.0, "part001.mp4": 4.04}, merged=15.04, head="0")
        mix = render.AudioMix(voice="/a/v.mp3", voice_volume=1.5, voice_duration=2.0, voice_fragment=1,
                              music="/a/m.mp3", music_volume=0.5, lines=self._lines()[1:])
        self._render(fake, mix)
        cmd = fake.mix()
        # Входы: ролик, голос за кадром, голоса сцен, музыка — по порядку.
        self.assertEqual([a for a in cmd if a.startswith("file:")],
                         ["file:/a/v.mp3", "file:/a/l1.mp3", "file:/a/l2.mp3", "file:/a/m.mp3"])
        graph = _graph(cmd)
        # Голос за кадром — как раньше: с первого кадра фрагмента 2 (5,0 с).
        self.assertIn("[1:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,asetpts=N/SR/TB,"
                      "volume=1.500,adelay=delays=5000:all=1[voice]", graph)
        # Голос сцены — только своя громкость: ползунок голоса за кадром (1,5) её не множит.
        self.assertIn("[2:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,asetpts=N/SR/TB,"
                      "volume=0.500,adelay=delays=6500:all=1[line0]", graph)
        self.assertIn("[3:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,asetpts=N/SR/TB,"
                      "volume=2.000,adelay=delays=11290:all=1[line1]", graph)
        self.assertIn("[4:a]", graph)
        self.assertIn("[clip][voice][line0][line1][music]amix=inputs=5", graph)
        # Голос 5,0–7,0 и голос сцены 6,5–7,5 — одно окно приглушения; второй голос сцены 11,29–12,29 — своё.
        self.assertIn("asetnsamples=n=256:p=0,volume=volume='0.500*(1-0.750*("
                      "clip((t-(4.700))/0.3,0,1)*clip(((8.000)-t)/0.5,0,1)"
                      "+clip((t-(10.990))/0.3,0,1)*clip(((12.790)-t)/0.5,0,1)))':eval=frame[music]", graph)

    def test_line_is_audible_with_zero_voice_volume_and_no_voice(self):
        # Ползунок голоса за кадром на 0 %, голоса за кадром нет (убран) — голос сцены всё равно
        # звучит со своей громкостью, а не volume=0.
        fake = FakeFFmpeg(part_lengths={"part000.mp4": 5.0}, merged=10.0, head="0")
        mix = render.AudioMix(voice_volume=0.0,
                              lines=(L("/a/l.mp3", fragment=0, start=0.5, duration=1.0, volume=1.0),))
        self._render(fake, mix)
        graph = _graph(fake.mix())
        self.assertIn("asetpts=N/SR/TB,volume=1.000,adelay=delays=500:all=1[line0]", graph)
        self.assertNotIn("volume=0.000", graph)

    def test_without_lines_the_voice_command_is_unchanged(self):
        fake = FakeFFmpeg(part_lengths={"part000.mp4": 4.021, "part001.mp4": 3.517}, merged=12.0)
        self._render(fake, render.AudioMix(clip_volume=0.3, voice="/a/v.mp3", voice_duration=3.0, voice_fragment=2,
                                           music="/a/m.mp3", expected_s=12.0))
        graph = _graph(fake.mix())
        self.assertIn("adelay=delays=7559:all=1", graph)
        self.assertIn("volume=volume='0.350*(1-0.750*clip((t-(7.259))/0.3,0,1)*clip(((11.059)-t)/0.5,0,1))'"
                      ":eval=frame[music]", graph)
        self.assertNotIn("[line", graph)

    def test_lines_on_the_first_fragment_need_no_part_probes(self):
        fake = FakeFFmpeg(head="0")
        self._render(fake, render.AudioMix(lines=(L("/a/l.mp3", fragment=0, start=1.2, duration=1.0),)))
        probed = [os.path.basename(c[-1]) for c, _ in fake.calls if c[0] == "ffprobe"]
        self.assertNotIn("part000.mp4", probed)
        self.assertIn("adelay=delays=1200:all=1[line0]", _graph(fake.mix()))

    def test_a_line_alone_makes_the_mix_step(self):
        self.assertTrue(render.AudioMix(lines=(L("/a/l.mp3", fragment=0),)).needed)
        self.assertFalse(render.AudioMix().needed)


class LineMixCommandTests(SimpleTestCase):
    VIDEO, DST = "/w/merged.mp4", "/w/mixed.mp4"

    def test_line_past_the_end_is_cut_and_one_after_the_end_is_dropped(self):
        mix = render.AudioMix(music="/a/m.mp3",
                              lines=(L("/a/l0.mp3", fragment=0, duration=5.0), L("/a/l1.mp3", fragment=1, duration=1.0)))
        cmd = render.mix_cmd(self.VIDEO, self.DST, duration=10.0, mix=mix, line_starts=[8.0, 10.0])
        self.assertEqual([a for a in cmd if a.startswith("file:")], ["file:/a/l0.mp3", "file:/a/m.mp3"])
        graph = _graph(cmd)
        self.assertIn("adelay=delays=8000:all=1[line0]", graph)
        self.assertNotIn("[line1]", graph)
        # Окно голоса — до конца ролика; конец смеси — -t по картинке.
        self.assertIn("clip(((10.500)-t)/0.5,0,1)", graph)
        self.assertEqual(cmd[cmd.index("-t") + 1], "10.000")
        self.assertIn("[clip][line0][music]amix=inputs=3", graph)

    def test_only_known_arguments_with_lines(self):
        mix = render.AudioMix(voice="/a/v.mp3", voice_duration=2.0, music="/a/m.mp3",
                              lines=(L("/a/l.mp3", fragment=0, duration=1.0, volume=0.7),))
        cmd = render.mix_cmd(self.VIDEO, self.DST, duration=10.0, mix=mix, voice_start=1.0, line_starts=[4.0])
        free = [a for a in cmd if not a.startswith("-") and a not in (
            "ffmpeg", "error", "file", "mp3float,mp3", "mp3", "copy", "aac", "128k", "48000", "2", "+faststart",
            "0:v:0", "[aout]", render.THREADS, "10.000", self.VIDEO, self.DST, "file:/a/v.mp3", "file:/a/m.mp3",
            "file:/a/l.mp3")]
        self.assertEqual(free, [_graph(cmd)])
        self.assertTrue(set(_graph(cmd)) <= set("[]0123456789:abcdefghijklmnopqrstuvwxyz_=,.;()*-/+'NSRTB"))
        self.assertEqual(cmd[cmd.index("file:/a/l.mp3") - 7:cmd.index("file:/a/l.mp3") + 1],
                         ["-protocol_whitelist", "file", "-codec_whitelist", "mp3float,mp3", "-f", "mp3", "-i",
                          "file:/a/l.mp3"])

    def test_duck_windows_merge_close_voices(self):
        self.assertEqual(render.duck_windows([(5.0, 6.0), (1.0, 2.0), (6.5, 7.0), (9.0, 9.0), (20.0, 21.0)]),
                         [(1.0, 2.0), (5.0, 7.0), (20.0, 21.0)])
        # Между голосами больше спуска и подъёма (0,8 с) — два окна.
        self.assertEqual(render.duck_windows([(1.0, 2.0), (2.81, 3.0)]), [(1.0, 2.0), (2.81, 3.0)])
        self.assertEqual(render.duck_windows([(1.0, 2.0), (2.8, 3.0)]), [(1.0, 3.0)])
        self.assertEqual(render.duck_windows([]), [])

    def test_ducking_envelope_under_several_voices(self):
        expr = render.music_volume_expr(0.4, [(2.0, 3.0), (8.0, 9.0)])
        body = expr.split("'")[1]

        def at(t):
            return eval(body, {"clip": lambda x, lo, hi: max(lo, min(hi, x)), "t": t})  # noqa: S307

        self.assertAlmostEqual(at(0.0), 0.4)
        self.assertAlmostEqual(at(2.5), 0.1)
        self.assertAlmostEqual(at(3.25), 0.4 * (1 - 0.75 * 0.5))
        self.assertAlmostEqual(at(5.0), 0.4)
        self.assertAlmostEqual(at(8.5), 0.1)
        self.assertAlmostEqual(at(10.0), 0.4)
        # Одно окно списком — то же выражение, что и окно без списка.
        self.assertEqual(render.music_volume_expr(0.4, [(5.0, 8.0)]), render.music_volume_expr(0.4, (5.0, 8.0)))
        self.assertEqual(render.music_volume_expr(0.4, []), "volume=0.400")
