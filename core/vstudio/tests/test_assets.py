"""Загрузки и нормализация фото видеостудии (§7, §13 «Загрузки»).

HEIC, EXIF-поворот, полиглот, «бомба», маленькое фото, дедупликация — плюс
правила приёма, прозрачность, анимация, профили цвета и последний кадр видео.
Файлы пишутся во временный MEDIA_ROOT (factories.media_root).
"""
from __future__ import annotations

import io
import struct
import zlib
from unittest import mock

from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase
from django.utils import timezone
from django.utils.datastructures import MultiValueDict
from PIL import Image, ImageCms, PngImagePlugin

from .. import assets as A
from ..models import Asset, Take
from . import factories as f

try:
    import pillow_heif

    HEIF_ENCODER = bool(pillow_heif.libheif_info().get("HEIF"))
except Exception:  # pragma: no cover — pillow-heif не установлен
    pillow_heif = None
    HEIF_ENCODER = False

RED = (220, 20, 20)
BLUE = (20, 20, 220)


# ---------------------------------------------------------------- картинки для тестов

def encode(img: Image.Image, fmt: str = "JPEG", **kw) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format=fmt, **kw)
    return buf.getvalue()


def jpeg(width: int = 640, height: int = 480, color=(200, 120, 40), **kw) -> bytes:
    return encode(Image.new("RGB", (width, height), color), "JPEG", quality=95, **kw)


