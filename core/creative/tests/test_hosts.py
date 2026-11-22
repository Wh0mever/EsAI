"""Скачивание результатов — только с хостов поставщика и CloudFront (SEC-3)."""
from django.test import SimpleTestCase, override_settings

from creative import hf


class MediaHostTests(SimpleTestCase):
    def test_provider_cdn_hosts_allowed(self):
        for url in (
            "https://cdn.higgsfield.ai/a/b.png",
            "https://static.higgsfield.ai/x.mp4",
            "https://static-public-media.higgsfield.ai/y.webp",
            "https://d3u0tzju9qaucj.cloudfront.net/z.png",
        ):
            self.assertTrue(hf.media_host_allowed(url), url)

    def test_other_hosts_refused(self):
        for url in (
            "http://cdn.higgsfield.ai/a.png",  # не https
            "https://127.0.0.1/a.png",
            "https://localhost/a.png",
            "https://evil.example/a.png",
            "https://higgsfield.ai.evil.example/a.png",
            "https://core:8000/api/",
            "not a url",
        ):
            self.assertFalse(hf.media_host_allowed(url), url)

    @override_settings(CREATIVE_MEDIA_EXTRA_HOSTS=["media.partner.example"])
    def test_extra_host_from_settings(self):
        self.assertTrue(hf.media_host_allowed("https://media.partner.example/a.png"))

    def test_download_refuses_foreign_host(self):
        with self.assertRaises(hf.HFError):
            hf.download("https://evil.example/a.png", "/tmp/never-written", max_bytes=10)
