# -*- coding: utf-8 -*-
"""Ссылки Академии: ссылка на курс и ссылка кнопки «Предложить курс»."""
from django.test import SimpleTestCase

from academy import links


class CourseUrlTests(SimpleTestCase):
    def code(self, raw):
        with self.assertRaises(links.LinkError) as ctx:
            links.clean_url(raw)
        return ctx.exception.code

    def test_good_links_are_kept_or_completed(self):
        cases = {
            "https://example.com/kurs": "https://example.com/kurs",
            "  https://example.com/kurs?utm_source=esai#top  ":
                "https://example.com/kurs?utm_source=esai#top",
            "HTTP://Example.com/x": "http://Example.com/x",
            "example.com/kurs": "https://example.com/kurs",
            "www.example.com": "https://www.example.com",
            "https://курсы.рф/x": "https://курсы.рф/x",
            "курсы.рф": "https://курсы.рф",
            "https://sub.example.co.uk:8443/a/b": "https://sub.example.co.uk:8443/a/b",
            "https://xn--j1amdg6b.xn--p1ai/": "https://xn--j1amdg6b.xn--p1ai/",
            "": "",
        }
        for raw, expected in cases.items():
            self.assertEqual(links.clean_url(raw), expected, raw)

    def test_foreign_schemes_are_refused(self):
        for raw in ("javascript:alert(1)", "JaVaScRiPt:alert(1)", "javascript://%0aalert(1)",
                    "data:text/html;base64,PHNjcmlwdD4=", "ftp://files.example.com/x",
                    "mailto:a@example.com", "tg://resolve?domain=esai", "//example.com/x",
                    "vbscript:msgbox(1)", "localhost:3000/x"):
            self.assertEqual(self.code(raw), "url_scheme", raw)

    def test_login_and_password_are_refused(self):
        for raw in ("https://u:p@example.com", "https://user@example.com/x",
                    "https://example.com:443@evil.com/", "https://example.com%2F@evil.com"):
            self.assertEqual(self.code(raw), "url_userinfo", raw)

    def test_internal_addresses_are_refused(self):
        for raw in ("https://localhost/", "http://localhost:3000/", "http://10.0.0.1/",
                    "http://127.0.0.1/", "http://192.168.1.10/kurs", "http://[::1]/",
                    "http://169.254.169.254/latest/meta-data", "http://100.64.0.1/",
                    "http://127.1/", "http://0x7f.1/", "http://2130706433/", "https://intranet/",
                    "https://foo.local/", "https://app.localhost/", "https://db.internal/x",
                    "https://localhost./", "https://site.onion/"):
            self.assertEqual(self.code(raw), "url_local", raw)

    def test_malformed_links_are_refused(self):
        for raw in ("https://exa mple.com", "https://example.com\\@evil.com",
                    "https://example.com/‮gnp.exe", "https://exam​ple.com",
                    "http://8.8.8.8/", "https://-bad-.com/", "https://exa_mple.com/",
                    "https://example.com:99999/", "https://example.c/", "https://%65xample.com/",
                    "https://", "https:///kurs", "https://[::1/", "https://a..b.com/"):
            self.assertEqual(self.code(raw), "url_invalid", raw)

    def test_length_limit(self):
        base = "https://example.com/"
        self.assertEqual(links.clean_url(base + "a" * (links.URL_MAX - len(base))),
                         base + "a" * (links.URL_MAX - len(base)))
        self.assertEqual(self.code(base + "a" * (links.URL_MAX - len(base) + 1)), "url_too_long")

    def test_stored_link_must_be_final_form(self):
        self.assertTrue(links.valid_course_url("https://example.com/kurs"))
        self.assertFalse(links.valid_course_url("example.com/kurs"))
        self.assertFalse(links.valid_course_url("javascript:alert(1)"))
        self.assertFalse(links.valid_course_url(""))

    def test_idna_deviation_letters_are_refused(self):
        # Python пишет straße.de как strasse.de, браузер открывает xn--strae-oqa.de:
        # хост в панели разошёлся бы с настоящим.
        for raw in ("https://straße.de/kurs", "https://STRAẞE.de/", "straße.de",
                    "https://ας.gr/", "https://kurs.straße.de/"):
            self.assertEqual(self.code(raw), "url_invalid", raw)
            self.assertEqual(links.ascii_host(raw), "", raw)
        # ß в пути и в запросе — не хост, ссылка годится.
        self.assertEqual(links.clean_url("https://example.com/straße?q=ς"), "https://example.com/straße?q=ς")
        # Заглавная сигма и браузер, и Python пишут одинаково (σ).
        self.assertEqual(links.ascii_host("https://ΑΣ.gr/"), "xn--mxa0b.gr")
        with self.assertRaises(links.LinkError):
            links.clean_suggest_url("https://straße.de/")

    def test_ascii_host_shows_punycode(self):
        self.assertEqual(links.ascii_host("https://курсы.рф/x"), "xn--j1amdg6b.xn--p1ai")
        self.assertEqual(links.ascii_host("https://Example.COM/x"), "example.com")
        self.assertEqual(links.ascii_host("javascript:alert(1)"), "")
        self.assertEqual(links.ascii_host(""), "")


class SuggestUrlTests(SimpleTestCase):
    def test_telegram_forms_become_https_t_me(self):
        cases = {
            "@my_channel": "https://t.me/my_channel",
            "my_channel": "https://t.me/my_channel",
            " t.me/my_channel ": "https://t.me/my_channel",
            "http://t.me/my_channel": "https://t.me/my_channel",
            "https://www.t.me/my_channel": "https://t.me/my_channel",
            "https://telegram.me/joinchat/AbC-12": "https://t.me/joinchat/AbC-12",
            "telegram.dog/esai": "https://t.me/esai",
            "https://t.me/+AbCd_123": "https://t.me/+AbCd_123",
            "t.me/esai_bot?start=academy": "https://t.me/esai_bot?start=academy",
            "https://forms.example.com/a": "https://forms.example.com/a",
            "forms.example.com/a": "https://forms.example.com/a",
            "": "",
            "   ": "",
            None: "",
        }
        for raw, expected in cases.items():
            self.assertEqual(links.clean_suggest_url(raw), expected, raw)

    def test_bad_suggest_links_are_refused(self):
        for raw in ("javascript:alert(1)", "http://forms.example.com/a", "@ab", "t.me", "t.me/",
                    "https://t.me/a b", "t.me/esai#x", "https://localhost/",
                    "tg://resolve?domain=x",
                    "https://u:p@t.me/esai", 42, ["@esai"], "https://t.me/" + "a" * 400):
            with self.assertRaises(links.LinkError, msg=repr(raw)) as ctx:
                links.clean_suggest_url(raw)
            self.assertEqual(ctx.exception.code, "suggest_invalid")

    def test_safe_read_drops_bad_stored_value(self):
        self.assertEqual(links.safe_suggest_url("javascript:alert(1)"), "")
        self.assertEqual(links.safe_suggest_url("@esai"), "https://t.me/esai")