def halves(width: int, height: int) -> Image.Image:
    """Левая половина красная, правая синяя — по ним видно, куда повернули."""
    img = Image.new("RGB", (width, height), BLUE)
    img.paste(RED, (0, 0, width // 2, height))
    return img


def exif_bytes(orientation: int | None = None, *, gps: bool = False) -> bytes:
    exif = Image.Exif()
    exif[0x010F] = "Apple"
    exif[0x0110] = "iPhone 15 Pro"
    if orientation:
        exif[0x0112] = orientation
    if gps:
        ifd = exif.get_ifd(0x8825)
        ifd[1] = "N"
        ifd[2] = (55.0, 45.0, 21.0)
        ifd[3] = "E"
        ifd[4] = (37.0, 37.0, 4.0)
    return exif.tobytes()


def png_header_only(width: int, height: int) -> bytes:
    """PNG, который ОБЪЯВЛЯЕТ огромный размер, а данных в нём на 16 байт."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(b"\x00" * 16)) + chunk(b"IEND", b""))


def gif_header_only(width: int, height: int) -> bytes:
    return (b"GIF89a" + struct.pack("<HH", width, height) + b"\x00\x00\x00"
            + b",\x00\x00\x00\x00" + struct.pack("<HH", width, height) + b"\x00\x02\x02D\x01\x00;")


def upload(data: bytes, name: str = "photo.jpg", content_type: str = "image/jpeg"):
    return SimpleUploadedFile(name, data, content_type=content_type)


def open_bytes(data: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(data))
    img.load()
    return img


def near(pixel, color, tol: int = 40) -> bool:
    return all(abs(a - b) <= tol for a, b in zip(pixel[:3], color))


def read(path: str) -> bytes:
    with default_storage.open(path, "rb") as fh:
        return fh.read()


# ---------------------------------------------------------------- нормализатор

class NormalizeTests(SimpleTestCase):
    def test_jpeg_reencoded_q90_with_thumb(self):
        norm = A.normalize_image_bytes(jpeg(1000, 800))
        self.assertEqual((norm.ext, norm.mime, norm.width, norm.height), ("jpg", "image/jpeg", 1000, 800))
        self.assertEqual(norm.flags, {})
        self.assertEqual(norm.source_format, "JPEG")
        self.assertEqual(open_bytes(norm.data).format, "JPEG")
        thumb = open_bytes(norm.thumb)
        self.assertEqual(thumb.format, "JPEG")
        self.assertEqual(max(thumb.size), 480)

    def test_long_side_downscaled_to_2048(self):
        norm = A.normalize_image_bytes(encode(Image.new("RGB", (3000, 1500), RED), "PNG"))
        self.assertEqual((norm.width, norm.height), (2048, 1024))
        self.assertEqual(norm.flags["downscaled_from"], [3000, 1500])
        self.assertEqual(norm.ext, "jpg")   # нет прозрачности — JPEG, даже из PNG

    def test_big_jpeg_decoded_with_draft(self):
        from PIL import JpegImagePlugin

        real = JpegImagePlugin.JpegImageFile.draft
        with mock.patch.object(JpegImagePlugin.JpegImageFile, "draft", autospec=True,
                               side_effect=real) as draft:
            norm = A.normalize_image_bytes(jpeg(8200, 4100))
        # Первый вызов — наш (декодирование в 1/4), второй делает превью.
        self.assertEqual(draft.call_args_list[0].args[1:], (None, (2048, 1024)))
        self.assertEqual((norm.width, norm.height), (2048, 1024))
        self.assertEqual(norm.flags["downscaled_from"], [8200, 4100])

    def test_small_photo_accepted_with_flag(self):
        norm = A.normalize_image_bytes(jpeg(200, 150))
        self.assertEqual((norm.width, norm.height), (200, 150))
        self.assertTrue(norm.flags["too_small"])
        self.assertNotIn("downscaled_from", norm.flags)

    def test_extreme_aspect_flag(self):
        self.assertTrue(A.normalize_image_bytes(jpeg(1500, 400)).flags.get("aspect"))
        self.assertNotIn("aspect", A.normalize_image_bytes(jpeg(1600, 900)).flags)

    def test_exif_rotation_applied(self):
        data = encode(halves(400, 200), "JPEG", quality=95, exif=exif_bytes(6))
        norm = A.normalize_image_bytes(data)
        self.assertEqual((norm.width, norm.height), (200, 400))
        self.assertTrue(norm.flags["exif_rotated"])
        img = open_bytes(norm.data)
        # Ориентация 6 = повернуть на 90° по часовой: левый (красный) край — наверху.
        self.assertTrue(near(img.getpixel((100, 50)), RED), img.getpixel((100, 50)))
        self.assertTrue(near(img.getpixel((100, 350)), BLUE), img.getpixel((100, 350)))
        # Ориентацию второй раз применить нельзя: в файле её больше нет.
        self.assertIsNone(img.getexif().get(0x0112))

    def test_exif_rotation_with_downscale_reports_oriented_size(self):
        data = encode(halves(3000, 1000), "JPEG", quality=90, exif=exif_bytes(8))
        norm = A.normalize_image_bytes(data)
        self.assertEqual((norm.width, norm.height), (683, 2048))
        self.assertEqual(norm.flags["downscaled_from"], [1000, 3000])
        self.assertTrue(norm.flags["exif_rotated"])

    def test_broken_orientation_does_not_reject_photo(self):
        data = encode(halves(400, 200), "JPEG", exif=exif_bytes(6))
        with mock.patch("PIL.ImageOps.exif_transpose", side_effect=RuntimeError("кривой EXIF")):
            norm = A.normalize_image_bytes(data)
        self.assertEqual((norm.width, norm.height), (400, 200))
        self.assertNotIn("exif_rotated", norm.flags)
        # Значение вне 1–8 считаем «без поворота».
        norm = A.normalize_image_bytes(encode(halves(400, 200), "JPEG", exif=exif_bytes(42)))
        self.assertEqual((norm.width, norm.height), (400, 200))
        self.assertNotIn("exif_rotated", norm.flags)

    def test_metadata_and_gps_stripped(self):
        data = encode(Image.new("RGB", (600, 400), RED), "JPEG", exif=exif_bytes(1, gps=True),
                      comment=b"shot on iPhone")
        self.assertIn(b"iPhone", data)
        self.assertTrue(Image.open(io.BytesIO(data)).getexif().get_ifd(0x8825))
        norm = A.normalize_image_bytes(data)
        out = open_bytes(norm.data)
        self.assertEqual(dict(out.getexif()), {})
        self.assertNotIn(b"Exif", norm.data)
        self.assertNotIn(b"iPhone", norm.data)
        self.assertNotIn("comment", out.info)
        self.assertNotIn("icc_profile", out.info)

    def test_polyglot_payloads_destroyed(self):
        payload = b"<html><script>alert(document.cookie)</script></html>"
        cases = {
            # HTML в комментарии JPEG: Pillow переносит его при пересохранении,
            # если не чистить info.
            "jpeg_comment": jpeg(500, 400, comment=payload),
            # ZIP и HTML в хвосте JPEG (GIFAR-подобный полиглот).
            "jpeg_tail": jpeg(500, 400) + b"PK\x03\x04" + b"\x00" * 26 + payload,
            "gif_tail": encode(Image.new("P", (300, 300), 1), "GIF") + payload,
            "png_text": encode(Image.new("RGB", (400, 300), RED), "PNG",
                               pnginfo=self._pnginfo(payload)),
        }
        for name, data in cases.items():
            with self.subTest(name):
                self.assertIn(b"<script>", data)
                norm = A.normalize_image_bytes(data)
                self.assertNotIn(b"<script", norm.data)
                self.assertNotIn(b"PK\x03\x04", norm.data)
                self.assertNotIn(b"<script", norm.thumb)
                open_bytes(norm.data)   # и это по-прежнему честная картинка

    @staticmethod
    def _pnginfo(payload: bytes):
        info = PngImagePlugin.PngInfo()
        info.add_text("Comment", payload.decode())
        info.add_text("XML:com.adobe.xmp", payload.decode(), zip=True)
        return info

    def test_alpha_kept_as_png(self):
        img = Image.new("RGBA", (400, 300), (*RED, 255))
        img.paste((0, 0, 0, 0), (0, 0, 200, 300))
        norm = A.normalize_image_bytes(encode(img, "PNG"))
        self.assertEqual((norm.ext, norm.mime), ("png", "image/png"))
        out = open_bytes(norm.data)
        self.assertEqual(out.mode, "RGBA")
        self.assertEqual(out.getpixel((10, 10))[3], 0)
        self.assertEqual(out.getpixel((300, 10))[3], 255)

    def test_opaque_alpha_becomes_jpeg(self):
        norm = A.normalize_image_bytes(encode(Image.new("RGBA", (400, 300), (*RED, 255)), "PNG"))
        self.assertEqual(norm.ext, "jpg")

    def test_palette_transparency_kept(self):
        img = Image.new("P", (300, 300), 0)
        img.putpalette([255, 0, 0, 0, 0, 255] + [0, 0, 0] * 254)
        img.paste(1, (150, 0, 300, 300))
        norm = A.normalize_image_bytes(encode(img, "PNG", transparency=0))
        self.assertEqual(norm.ext, "png")
        self.assertEqual(open_bytes(norm.data).getpixel((10, 10))[3], 0)

    def test_animated_gif_first_frame(self):
        frames = [Image.new("RGB", (320, 320), RED), Image.new("RGB", (320, 320), BLUE)]
        buf = io.BytesIO()
        frames[0].save(buf, format="GIF", save_all=True, append_images=frames[1:], duration=100, loop=0)
        norm = A.normalize_image_bytes(buf.getvalue())
        self.assertTrue(norm.flags["animated"])
        self.assertEqual(norm.ext, "jpg")
        self.assertTrue(near(open_bytes(norm.data).getpixel((160, 160)), RED))

    def test_animated_webp_first_frame(self):
        frames = [Image.new("RGB", (320, 320), BLUE), Image.new("RGB", (320, 320), RED)]
        buf = io.BytesIO()
        frames[0].save(buf, format="WEBP", save_all=True, append_images=frames[1:], duration=100)
        norm = A.normalize_image_bytes(buf.getvalue())
        self.assertTrue(norm.flags["animated"])
        self.assertTrue(near(open_bytes(norm.data).getpixel((160, 160)), BLUE))

    def test_static_gif_not_flagged(self):
        norm = A.normalize_image_bytes(encode(Image.new("RGB", (320, 320), RED), "GIF"))
        self.assertNotIn("animated", norm.flags)

    def test_cmyk_jpeg_to_rgb(self):
        norm = A.normalize_image_bytes(encode(Image.new("CMYK", (400, 300), (0, 255, 255, 0)), "JPEG"))
        out = open_bytes(norm.data)
        self.assertEqual(out.mode, "RGB")
        self.assertTrue(near(out.getpixel((10, 10)), (255, 0, 0), tol=60), out.getpixel((10, 10)))

    def test_16bit_grayscale_png(self):
        norm = A.normalize_image_bytes(encode(Image.new("I;16", (400, 300), 30000), "PNG"))
        out = open_bytes(norm.data)
        self.assertEqual(out.mode, "RGB")
        # 30000/65535 ≈ 46 % серого, а не белый от обрезки.
        self.assertTrue(near(out.getpixel((5, 5)), (117, 117, 117), tol=8), out.getpixel((5, 5)))

    def test_bmp_and_webp_accepted(self):
        for fmt in ("BMP", "WEBP"):
            with self.subTest(fmt):
                norm = A.normalize_image_bytes(encode(Image.new("RGB", (500, 400), RED), fmt))
                self.assertEqual((norm.source_format, norm.ext), (fmt, "jpg"))

    def test_icc_profile_converted_then_dropped(self):
        srgb = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
        data = encode(Image.new("RGB", (400, 300), RED), "JPEG", quality=95, icc_profile=srgb)
        norm = A.normalize_image_bytes(data)
        out = open_bytes(norm.data)
        self.assertNotIn("icc_profile", out.info)
        self.assertTrue(near(out.getpixel((5, 5)), RED, tol=12), out.getpixel((5, 5)))

    def test_broken_icc_profile_ignored(self):
        data = encode(Image.new("RGB", (400, 300), RED), "JPEG", icc_profile=b"not an icc profile")
        norm = A.normalize_image_bytes(data)
        self.assertNotIn("icc_profile", open_bytes(norm.data).info)

    @mock.patch.object(PngImagePlugin.PngImageFile, "load", side_effect=AssertionError("декодирует"))
    def test_pixel_bomb_rejected_before_decoding(self, load):
        with self.assertRaises(A.AssetError) as ctx:
            A.normalize_image_bytes(png_header_only(8000, 8000))   # 64 Мп, файл — 60 байт
        self.assertEqual((ctx.exception.code, ctx.exception.status), ("too_many_pixels", 422))
        load.assert_not_called()

    def test_huge_bomb_rejected_by_pillow_guard(self):
        for name, data in {"png": png_header_only(20000, 20000),
                           "gif": gif_header_only(60000, 60000)}.items():
            with self.subTest(name):
                with self.assertRaises(A.AssetError) as ctx:
                    A.normalize_image_bytes(data)
                self.assertEqual(ctx.exception.code, "too_many_pixels")

    def test_just_under_pixel_limit_is_not_a_bomb(self):
        with mock.patch.object(A, "MAX_PIXELS", 1000 * 1000):
            A.normalize_image_bytes(jpeg(1000, 1000))
            with self.assertRaises(A.AssetError):
                A.normalize_image_bytes(jpeg(1001, 1000))

    def test_bad_images(self):
        good = jpeg(800, 600)
        png = bytearray(encode(Image.new("RGB", (300, 300), RED), "PNG"))
        png[-20] ^= 0xFF   # испорченный IDAT/CRC
        cases = {
            "empty": b"",
            "text": b"hello, I am not an image",
            "truncated_jpeg": good[: len(good) // 2],
            "broken_png_crc": bytes(png),
            "tiff": encode(Image.new("RGB", (300, 300), RED), "TIFF"),
            "ico": encode(Image.new("RGB", (64, 64), RED), "ICO"),
            "svg": b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
        }
        for name, data in cases.items():
            with self.subTest(name):
                with self.assertRaises(A.AssetError) as ctx:
                    A.normalize_image_bytes(data)
                self.assertEqual((ctx.exception.code, ctx.exception.status), ("bad_image", 422))

    def test_eps_never_reaches_ghostscript(self):
        from PIL import EpsImagePlugin

        eps = (b"%!PS-Adobe-3.0 EPSF-3.0\n%%BoundingBox: 0 0 100 100\n"
               b"newpath 0 0 moveto 100 100 lineto stroke\nshowpage\n%%EOF\n")
        with mock.patch.object(EpsImagePlugin.EpsImageFile, "_open") as eps_open:
            with self.assertRaises(A.AssetError) as ctx:
                A.normalize_image_bytes(eps)
        self.assertEqual(ctx.exception.code, "bad_image")
        eps_open.assert_not_called()

    @mock.patch.object(A, "_ensure_heif", return_value=False)
    def test_without_pillow_heif_heic_is_bad_image_not_crash(self, _ensure):
        from PIL import Image as PILImage

        with mock.patch.dict(PILImage.OPEN, {}, clear=False):
            PILImage.OPEN.pop("HEIF", None)
            self.assertNotIn("HEIF", A._decoders())
            with self.assertRaises(A.AssetError) as ctx:
                A.normalize_image_bytes(b"\x00\x00\x00\x1cftypheic\x00\x00\x00\x00mif1heic" + b"\x00" * 64)
        self.assertEqual(ctx.exception.code, "bad_image")


class HeicTests(SimpleTestCase):
    def setUp(self):
        if not HEIF_ENCODER:
            self.skipTest("pillow-heif без HEIF-кодировщика: HEIC для теста не собрать")
        A._ensure_heif()

    def test_heic_to_jpeg(self):
        data = encode(Image.new("RGB", (640, 480), RED), "HEIF", quality=90)
        self.assertEqual(data[4:12], b"ftypheic")
        norm = A.normalize_image_bytes(data)
        self.assertEqual((norm.ext, norm.mime, norm.source_format), ("jpg", "image/jpeg", "HEIF"))
        self.assertTrue(norm.flags["heic"])
        self.assertEqual((norm.width, norm.height), (640, 480))
        self.assertTrue(near(open_bytes(norm.data).getpixel((10, 10)), RED))

    def test_heic_rotation_applied_once(self):
        data = encode(halves(400, 200), "HEIF", quality=90, exif=exif_bytes(6))
        norm = A.normalize_image_bytes(data)
        self.assertEqual((norm.width, norm.height), (200, 400))
        self.assertTrue(norm.flags["exif_rotated"])
        img = open_bytes(norm.data)
        self.assertTrue(near(img.getpixel((100, 50)), RED), img.getpixel((100, 50)))
        self.assertTrue(near(img.getpixel((100, 350)), BLUE), img.getpixel((100, 350)))

    def test_heic_with_alpha_to_png(self):
        img = Image.new("RGBA", (320, 320), (*RED, 255))
        img.paste((0, 0, 0, 0), (0, 0, 160, 320))
        norm = A.normalize_image_bytes(encode(img, "HEIF", quality=90))
        self.assertEqual(norm.ext, "png")
        self.assertTrue(norm.flags["heic"])


# ---------------------------------------------------------------- правила приёма

class UploadRulesTests(SimpleTestCase):
    def test_extensions(self):
        self.assertEqual(A.upload_extension("IMG_0001.HEIC"), ".heic")
        self.assertEqual(A.upload_extension("photo.JPG"), ".jpg")
        self.assertEqual(A.upload_extension("scan.jfif"), ".jpg")
        self.assertEqual(A.upload_extension("scan.jpe"), ".jpg")
        self.assertEqual(A.upload_extension("C:\\Users\\me\\pic.webp"), ".webp")
        # Вставка из буфера без расширения — по content_type, как в чате.
        self.assertEqual(A.upload_extension("blob", "image/png"), ".png")
        self.assertEqual(A.upload_extension("", "image/heic"), ".heic")

    def test_rejected_types(self):
        cases = [
            ("clip.mp4", "", "video_refs_unsupported"),
            ("clip.MOV", "video/quicktime", "video_refs_unsupported"),
            ("voice.mp3", "", "video_refs_unsupported"),
            ("voice.m4a", "audio/mp4", "video_refs_unsupported"),
            ("blob", "video/mp4", "video_refs_unsupported"),
            ("x.svg", "image/svg+xml", "unsupported_type"),
            ("doc.pdf", "application/pdf", "unsupported_type"),
            ("notes.txt", "", "unsupported_type"),
            ("scan.tiff", "image/tiff", "unsupported_type"),
            ("page.html", "text/html", "unsupported_type"),
            ("x.png.svg", "", "unsupported_type"),
            ("blob", "application/octet-stream", "unsupported_type"),
        ]
        for name, ctype, code in cases:
            with self.subTest(name):
                with self.assertRaises(A.AssetError) as ctx:
                    A.upload_extension(name, ctype)
                self.assertEqual((ctx.exception.code, ctx.exception.status), (code, 422))

    def test_limit_comes_from_chat(self):
        from ai import views as ai_views

        self.assertEqual(A.max_upload_bytes(), ai_views.MAX_ATTACHMENT_SIZE)
        with mock.patch.object(ai_views, "MAX_ATTACHMENT_SIZE", 1234):
            self.assertEqual(A.max_upload_bytes(), 1234)

    def test_single_upload(self):
        one = upload(b"x")
        self.assertIs(A.single_upload(MultiValueDict({"file": [one]})), one)
        for files in (MultiValueDict(), MultiValueDict({"file": [one, upload(b"y")]}),
                      MultiValueDict({"file": [one], "other": [upload(b"y")]})):
            with self.assertRaises(A.AssetError) as ctx:
                A.single_upload(files)
            self.assertEqual((ctx.exception.code, ctx.exception.status), ("bad_request", 400))

    def test_error_response_shape(self):
        err = A.AssetError("file_too_large", "Файл слишком большой", status=413, max_bytes=10)
        self.assertEqual(err.response_data(),
                         {"error": "Файл слишком большой", "error_code": "file_too_large", "max_bytes": 10})


# ---------------------------------------------------------------- приём в библиотеку

class IngestUploadTests(TestCase):
    def setUp(self):
        self._media = f.media_root()
        self._media.__enter__()
        self.addCleanup(self._media.__exit__, None, None, None)
        self.user = f.make_user()
        self.project = f.make_project(self.user)

    def test_upload_creates_ready_asset_with_files(self):
        data = jpeg(1200, 900, exif=exif_bytes(1, gps=True))
        asset, created = A.ingest_upload(self.user, upload(data, "IMG 0001.jpg"), self.project)
        self.assertTrue(created)
        asset.refresh_from_db()
        self.assertEqual((asset.kind, asset.source, asset.status),
                         (Asset.KIND_IMAGE, Asset.SOURCE_UPLOAD, Asset.STATUS_READY))
        self.assertEqual(asset.user, self.user)
        self.assertEqual(asset.project, self.project)
        self.assertEqual(asset.file, f"vstudio/{self.user.pk}/{asset.uid}.jpg")
        self.assertEqual(asset.thumb, f"vstudio/{self.user.pk}/{asset.uid}_t.jpg")
        self.assertEqual((asset.width, asset.height, asset.mime), (1200, 900, "image/jpeg"))
        self.assertEqual(asset.sha256, A.sha256_hex(data))
        self.assertEqual(asset.meta["original_name"], "IMG 0001.jpg")
        self.assertEqual(asset.meta["original_bytes"], len(data))
        self.assertEqual(asset.meta["original_format"], "jpeg")
        stored = read(asset.file)
        self.assertEqual(asset.bytes, len(stored))
        self.assertNotIn(b"iPhone", stored)   # EXIF/GPS не доехали до /media
        self.assertLessEqual(max(open_bytes(read(asset.thumb)).size), 480)
        self.assertTrue(asset.url.endswith(f"{asset.uid}.jpg"))

    def test_png_with_alpha_stored_as_png(self):
        img = Image.new("RGBA", (400, 400), (0, 0, 0, 0))
        asset, _ = A.ingest_upload(self.user, upload(encode(img, "PNG"), "sticker.png", "image/png"))
        self.assertTrue(asset.file.endswith(f"{asset.uid}.png"))
        self.assertEqual(asset.mime, "image/png")
        self.assertIsNone(asset.project)

    def test_heic_upload(self):
        if not HEIF_ENCODER:
            self.skipTest("pillow-heif без HEIF-кодировщика")
        A._ensure_heif()
        data = encode(halves(400, 200), "HEIF", quality=90, exif=exif_bytes(6))
        asset, created = A.ingest_upload(self.user, upload(data, "IMG_0042.HEIC", ""))
        self.assertTrue(created)
        self.assertTrue(asset.file.endswith(".jpg"))
        self.assertEqual(asset.mime, "image/jpeg")
        self.assertEqual((asset.width, asset.height), (200, 400))
        self.assertTrue(asset.flags["heic"])
        self.assertTrue(asset.flags["exif_rotated"])
        self.assertEqual(asset.meta["original_format"], "heif")
        self.assertEqual(open_bytes(read(asset.file)).format, "JPEG")

    def test_content_decides_format_not_extension(self):
        # JPEG под именем .png и PNG под именем .jpg — берём по содержимому.
        a, _ = A.ingest_upload(self.user, upload(jpeg(500, 500), "really_jpeg.png", "image/png"))
        self.assertEqual(a.meta["original_format"], "jpeg")
        img = Image.new("RGBA", (500, 500), (0, 0, 0, 0))
        b, _ = A.ingest_upload(self.user, upload(encode(img, "PNG"), "really_png.jpg"))
        self.assertEqual(b.mime, "image/png")

    def test_small_photo_accepted_and_flagged(self):
        asset, created = A.ingest_upload(self.user, upload(jpeg(240, 180)))
        self.assertTrue(created)
        self.assertTrue(asset.flags["too_small"])
        self.assertEqual((asset.width, asset.height), (240, 180))

    def test_duplicate_returns_existing(self):
        data = jpeg(700, 500)
        first, created1 = A.ingest_upload(self.user, upload(data, "a.jpg"), self.project)
        other_project = f.make_project(self.user)
        second, created2 = A.ingest_upload(self.user, upload(data, "copy of a.jpg"), other_project)
        self.assertTrue(created1)
        self.assertFalse(created2)
        self.assertEqual(second.pk, first.pk)
        self.assertEqual(second.project, self.project)
        self.assertEqual(Asset.objects.filter(user=self.user).count(), 1)
        self.assertEqual(len(default_storage.listdir(f"vstudio/{self.user.pk}")[1]), 2)  # файл + превью

    def test_duplicate_is_per_user_and_ignores_deleted_and_generated(self):
        data = jpeg(700, 500, color=(1, 2, 3))
        mine, _ = A.ingest_upload(self.user, upload(data))
        stranger, created = A.ingest_upload(f.make_user(), upload(data))
        self.assertTrue(created)
        self.assertNotEqual(stranger.pk, mine.pk)

        Asset.objects.filter(pk=mine.pk).update(deleted_at=timezone.now())
        again, created = A.ingest_upload(self.user, upload(data))
        self.assertTrue(created)
        self.assertNotEqual(again.pk, mine.pk)

        other = jpeg(700, 500, color=(9, 9, 9))
        f.make_asset(self.user, source=Asset.SOURCE_GENERATED_IMAGE, sha256=A.sha256_hex(other))
        _, created = A.ingest_upload(self.user, upload(other))
        self.assertTrue(created)

    def test_too_large_rejected_before_reading(self):
        from ai import views as ai_views

        file = upload(jpeg(400, 300))
        with mock.patch.object(ai_views, "MAX_ATTACHMENT_SIZE", 100), \
                mock.patch.object(file, "chunks", side_effect=AssertionError("читали")):
            with self.assertRaises(A.AssetError) as ctx:
                A.ingest_upload(self.user, file)
        self.assertEqual((ctx.exception.code, ctx.exception.status), ("file_too_large", 413))
        self.assertIn("error", ctx.exception.response_data())

    def test_too_large_caught_while_reading_when_size_lies(self):
        from ai import views as ai_views

        file = upload(jpeg(400, 300))
        file.size = 10   # клиент/обёртка соврали о размере
        with mock.patch.object(ai_views, "MAX_ATTACHMENT_SIZE", 100):
            with self.assertRaises(A.AssetError) as ctx:
                A.ingest_upload(self.user, file)
        self.assertEqual(ctx.exception.code, "file_too_large")

    def test_rejections_leave_nothing_behind(self):
        cases = [
            (upload(b"GIF89a not really", "fake.gif", "image/gif"), "bad_image"),
            (upload(png_header_only(9000, 9000), "bomb.png", "image/png"), "too_many_pixels"),
            (upload(b"\x00" * 64, "clip.mp4", "video/mp4"), "video_refs_unsupported"),
            (upload(b"<svg/>", "x.svg", "image/svg+xml"), "unsupported_type"),
            (upload(b"", "empty.jpg"), "bad_image"),
        ]
        for file, code in cases:
            with self.subTest(code):
                with self.assertRaises(A.AssetError) as ctx:
                    A.ingest_upload(self.user, file)
                self.assertEqual(ctx.exception.code, code)
        self.assertFalse(Asset.objects.exists())
        self.assertFalse(default_storage.exists(f"vstudio/{self.user.pk}"))

    def test_polyglot_upload_stored_clean(self):
        data = jpeg(600, 400) + b"PK\x03\x04" + b"\x00" * 26 + b"<script>alert(1)</script>"
        asset, _ = A.ingest_upload(self.user, upload(data, "cat.jpg"))
        stored = read(asset.file)
        self.assertNotIn(b"<script", stored)
        self.assertNotIn(b"PK\x03\x04", stored)
        self.assertEqual(asset.sha256, A.sha256_hex(data))   # дубль ищется по исходнику

    def test_foreign_project_is_programming_error(self):
        with self.assertRaises(ValueError):
            A.ingest_upload(self.user, upload(jpeg()), f.make_project())

    def test_files_removed_if_row_not_saved(self):
        with mock.patch.object(Asset, "save", side_effect=RuntimeError("db down")):
            with self.assertRaises(RuntimeError):
                A.ingest_upload(self.user, upload(jpeg(500, 400)))
        _dirs, files = default_storage.listdir(f"vstudio/{self.user.pk}")
        self.assertEqual(files, [])


# ---------------------------------------------------------------- хранение для конвейера

class StoreImageBytesTests(TestCase):
    """Контракт для BE-7: картинка от модели → файлы → поля pending-ассета."""

    def setUp(self):
        self._media = f.media_root()
        self._media.__enter__()
        self.addCleanup(self._media.__exit__, None, None, None)

    def test_store_and_fill_pending_asset(self):
        user = f.make_user()
        pending = f.make_asset(user, source=Asset.SOURCE_GENERATED_IMAGE, status=Asset.STATUS_PENDING,
                               width=None, height=None)
        blob = encode(Image.new("RGB", (1024, 1536), RED), "PNG")
        stored = A.store_image_bytes(user.pk, pending.uid, blob)
        self.assertEqual(stored.file, f"vstudio/{user.pk}/{pending.uid}.jpg")
        self.assertEqual(stored.thumb, f"vstudio/{user.pk}/{pending.uid}_t.jpg")
        self.assertEqual(stored.paths, [stored.file, stored.thumb])
        fields = stored.asset_fields()
        self.assertEqual(set(fields), {"file", "thumb", "mime", "bytes", "width", "height", "flags", "sha256"})
        self.assertEqual((fields["width"], fields["height"], fields["mime"]), (1024, 1536, "image/jpeg"))
        self.assertEqual(fields["sha256"], A.sha256_hex(blob))
        Asset.objects.filter(pk=pending.pk, status=Asset.STATUS_PENDING).update(
            status=Asset.STATUS_READY, **fields)
        pending.refresh_from_db()
        self.assertEqual(pending.bytes, len(read(pending.file)))

        A.delete_files(*stored.paths)
        self.assertFalse(default_storage.exists(stored.file))
        self.assertFalse(default_storage.exists(stored.thumb))
        A.delete_files("", "vstudio/nope/missing.jpg")   # не падает

    def test_store_rejects_bad_bytes_without_files(self):
        with self.assertRaises(A.AssetError):
            A.store_image_bytes(1, "a" * 32, b"<svg/>")
        self.assertFalse(default_storage.exists("vstudio/1"))


# ---------------------------------------------------------------- последний кадр

class LastFrameTests(TestCase):
    def setUp(self):
        self._media = f.media_root()
        self._media.__enter__()
        self.addCleanup(self._media.__exit__, None, None, None)
        self.user = f.make_user()
        self.shot = f.make_shot(self.user)
        self.take = f.make_take(self.shot, status=Take.STATUS_DONE)
        video = Asset(user=self.user, project=self.shot.project, kind=Asset.KIND_VIDEO,
                      source=Asset.SOURCE_GENERATED_VIDEO, origin_take=self.take, mime="video/mp4")
        video.file = default_storage.save(f"vstudio/{self.user.pk}/{video.uid}.mp4",
                                          io.BytesIO(b"fake-mp4-bytes"))
        video.save()
        Take.objects.filter(pk=self.take.pk).update(result_asset=video)
        self.take.refresh_from_db()
        self.frame = jpeg(3840, 2160, color=RED)

    def test_frame_asset_created_once(self):
        with mock.patch("ai.video_edit.extract_last_frame", return_value=self.frame) as extract:
            asset, created = A.from_take_last_frame(self.take)
            again, created_again = A.from_take_last_frame(self.take)
        self.assertTrue(created)
        self.assertFalse(created_again)
        self.assertEqual(again.pk, asset.pk)
        extract.assert_called_once_with(b"fake-mp4-bytes")
        asset.refresh_from_db()
        self.assertEqual((asset.kind, asset.source, asset.status),
                         (Asset.KIND_IMAGE, Asset.SOURCE_FRAME, Asset.STATUS_READY))
        self.assertEqual((asset.user_id, asset.project_id, asset.origin_take_id),
                         (self.user.pk, self.shot.project_id, self.take.pk))
        self.assertEqual((asset.width, asset.height), (2048, 1152))   # 4K-кадр ужат
        self.assertEqual(asset.flags["downscaled_from"], [3840, 2160])
        self.assertEqual(asset.meta, {"at": "last_frame", "take": self.take.uid})
        self.assertTrue(default_storage.exists(asset.file))
        self.assertTrue(default_storage.exists(asset.thumb))

    def test_deleted_frame_is_made_again(self):
        with mock.patch("ai.video_edit.extract_last_frame", return_value=self.frame):
            first, _ = A.from_take_last_frame(self.take)
            Asset.objects.filter(pk=first.pk).update(deleted_at=timezone.now())
            second, created = A.from_take_last_frame(self.take)
        self.assertTrue(created)
        self.assertNotEqual(first.pk, second.pk)

    def test_not_done_or_not_video(self):
        running = f.make_take(f.make_shot(self.user), status=Take.STATUS_RUNNING)
        with self.assertRaises(A.AssetError) as ctx:
            A.from_take_last_frame(running)
        self.assertEqual((ctx.exception.code, ctx.exception.status), ("take_not_ready", 409))

        image_take = f.make_take(f.make_shot(self.user, kind="image"), status=Take.STATUS_DONE)
        with self.assertRaises(A.AssetError) as ctx:
            A.from_take_last_frame(image_take)
        self.assertEqual((ctx.exception.code, ctx.exception.status), ("take_not_found", 404))

    def test_extraction_failures(self):
        with mock.patch("ai.video_edit.extract_last_frame", return_value=None):
            with self.assertRaises(A.AssetError) as ctx:
                A.from_take_last_frame(self.take)
        self.assertEqual(ctx.exception.code, "frame_failed")

        with mock.patch("ai.video_edit.extract_last_frame", return_value=b"not a jpeg"):
            with self.assertRaises(A.AssetError) as ctx:
                A.from_take_last_frame(self.take)
        self.assertEqual(ctx.exception.code, "frame_failed")

        default_storage.delete(self.take.result_asset.file)
        with mock.patch("ai.video_edit.extract_last_frame") as extract:
            with self.assertRaises(A.AssetError) as ctx:
                A.from_take_last_frame(self.take)
        self.assertEqual(ctx.exception.code, "frame_failed")
        extract.assert_not_called()

        Take.objects.filter(pk=self.take.pk).update(result_asset=None)
        self.take.refresh_from_db()
        with self.assertRaises(A.AssetError) as ctx:
            A.from_take_last_frame(self.take)
        self.assertEqual(ctx.exception.code, "frame_failed")
        self.assertFalse(Asset.objects.filter(source=Asset.SOURCE_FRAME).exists())
