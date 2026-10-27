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
                    "https://example.com/\u202egnp.exe", "https://exam\u200bple.com",
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
            links.parse_suggest("https://straße.de/")

    def test_dot_made_by_nfkc_is_refused(self):
        # Python делит имя на метки до NFKC и видит exa.mple.com, а браузер такую ссылку не
        # открывает: карточка курса на сайте молча пропала бы.
        for raw in ("https://exa\u2024mple.com/", "https://exa\ufe12mple.com/", "https://exa\ufe19mple.com/",
                    "https://exa\U0001f100mple.com/", "https://\u2488example.com/", "exa\u2024mple.com/kurs"):
            self.assertEqual(self.code(raw), "url_invalid", raw)
            self.assertEqual(links.ascii_host(raw), "", raw)
            self.assertFalse(links.valid_course_url(raw), raw)

    def test_host_the_browser_reads_differently_is_refused(self):
        # Python кодирует хост по Unicode 3.2, браузер — по UTS46. U+0378 и U+FE47 («[») браузер
        # не откроет (карточка пропала бы), U+1FBF1 прочтёт как «1» (обход «внутреннего адреса»),
        # U+180F и Cherokee приведёт к другому хосту, чем покажет панель.
        for raw in ("https://a\u0378b.com/", "https://a\ufe47b.com/", "https://10.0.0.\U0001fbf1/",
                    "https://0x7f.\U0001fbf1/kurs", "https://127.0.0.\u3164/", "https://a\u180fb.com/",
                    "https://\u13a0example.com/"):
            self.assertEqual(self.code(raw), "url_invalid", raw)
            self.assertEqual(links.ascii_host(raw), "", raw)
            self.assertFalse(links.valid_course_url(raw), raw)
        self.assertEqual(links.ascii_host("https://курсы.рф/x"), "xn--j1amdg6b.xn--p1ai")
        self.assertEqual(links.clean_url("https://ESAI.kg/x"), "https://ESAI.kg/x")

    def test_ascii_host_shows_punycode(self):
        self.assertEqual(links.ascii_host("https://курсы.рф/x"), "xn--j1amdg6b.xn--p1ai")
        self.assertEqual(links.ascii_host("https://Example.COM/x"), "example.com")
        self.assertEqual(links.ascii_host("javascript:alert(1)"), "")
        self.assertEqual(links.ascii_host(""), "")


