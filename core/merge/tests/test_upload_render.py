"""ffmpeg для своих видео: строгое чтение, поворот, HDR, обложки — без настоящего ffmpeg."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from unittest.mock import patch

from django.test import SimpleTestCase

from merge import render
from merge.config import UPLOAD_CODECS, UPLOAD_DECODERS


def full_probe(*, codec="h264", width=1920, height=1080, duration="4.000000", rotation=None,
               rotate_tag=None, transfer=None, audio_codec="aac", cover_first=False, fmt_duration="4.02",
               packets=None):
    """Ответ «ffprobe -count_packets -show_streams -show_format -of json» в том виде, что пишет ffprobe."""
    streams = []
    if cover_first:
        streams.append({"index": 0, "codec_name": "mjpeg", "codec_type": "video", "width": 300,
                        "height": 300, "disposition": {"default": 0, "attached_pic": 1}})
    video = {"index": len(streams), "codec_name": codec, "codec_type": "video", "width": width,
             "height": height, "pix_fmt": "yuv420p", "disposition": {"default": 1, "attached_pic": 0}}
    if duration is not None:
        video["duration"] = duration
    if rotation is not None:
        video["side_data_list"] = [{"side_data_type": "Display Matrix",
                                    "displaymatrix": "\n00000000:            0       65536           0\n",
                                    "rotation": rotation}]
    if rotate_tag is not None:
        video["tags"] = {"rotate": str(rotate_tag)}
    if transfer:
        video.update(color_transfer=transfer, color_primaries="bt2020", pix_fmt="yuv420p10le")
    if packets is not None:
        video["nb_read_packets"] = str(packets)
    streams.append(video)
    if audio_codec is not None:
        audio = {"index": len(streams), "codec_type": "audio", "sample_rate": "48000", "channels": 2}
        if audio_codec:  # у незнакомого ffmpeg кодека ffprobe codec_name не пишет вовсе
            audio["codec_name"] = audio_codec
        streams.append(audio)
    return json.dumps({"streams": streams,
                       "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2", "duration": fmt_duration}})


class StrictProbeTests(SimpleTestCase):
    def test_portrait_phone_clip(self):
        # iPhone вертикально: кадр в файле 1920×1080, матрица «-90».
        info = render.parse_probe(full_probe(rotation=-90), strict=True)
        self.assertEqual((info.rotation, info.width, info.height), (90, 1920, 1080))
        self.assertEqual((info.display_width, info.display_height), (1080, 1920))
        self.assertEqual((info.codec, info.video_streams, info.video_index, info.audio_index),
                         ("h264", 1, 0, 1))
        upside_down = render.parse_probe(full_probe(rotation=180), strict=True)
        self.assertEqual((upside_down.display_width, upside_down.display_height), (1920, 1080))

    def test_old_rotate_tag(self):
        info = render.parse_probe(full_probe(rotate_tag=270), strict=True)
        self.assertEqual((info.rotation, info.display_width), (270, 1080))

    def test_cover_picture_is_not_a_video(self):
        info = render.parse_probe(full_probe(cover_first=True), strict=True)
        self.assertEqual((info.video_streams, info.video_index, info.width, info.audio_index), (1, 1, 1920, 2))

    def test_hdr_is_detected(self):
        for transfer in ("smpte2084", "arib-std-b67"):
            self.assertTrue(render.parse_probe(full_probe(codec="hevc", transfer=transfer), strict=True).hdr)
        self.assertFalse(render.parse_probe(full_probe(transfer="bt709"), strict=True).hdr)

    def test_unknown_audio_means_silence_only_in_strict_mode(self):
        raw = full_probe(audio_codec="")
        self.assertEqual((render.parse_probe(raw, strict=True).audio,
                          render.parse_probe(raw, strict=True).audio_index), (False, None))
        # Наш файл разбирается коротким запросом без codec_name: звук есть звук.
        self.assertTrue(render.parse_probe(raw).audio)

    def test_matroska_duration_comes_from_the_container(self):
        info = render.parse_probe(full_probe(codec="vp9", duration=None, fmt_duration="3.5"), strict=True)
        self.assertEqual(info.duration, 3.5)

    def test_rotate_tag_that_is_not_a_finite_number_means_no_rotation(self):
        # Тег — любая строка файла (Matroska SimpleTag): «inf» ронял int() с OverflowError → 500.
        for value in ("inf", "-inf", "1e999", "nan", "Infinity"):
            with self.subTest(value=value):
                info = render.parse_probe(full_probe(rotate_tag=value), strict=True)
                self.assertEqual((info.rotation, info.display_width), (0, 1920))
        matrix = render.parse_probe(full_probe(rotation="inf"), strict=True)
        self.assertEqual(matrix.rotation, 0)

    def test_frames_are_the_counted_packets_of_the_picture(self):
        info = render.parse_probe(full_probe(cover_first=True, packets=7200), strict=True)
        self.assertEqual(info.frames, 7200)
        self.assertIsNone(render.parse_probe(full_probe(), strict=True).frames)
        self.assertIsNone(render.parse_probe(full_probe(packets="-5"), strict=True).frames)
        # Наш файл разбирается коротким запросом: кадры не считаются.
        self.assertIsNone(render.parse_probe(full_probe(packets=120)).frames)

    def test_only_listed_audio_is_decoded(self):
        # DTS ffmpeg читает, но его нет в списке: склейка возьмёт тишину, декодер не запустится.
        for codec, heard in (("aac", True), ("opus", True), ("pcm_s16le", True), ("dts", False),
                             ("truehd", False)):
            with self.subTest(codec=codec):
                self.assertEqual(render.parse_probe(full_probe(audio_codec=codec), strict=True).audio, heard)
        self.assertTrue(render.parse_probe(full_probe(audio_codec="dts")).audio)

    def test_probe_survives_any_parse_failure(self):
        ok = subprocess.CompletedProcess([], 0, full_probe().encode(), b"")
        for exc in (OverflowError("x"), ValueError("x"), TypeError("x"), AttributeError("x")):
            with self.subTest(exc=type(exc).__name__), \
                    patch("merge.render._run", return_value=ok), \
                    patch("merge.render.parse_probe", side_effect=exc):
                self.assertIsNone(render.probe("/m/a.mkv", "matroska"))


class StrictCommandTests(SimpleTestCase):
    def test_probe_reads_only_a_local_file_with_a_fixed_demuxer(self):
        cmd = render.upload_probe_cmd("/app/media/merge/uploads/1/a.mp4", "mov")
        self.assertEqual(cmd[0], "ffprobe")
        self.assertEqual(cmd[cmd.index("-protocol_whitelist") + 1], "file")
        self.assertEqual(cmd[cmd.index("-f") + 1], "mov")
        self.assertEqual(cmd[cmd.index("-probesize") + 1], "10000000")
        self.assertEqual(cmd[cmd.index("-analyzeduration") + 1], "10000000")
        self.assertIn("-show_streams", cmd)
        # Кадры — чтением файла, а не из заголовка; декодеры — только из списка.
        self.assertIn("-count_packets", cmd)
        self.assertEqual(cmd[cmd.index("-codec_whitelist") + 1], ",".join(UPLOAD_DECODERS))
        self.assertEqual(cmd[-1], "file:/app/media/merge/uploads/1/a.mp4")
        self.assertLess(cmd.index("-f"), len(cmd) - 1)

    def test_decoder_list_covers_every_accepted_video_codec(self):
        self.assertTrue(set(UPLOAD_CODECS) <= set(UPLOAD_DECODERS))
        self.assertTrue({"libdav1d", "aac", "mp3float", "opus", "mjpeg"} <= set(UPLOAD_DECODERS))
        self.assertTrue(all("," not in name and name == name.strip() for name in UPLOAD_DECODERS))

    def test_only_known_demuxers(self):
        for fmt in ("hls", "concat", "lavfi", "image2"):
            with self.assertRaises(ValueError):
                render.input_args(fmt)

    def test_normalize_upload(self):
        cmd = render.normalize_cmd("/m/a.webm", "out.mp4", aspect="9:16", fit="crop", duration=3.5,
                                   has_audio=True, fmt="matroska", video_index=2, audio_index=0)
        head = cmd[:cmd.index("-filter_complex")]
        self.assertEqual(head[6:], ["-protocol_whitelist", "file", "-codec_whitelist", ",".join(UPLOAD_DECODERS),
                                    "-f", "matroska", "-i", "file:/m/a.webm"])
        graph = cmd[cmd.index("-filter_complex") + 1]
        self.assertTrue(graph.startswith("[0:2]fps=30,"), graph)
        self.assertIn("[0:0]aresample=48000", graph)
        # Звук чужого файла — с потолком по сэмплам (3,5 + 1 с при 48 кГц): метки времени файла
        # могут врать, и -t по ним не наступил бы.
        self.assertIn("channel_layouts=stereo,atrim=end_sample=216000,apad[a]", graph)
        self.assertNotIn("asetpts", graph)
        self.assertNotIn("zscale", graph)
        self.assertNotIn("setparams", graph)
        self.assertNotIn("-color_trc", cmd)

    def test_normalize_hdr_tones_to_sdr_and_tags_bt709(self):
        cmd = render.normalize_cmd("/m/a.mp4", "out.mp4", aspect="16:9", fit="pad", duration=4,
                                   has_audio=False, fmt="mov", video_index=0, hdr=True)
        graph = cmd[cmd.index("-filter_complex") + 1]
        # Сначала 30 к/с и кадр не больше склейки, потом tonemap: 4K60 в плавающей точке шло втрое дольше.
        self.assertTrue(graph.startswith(
            "[0:0]fps=30,scale=1280:720:force_original_aspect_ratio=decrease," + render.TONEMAP + ","), graph)
        self.assertEqual(graph.count("fps=30"), 1)
        self.assertTrue(graph.endswith("format=yuv420p[v]"))
        crop = render.normalize_cmd("/m/a.mp4", "out.mp4", aspect="9:16", fit="crop", duration=4,
                                    has_audio=False, fmt="mov", video_index=0, hdr=True)
        self.assertTrue(crop[crop.index("-filter_complex") + 1].startswith(
            "[0:0]fps=30,scale=720:1280:force_original_aspect_ratio=increase," + render.TONEMAP + ","))
        for flag in ("-color_primaries", "-color_trc", "-colorspace"):
            self.assertEqual(cmd[cmd.index(flag) + 1], "bt709")
        plain = render.normalize_cmd("/m/a.mp4", "out.mp4", aspect="16:9", fit="pad", duration=4,
                                     has_audio=False, fmt="mov", video_index=0, hdr=True, tonemap=False)
        plain_graph = plain[plain.index("-filter_complex") + 1]
        self.assertNotIn("zscale", plain_graph)
        # Метку кодер берёт из кадра: без setparams HLG первой части ушёл бы во всю склейку.
        self.assertTrue(plain_graph.startswith(
            "[0:0]fps=30,scale=1280:720:force_original_aspect_ratio=decrease," + render.RELABEL_BT709 + ","),
            plain_graph)
        self.assertEqual(plain[plain.index("-color_trc") + 1], "bt709")
        # anullsrc — второй вход, после файла: строгие опции к нему не относятся.
        self.assertLess(plain.index("file:/m/a.mp4"), plain.index("lavfi"))

    def test_our_files_keep_the_old_command(self):
        cmd = render.normalize_cmd("in.mp4", "out.mp4", aspect="16:9", fit="crop", duration=5,
                                   has_audio=True)
        self.assertNotIn("-protocol_whitelist", cmd)
        self.assertEqual(cmd[cmd.index("-i") + 1], "in.mp4")
        self.assertTrue(cmd[cmd.index("-filter_complex") + 1].startswith("[0:v]fps=30,"))
        self.assertNotIn("atrim", cmd[cmd.index("-filter_complex") + 1])

    def test_silent_upload_has_no_audio_cap(self):
        cmd = render.normalize_cmd("/m/a.mp4", "out.mp4", aspect="16:9", fit="pad", duration=4,
                                   has_audio=False, fmt="mov", video_index=0)
        self.assertNotIn("atrim", cmd[cmd.index("-filter_complex") + 1])

    def test_upload_poster(self):
        cmd = render.poster_cmd("/m/a.mp4", "/m/a.jpg", at=0.5, fmt="mov", video_index=1)
        self.assertEqual(cmd[cmd.index("-f") + 1], "mov")
        self.assertLess(cmd.index("-codec_whitelist"), cmd.index("-i"))
        self.assertEqual(cmd[cmd.index("-i") + 1], "file:/m/a.mp4")
        self.assertEqual(cmd[cmd.index("-map") + 1], "0:1")
        self.assertEqual(cmd[-1], "/m/a.jpg")


class FakeStrictFFmpeg:
    """subprocess.run: полный ffprobe по таблице, ffmpeg «пишет» выход; fail — какие команды падают."""

    def __init__(self, probes, fail=None):
        self.calls = []
        self.probes = probes
        self.fail = fail or (lambda cmd: False)

    def __call__(self, cmd, **kwargs):
        cmd = list(cmd)
        if os.path.basename(cmd[0]) == "nice":
            cmd = cmd[3:]
        self.calls.append(cmd)
        if cmd[0] == "ffprobe":
            name = os.path.basename(cmd[-1].removeprefix("file:"))
            return subprocess.CompletedProcess(cmd, 0, self.probes.get(name, full_probe()).encode(), b"")
        if self.fail(cmd):
            return subprocess.CompletedProcess(cmd, 1, b"", b"No such filter: 'zscale'")
        with open(cmd[-1], "wb") as fh:
            fh.write(b"mp4")
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    def normalize(self):
        return [c for c in self.calls if c[0] == "ffmpeg" and "-filter_complex" in c
                and "concat" not in c[c.index("-filter_complex") + 1]]


class UploadRenderRunTests(SimpleTestCase):
    def setUp(self):
        self.workdir = tempfile.mkdtemp(prefix="merge-upload-render-")
        self.addCleanup(shutil.rmtree, self.workdir, True)
        self.files = {}
        for name in ("ours.mp4", "phone.mp4", "hdr.mp4", "silent.webm"):
            path = os.path.join(self.workdir, name)
            with open(path, "wb") as fh:
                fh.write(b"src")
            self.files[name] = path

    def test_uploads_are_read_strictly_and_ours_as_before(self):
        fake = FakeStrictFFmpeg({"phone.mp4": full_probe(rotation=-90, cover_first=True),
                                 "silent.webm": full_probe(codec="vp9", audio_codec=None, duration=None),
                                 "merged.mp4": full_probe(duration="12.0")})
        paths = [self.files["ours.mp4"], render.Input(self.files["phone.mp4"], "mov"),
                 render.Input(self.files["silent.webm"], "matroska")]
        with patch("merge.render.subprocess.run", side_effect=fake):
            result = render.render(paths, aspect="9:16", fit="pad", workdir=self.workdir)
        self.assertEqual(result.duration, 12.0)
        probes = [c for c in fake.calls if c[0] == "ffprobe"]
        self.assertNotIn("-protocol_whitelist", probes[0])
        self.assertEqual(probes[1][probes[1].index("-f") + 1], "mov")
        self.assertEqual(probes[2][probes[2].index("-f") + 1], "matroska")
        ours, phone, silent = fake.normalize()
        self.assertEqual(ours[ours.index("-i") + 1], self.files["ours.mp4"])
        self.assertEqual(phone[phone.index("-i") + 1], "file:" + self.files["phone.mp4"])
        # Обложка в файле стоит первой: картинку берём из потока 1, звук — из 2.
        graph = phone[phone.index("-filter_complex") + 1]
        self.assertTrue(graph.startswith("[0:1]fps=30"), graph)
        self.assertIn("[0:2]aresample", graph)
        self.assertIn("anullsrc=r=48000:cl=stereo", silent)

    def test_hdr_falls_back_to_plain_conversion_when_tonemap_fails(self):
        fake = FakeStrictFFmpeg({"hdr.mp4": full_probe(codec="hevc", transfer="arib-std-b67")},
                                fail=lambda cmd: "zscale" in " ".join(cmd))
        with patch("merge.render.subprocess.run", side_effect=fake):
            render.render([render.Input(self.files["hdr.mp4"], "mov"), self.files["ours.mp4"]],
                          aspect="16:9", fit="crop", workdir=self.workdir)
        first, second, _ours = fake.normalize()
        self.assertIn("zscale", first[first.index("-filter_complex") + 1])
        self.assertNotIn("zscale", second[second.index("-filter_complex") + 1])
        self.assertIn(render.RELABEL_BT709, second[second.index("-filter_complex") + 1])
        self.assertEqual(second[second.index("-color_trc") + 1], "bt709")
        self.assertTrue(second[-1].endswith("part000.mp4"))

    def test_hdr_failing_both_ways_names_the_fragment(self):
        fake = FakeStrictFFmpeg({"hdr.mp4": full_probe(codec="hevc", transfer="smpte2084")},
                                fail=lambda cmd: cmd[-1].endswith("part001.mp4"))
        with patch("merge.render.subprocess.run", side_effect=fake), \
                self.assertRaises(render.RenderError) as ctx:
            render.render([self.files["ours.mp4"], render.Input(self.files["hdr.mp4"], "mov")],
                          aspect="16:9", fit="crop", workdir=self.workdir)
        self.assertEqual((ctx.exception.code, ctx.exception.fragment), ("fragment_failed", 2))
        self.assertEqual(len(fake.normalize()), 3)

    def test_upload_probe_failure_is_unreadable(self):
        def fake(cmd, **kw):
            return subprocess.CompletedProcess(cmd, 1, b"", b"moov atom not found")

        with patch("merge.render.subprocess.run", side_effect=fake):
            self.assertIsNone(render.probe(self.files["phone.mp4"], "mov"))