class SuggestTests(SimpleTestCase):
    """«Предложить курс»: ссылка, e-mail или текст (CONTRACT_ACADEMY §5)."""

    def parsed(self, raw):
        item = links.parse_suggest(raw)
        self.assertIsNotNone(item, repr(raw))
        # Сохранённое значение разбирается так же: сайт и панель перепроверяют его при каждом чтении.
        self.assertEqual(links.parse_suggest(item.value), item, repr(raw))
        return item

    def refused(self, raw):
        with self.assertRaises(links.LinkError, msg=repr(raw)) as ctx:
            links.parse_suggest(raw)
        return ctx.exception

    def assert_kind(self, cases, kind):
        for raw, value in cases.items():
            item = self.parsed(raw)
            self.assertEqual((item.kind, item.value), (kind, value), repr(raw))

    def test_empty_means_nothing(self):
        for raw in (None, "", "   ", "\n\t\r\n"):
            self.assertIsNone(links.parse_suggest(raw), repr(raw))
            self.assertIsNone(links.safe_suggest(raw), repr(raw))

    def test_not_a_string(self):
        for raw in (42, ["@esai"], {"a": 1}, True):
            err = self.refused(raw)
            self.assertEqual((err.code, err.message), ("suggest_type", "Предложить курс: нужна строка"))

    def test_telegram_forms_become_https_t_me(self):
        self.assert_kind({
            "@my_channel": "https://t.me/my_channel",
            " t.me/my_channel ": "https://t.me/my_channel",
            "http://t.me/my_channel": "https://t.me/my_channel",
            "HTTPS://WWW.T.ME/my_channel": "https://t.me/my_channel",
            "https://telegram.me/joinchat/AbC-12": "https://t.me/joinchat/AbC-12",
            "telegram.dog/esai": "https://t.me/esai",
            "https://t.me/+AbCd_123": "https://t.me/+AbCd_123",
            "t.me/esai_bot?start=academy": "https://t.me/esai_bot?start=academy",
        }, "url")
        self.assertEqual(self.parsed("@esai_academy").as_json(),
                         {"kind": "url", "text": "https://t.me/esai_academy",
                          "href": "https://t.me/esai_academy"})

    def test_other_telegram_paths_are_plain_links(self):
        # Путь не по шаблону Telegram — обычная ссылка на t.me, а не отказ.
        self.assert_kind({"t.me/esai#x": "https://t.me/esai#x", "https://t.me/esai#x": "https://t.me/esai#x",
                          "t.me": "https://t.me"}, "url")

    def test_name_without_at_or_too_short_is_text(self):
        self.assert_kind({"my_channel": "my_channel", "Academy": "Academy", "@ab": "@ab"}, "text")

    def test_bare_email(self):
        cases = {
            "academy@esai.kg": ("academy@esai.kg", "mailto:academy@esai.kg"),
            " Academy@Esai.KG ": ("Academy@Esai.KG", "mailto:Academy@esai.kg"),
            "first.last+academy@mail.example.com": ("first.last+academy@mail.example.com",
                                                    "mailto:first.last+academy@mail.example.com"),
            "academy@курсы.рф": ("academy@курсы.рф", "mailto:academy@xn--j1amdg6b.xn--p1ai"),
            "почта@курсы.рф": ("почта@курсы.рф",
                               "mailto:%D0%BF%D0%BE%D1%87%D1%82%D0%B0@xn--j1amdg6b.xn--p1ai"),
            "a_b-c@xn--j1amdg6b.xn--p1ai": ("a_b-c@xn--j1amdg6b.xn--p1ai",
                                            "mailto:a_b-c@xn--j1amdg6b.xn--p1ai"),
        }
        for raw, (text, href) in cases.items():
            item = self.parsed(raw)
            self.assertEqual(item.as_json(), {"kind": "email", "text": text, "href": href}, raw)
            self.assertEqual(item.value, text, raw)

    def test_mailto_keeps_only_the_address(self):
        cases = {
            "mailto:academy@esai.kg": "academy@esai.kg",
            "MAILTO:academy@esai.kg?subject=Курс в EsAI&body=Здравствуйте": "academy@esai.kg",
            "mailto:academy@esai.kg#top": "academy@esai.kg",
            "mailto:%D0%BF%D0%BE%D1%87%D1%82%D0%B0@esai.kg": "почта@esai.kg",
        }
        for raw, address in cases.items():
            item = self.parsed(raw)
            self.assertEqual((item.kind, item.value, item.text), ("email", address, address), raw)
            self.assertNotIn("?", item.href, raw)
        # Копию и прочие параметры не протащить: href — только адрес.
        self.assertEqual(self.parsed("mailto:a@b.kg?cc=other@example.com").href, "mailto:a@b.kg")

    def test_mailto_without_one_address_is_text(self):
        # Не отказ, а текст: годный адрес внутри сайт всё равно сделает ссылкой.
        self.assert_kind({raw: raw for raw in (
            "mailto:", "mailto:foo", "mailto:a@b.kg,c@d.kg", "mailto:a%40b@c.kg", "mailto:a%0A@b.kg",
            "mailto:a@b.kg%0A", "mailto:a@b.kg%00", "mailto:a%E2%80%AE@b.kg", "mailto:a@localhost",
            "mailto:javascript:alert(1)", "mailto:%20a@b.kg", "mailto://a@b.kg",
            "mailto:a@b\ufe12c.kg",
            # \u041d\u0435\u0432\u0438\u0434\u0438\u043c\u044b\u0435 \u0437\u043d\u0430\u043a\u0438 %-\u043a\u043e\u0434\u043e\u043c: nameprep \u0432\u044b\u0431\u0440\u043e\u0441\u0438\u043b \u0431\u044b \u0438\u0445 \u0438\u0437 \u0434\u043e\u043c\u0435\u043d\u0430, \u0430 \u0432 \u0437\u043d\u0430\u0447\u0435\u043d\u0438\u0435 \u043e\u043d\u0438 \u043f\u043e\u043f\u0430\u043b\u0438 \u0431\u044b.
            "mailto:a@b%C2%ADc.kg", "mailto:academy@es%E2%80%8Bai.kg?subject=x",
            "mailto:a@bc.kg%E2%81%A6", "mailto:a@b%EF%BB%BFc.kg")}, "text")
        self.assertEqual(self.parsed("mailto:a@b.kg пишите").as_json(),
                         {"kind": "text", "text": "mailto:a@b.kg пишите", "href": None})

    def test_not_an_address_is_text(self):
        self.assert_kind({raw: raw for raw in (
            "a@b", "academy@localhost", "a..b@esai.kg", ".a@esai.kg", "academy@esai.kg.",
            "academy@1.2.3.4", "academy@straße.de", "a@b@esai.kg", "academy@-esai.kg",
            "a@b\ufe12c.kg", "a@b\ufe19c.kg", "a@b\U0001f100c.kg", "a@b\u2488c.kg",
            "academy@esai\u2024kg",
            # U+180F \u0438 U+3164 \u0431\u0440\u0430\u0443\u0437\u0435\u0440 \u0432\u044b\u0431\u0440\u043e\u0441\u0438\u0442 \u0438\u0437 \u0434\u043e\u043c\u0435\u043d\u0430: \u043f\u0438\u0441\u044c\u043c\u043e \u0443\u0448\u043b\u043e \u0431\u044b \u043d\u0435 \u043d\u0430 \u0442\u043e\u0442 \u0430\u0434\u0440\u0435\u0441, \u0447\u0442\u043e \u0432 API.
            "x@a\u180fb.kg", "x@a\u3164b.kg")}, "text")

    def test_any_http_link_is_allowed(self):
        for raw in ("https://forms.example.com/academy", "http://forms.example.com/a?x=1#y",
                    "http://localhost:3000/form", "https://localhost/", "http://127.0.0.1/",
                    "http://10.0.0.1/", "http://192.168.1.10/kurs", "http://169.254.169.254/latest",
                    "http://8.8.8.8/", "http://[::1]:8080/x", "https://intranet/", "https://app.local/",
                    "https://medium.com/@user", "https://exa_mple.com/", "https://курсы.рф/x",
                    "https://xn--j1amdg6b.xn--p1ai/", "https://example.com:8443/a", "https://example.com./",
                    "https://example.com/straße?q=ς", "https://example\u3002com/",
                    "https://docs.google.com/forms/d/e/1FAIpQ/viewform?usp=sf_link"):
            self.assertEqual(self.parsed(raw).as_json(), {"kind": "url", "text": raw, "href": raw}, raw)
        # Схема — строчными, http остаётся http.
        self.assertEqual(self.parsed("HTTPS://Example.com/X").value, "https://Example.com/X")
        self.assertEqual(self.parsed("Http://example.com").value, "http://example.com")

    def test_course_rules_do_not_follow_suggest(self):
        # «Любая ссылка» — только для «Предложить курс»: ссылка курса по-прежнему строгая.
        for raw in ("http://localhost:3000/form", "http://10.0.0.1/", "http://8.8.8.8/",
                    "https://exa_mple.com/", "https://intranet/"):
            self.assertEqual(self.parsed(raw).kind, "url", raw)
            with self.assertRaises(links.LinkError, msg=raw):
                links.clean_url(raw)

    def test_address_without_scheme_gets_https(self):
        self.assert_kind({
            "example.com": "https://example.com",
            "esai.kg": "https://esai.kg",
            "ESAI.KG/Kurs": "https://ESAI.KG/Kurs",
            "www.example.com/path?a=1": "https://www.example.com/path?a=1",
            "курсы.рф": "https://курсы.рф",
            "КУРСЫ.РФ": "https://КУРСЫ.РФ",
            "курсы.kg": "https://курсы.kg",
            "мектеп.қаз": "https://мектеп.қаз",
            "магазин.онлайн/x": "https://магазин.онлайн/x",
            "example.com:8080/x": "https://example.com:8080/x",
            "t.me/esai#x": "https://t.me/esai#x",
        }, "url")

    def test_prose_with_a_dot_is_not_a_button(self):
        # Домен верхнего уровня — латиницей (2–24 буквы) или настоящий кириллический; кириллица с
        # латиницей в одной метке — подмена букв. Иначе «Скоро.Ждите» стало бы кнопкой.
        self.assert_kind({raw: raw for raw in (
            "Скоро.Ждите", "Привет.Мир", "курсы.ру", "a.b", "e.g", "10.0.0.1", "127.0.0.1:8000/x",
            "сайт.kg1", "x." + "a" * 25, "xn--j1amdg6b.xn--p1ai", "p\u0430ypal.com", "\u0435sai.kg/form",
            "esai.\u043ag", "example.com\u3002", "exa\ufe12mple.com", "exa\ufe19mple.com",
            "exa\U0001f100mple.com", "xn--zz.com")}, "text")
        # Со схемой правила прежние: ссылка остаётся ссылкой.
        self.assertEqual(self.parsed("https://\u0435sai.kg/form").kind, "url")
        self.assertEqual(self.parsed("http://10.0.0.1").kind, "url")

    def test_address_like_but_not_a_link_is_text(self):
        # Без схемы, но ссылкой не откроется или в нём @ — это текст, а не отказ.
        self.assert_kind({raw: raw for raw in (
            "3.14", "v1.2", "127.1", "example.com:99999", "medium.com/@user", "exa\u2024mple.com",
            "a\u0378b.com")}, "text")

    def test_text_is_normalised_and_keeps_lines(self):
        cases = {
            "Пишите на academy@esai.kg": "Пишите на academy@esai.kg",
            "+996 555 123 456": "+996 555 123 456",
            "Email: academy@esai.kg": "Email: academy@esai.kg",
            "Tel: +996 555 123 456": "Tel: +996 555 123 456",
            "t.me/a b": "t.me/a b",
            "<b>жирный</b> & <script>": "<b>жирный</b> & <script>",
            "  Пишите\tнам:  \r\n\r\n\n  academy@esai.kg  \r  или   @esai_academy ":
                "Пишите нам:\nacademy@esai.kg\nили @esai_academy",
            "1\n2\n3\n4\n5\n6\n7": "1\n2\n3\n4\n5 6 7",
            "Сайт:\nhttps://example.com": "Сайт:\nhttps://example.com",
        }
        for raw, text in cases.items():
            item = self.parsed(raw)
            self.assertEqual(item.as_json(), {"kind": "text", "text": text, "href": None}, repr(raw))
            self.assertEqual(item.value, text)

    def test_length_limit(self):
        self.assertEqual(self.parsed("я" * 300).value, "я" * 300)
        err = self.refused("я" * 301)
        self.assertEqual((err.code, err.message),
                         ("suggest_too_long", "Не длиннее 300 символов — сейчас 301"))
        # «t.me/…» сохраняется на 8 символов длиннее — проверяется и сохранённое значение.
        self.assertEqual(self.refused("t.me/" + "a" * 295).message, "Не длиннее 300 символов — сейчас 308")
        # \r\n — один перевод строки.
        self.assertEqual(self.parsed("я" * 149 + "\r\n" + "я" * 150).kind, "text")

    def test_hidden_characters_are_refused(self):
        for raw in ("a\x00b", "a\x07b", "a\x1bb", "a\x7fb", "a\x85b", "Курс\u202eтекст", "a\u2066b",
                    "exam\u200bple.com", "a\u200db", "\ufeffacademy@esai.kg", "a\u00adb", "a\u2028b",
                    "a\u2029b", "a\ud800b", "https://example.com/\u202egnp.exe", "@esai\u200b"):
            err = self.refused(raw)
            self.assertEqual((err.code, err.message),
                             ("suggest_hidden", "Уберите невидимые символы: управляющие, нулевой ширины (в "
                                                "том числе внутри составных эмодзи) или смены направления "
                                                "текста"), repr(raw))
        # Склейка внутри эмодзи — тоже U+200D; одиночные эмодзи и вариант-селектор U+FE0F проходят.
        self.assertEqual(self.refused("Курсы \U0001F469\u200d\U0001F4BB").code, "suggest_hidden")
        self.assertEqual(self.parsed("Курсы \U0001F600 \u2764\ufe0f").kind, "text")

    def test_dangerous_schemes_are_refused_not_kept_as_text(self):
        for raw, scheme in (("javascript:alert(1)", "javascript"), ("JaVaScRiPt:alert(1)", "javascript"),
                            ("javascript: alert(document.cookie)", "javascript"),
                            ("java\nscript:alert(1)", "javascript"),
                            ("java \n script:alert(1)", "javascript"),
                            ("  javascript://%0aalert(1)", "javascript"),
                            ("vbscript:msgbox(1)", "vbscript"),
                            ("data:text/html;base64,PHNjcmlwdD4=", "data"),
                            ("DATA:,x", "data"),
                            ("file:///etc/passwd", "file"), ("FILE:C:/Users/x.html", "file"),
                            ("fi\nle:///etc/passwd", "file"), ("fi \n le:x", "file")):
            err = self.refused(raw)
            self.assertEqual((err.code, err.message),
                             ("suggest_danger", f"Ссылки «{scheme}:» на сайт не ставим — нужна ссылка "
                                                "https://…, e-mail, @имя или обычный текст"), repr(raw))
        self.assertIsNone(links.safe_suggest("javascript:alert(1)"))

    def test_foreign_scheme_link_is_refused(self):
        # Одно слово вида <схема>://… — ссылка, которую кнопка у посетителя не откроет.
        for raw, scheme in (("tg://resolve?domain=esai", "tg"), ("ftp://files.example.com/x", "ftp"),
                            ("whatsapp://send?phone=996555", "whatsapp"), ("intent://x#Intent;end", "intent"),
                            ("Chrome://settings", "chrome"), ("ws://x.kg", "ws")):
            err = self.refused(raw)
            self.assertEqual((err.code, err.message),
                             ("suggest_scheme", f"Ссылки «{scheme}:» не подходят — нужна https:// или "
                                                "http://, e-mail или @имя в Telegram"), raw)

    def test_colon_without_double_slash_is_text(self):
        # Двоеточие без «//» — не ссылка, а текст (почта или телефон в нём на сайте — ссылкой или как есть).
        self.assert_kind({raw: raw for raw in (
            "Contact:a@b.kg", "Почта:a@b.kg", "tel:+996555123456", "https:example.com", "https:/example.com",
            "HTTPS:\\\\example.com", "localhost:3000/x", "sms:+996555", "about:blank",
            "ftp://x.example.com и текст", "tg://resolve?domain=esai — пишите")}, "text")

    def test_link_followed_by_words_is_text(self):
        # Ссылка, а за ней слова или строки, — текст: ссылку в нём сайт сделает ссылкой сам.
        cases = {
            "https://forms.gle/abc\nЗаполните анкету": "https://forms.gle/abc\nЗаполните анкету",
            "https://t.me/x — пишите сюда": "https://t.me/x — пишите сюда",
            "https://exa mple.com": "https://exa mple.com",
            "HTTPS://example.com/a   b": "HTTPS://example.com/a b",
            "http://t.me/a b": "http://t.me/a b",
            "https://u:p@example.com и текст": "https://u:p@example.com и текст",
        }
        for raw, text in cases.items():
            self.assertEqual(self.parsed(raw).as_json(),
                             {"kind": "text", "text": text, "href": None}, repr(raw))

    def test_login_and_password_are_refused(self):
        for raw in ("https://u:p@example.com", "https://user@example.com/x",
                    "https://example.com:443@evil.com/",
                    "https://example.com%2F@evil.com", "https://u:p@t.me/esai", "http://t.me@evil.com"):
            err = self.refused(raw)
            self.assertEqual((err.code, err.message),
                             ("suggest_userinfo", "В ссылке не должно быть логина и пароля "
                                                  "(user:pass@)"), raw)

    def test_unparseable_hosts_are_refused(self):
        for raw in ("https://", "https:///kurs", "https://[::1/", "https://exa%6dple.com/",
                    "https://example.com\\@evil.com", "https://straße.de/", "https://STRAẞE.de/",
                    "https://ας.gr/", "http://127.1/", "http://0x7f.1/", "http://2130706433/",
                    "http://010.0.0.1/", "https://example.123/", "https://example.com:99999/",
                    "https://example.com:0/", "https://[1.2.3.4]/", "https://[fe80::1%25eth0]/",
                    "http://[::1]-esai/", "http://a[::1]/", "http://[::1]x:80/",
                    "https://xn--zz.com/", "https://ex!ample.com/", "https://a..b.com/",
                    "https://" + "a" * 64 + ".com/",
                    # U+FE12 → U+3002 внутри метки, U+FE19 и U+1F100 Python (Unicode 3.2) пропускает как есть.
                    "https://exa\ufe12mple.com/", "https://exa\ufe19mple.com/",
                    "https://exa\U0001f100mple.com/",
                    # NFKC даёт точку из «не точки»: Python видит exa.mple.com, браузер ссылку не откроет.
                    "http://exa\u2024mple.com", "https://example\ufe52com/", "https://\u2488example.com/",
                    "https://example.com\u3002/",
                    # \u0411\u0440\u0430\u0443\u0437\u0435\u0440 (UTS46) \u0442\u0430\u043a\u043e\u0439 \u0445\u043e\u0441\u0442 \u043d\u0435 \u043e\u0442\u043a\u0440\u043e\u0435\u0442 \u0438\u043b\u0438 \u043f\u0440\u043e\u0447\u0442\u0451\u0442 \u0438\u043d\u0430\u0447\u0435, \u0447\u0435\u043c Python (Unicode 3.2).
                    "https://a\u0378b.com/", "https://a\ufe47b.com/", "https://0x7f.\U0001fbf1/"):
            err = self.refused(raw)
            self.assertEqual((err.code, err.message),
                             ("suggest_host", "Не разобрать адрес сайта в ссылке — проверьте её, например "
                                              "https://example.com/forma"), raw)

    def test_safe_read(self):
        self.assertIsNone(links.safe_suggest("javascript:alert(1)"))
        self.assertIsNone(links.safe_suggest(42))
        self.assertIsNone(links.safe_suggest("https://u:p@example.com"))
        self.assertEqual(links.safe_suggest("@esai").value, "https://t.me/esai")
        self.assertEqual(links.safe_suggest("academy@esai.kg").href, "mailto:academy@esai.kg")
        self.assertEqual(links.safe_suggest("Пишите нам").as_json(),
                         {"kind": "text", "text": "Пишите нам", "href": None})
