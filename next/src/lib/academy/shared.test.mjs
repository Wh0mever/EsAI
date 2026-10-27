// EsAI Академия, общее страницы /academy: разбор каталога, страницы по 9, ссылки, тексты (shared.ts).
// Запуск (Node 22.6+):  node --experimental-strip-types --test src/lib/academy/shared.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  ACADEMY_DESCRIPTION,
  ACADEMY_RU,
  ACADEMY_TITLE,
  EXTERNAL_REL,
  PAGE_SIZE,
  academyText,
  courseListJsonLd,
  emailFromMailto,
  emailLink,
  fill,
  nfkcAddsDots,
  pageCount,
  pageFromParam,
  pageFromSearch,
  pageHref,
  pagerItems,
  paginate,
  parseCatalog,
  parseSuggest,
  safeExternalUrl,
  safeLinkHref,
  safeMediaPath,
  suggestFromUrl,
  suggestParts,
  suggestText,
} from "./shared.ts";

// Строка публичного API в том виде, как её отдаёт core/academy (CONTRACT_ACADEMY §1).
const row = (over = {}) => ({
  id: 7,
  title: "AI-мультфильмы с нуля",
  teacher: "Айбек Садыков",
  description: "Практический курс: от идеи и героя до готового мультфильма.",
  url: "https://example.com/kurs",
  cover: "/media/academy/covers/7-1a2b3c4d.jpg",
  cover_thumb: "/media/academy/covers/7-1a2b3c4d-480.jpg",
  cover_width: 1280,
  cover_height: 720,
  ...over,
});

const catalogOf = (n) => parseCatalog({ count: n, page_size: 9, results: Array.from({ length: n }, (_, i) => row({ id: i + 1 })), suggest_url: "" });

test("метаданные — дословно ТЗ", () => {
  assert.equal(ACADEMY_TITLE, "EsAI Академия — курсы по созданию AI-контента");
  assert.equal(
    ACADEMY_DESCRIPTION,
    "Обучение созданию AI-видео, мультфильмов, сериалов и изображений с помощью нейросетей. Курсы от авторов и экспертов в EsAI Академии.",
  );
  assert.equal(EXTERNAL_REL, "noopener noreferrer");
  assert.equal(PAGE_SIZE, 9);
});

test("pageFromParam: номер — только целое ≥ 1 цифрами, иначе первая страница", () => {
  assert.equal(pageFromParam("2"), 2);
  assert.equal(pageFromParam(" 12 "), 12);
  assert.equal(pageFromParam("1000000"), 1000000);
  for (const junk of ["0", "-1", "abc", "1.5", "", "1e3", "0x10", "99999999", undefined, null]) {
    assert.equal(pageFromParam(junk), 1, String(junk));
  }
  assert.equal(pageFromParam(["2", "3"]), 1);
});

test("pageFromSearch: из строки адреса; повтор page — первая страница", () => {
  assert.equal(pageFromSearch("?page=3&utm_source=x"), 3);
  assert.equal(pageFromSearch("page=4"), 4);
  assert.equal(pageFromSearch(""), 1);
  assert.equal(pageFromSearch(null), 1);
  assert.equal(pageFromSearch("?page=2&page=3"), 1);
  assert.equal(pageFromSearch("?page=abc"), 1);
});

test("pageHref: первая — без ?page=1", () => {
  assert.equal(pageHref(1), "/academy");
  assert.equal(pageHref(3), "/academy?page=3");
});

test("pageCount и paginate: по 9, ≤ 9 — одна страница, за краем — outOfRange", () => {
  assert.equal(pageCount(0), 1);
  assert.equal(pageCount(9), 1);
  assert.equal(pageCount(10), 2);
  assert.equal(pageCount(500), 56);

  const nine = catalogOf(9).courses;
  const one = paginate(nine, 1);
  assert.equal(one.pages, 1);
  assert.equal(one.courses.length, 9);
  assert.equal(one.outOfRange, false);

  const twelve = catalogOf(12).courses;
  const second = paginate(twelve, 2);
  assert.deepEqual(
    second.courses.map((c) => c.id),
    [10, 11, 12],
  );
  assert.equal(second.firstPosition, 10);
  assert.equal(second.total, 12);

  const beyond = paginate(twelve, 3);
  assert.equal(beyond.outOfRange, true);
  assert.equal(beyond.courses.length, 0);

  // Пустой каталог: первая — пустое состояние, индексируется; дальше — «страницы нет»
  // (noindex без canonical), а не копия первой с canonical на себя.
  const empty = paginate([], 1);
  assert.equal(empty.outOfRange, false);
  assert.equal(empty.total, 0);
  const emptyFifth = paginate([], 5);
  assert.equal(emptyFifth.outOfRange, true);
  assert.equal(emptyFifth.total, 0);
  assert.equal(emptyFifth.courses.length, 0);
});

const shape = (items) => items.map((it) => (it.kind === "gap" ? "…" : it.current ? `[${it.page}]` : String(it.page))).join(" ");

test("pagerItems: до 7 — все; дальше первая, последняя, соседи и «…»", () => {
  assert.equal(shape(pagerItems(1, 1)), "[1]");
  assert.equal(shape(pagerItems(2, 2)), "1 [2]");
  assert.equal(shape(pagerItems(4, 7)), "1 2 3 [4] 5 6 7");
  assert.equal(shape(pagerItems(1, 12)), "[1] 2 3 4 5 … 12");
  assert.equal(shape(pagerItems(4, 12)), "1 2 3 [4] 5 … 12");
  assert.equal(shape(pagerItems(5, 12)), "1 … 4 [5] 6 … 12");
  assert.equal(shape(pagerItems(9, 12)), "1 … 8 9 10 11 12".replace("9", "[9]"));
  assert.equal(shape(pagerItems(12, 12)), "1 … 8 9 10 11 [12]");
  // За краем — ряд последних страниц без текущей.
  assert.equal(shape(pagerItems(40, 12)), "1 … 8 9 10 11 12");
  // Ключи «…» разные — React не ругается на повтор.
  const gaps = pagerItems(6, 12).filter((it) => it.kind === "gap").map((it) => it.key);
  assert.equal(new Set(gaps).size, gaps.length);
});

test("safeExternalUrl: только http(s) с хостом и без логина", () => {
  assert.equal(safeExternalUrl("https://example.com/kurs"), "https://example.com/kurs");
  assert.equal(safeExternalUrl("http://example.com"), "http://example.com/");
  assert.equal(safeExternalUrl("https://курсы.рф/x"), "https://xn--j1amdg6b.xn--p1ai/x");
  for (const bad of ["javascript:alert(1)", "data:text/html,x", "/academy", "//evil.com", "ftp://x.y", "https://u:p@x.com", "https://exa mple.com", "", null, 5]) {
    assert.equal(safeExternalUrl(bad), null, String(bad));
  }
});

test("safeMediaPath: свой путь или http(s); //чужой хост и data: — нет", () => {
  assert.equal(safeMediaPath("/media/academy/covers/7.jpg"), "/media/academy/covers/7.jpg");
  assert.equal(safeMediaPath("https://cdn.example.com/a.jpg"), "https://cdn.example.com/a.jpg");
  for (const bad of ["//evil.com/a.jpg", "data:image/png;base64,AA", "javascript:x", "", '/a" onerror="x', null]) {
    assert.equal(safeMediaPath(bad), null, String(bad));
  }
});

test("parseCatalog: «чужие руки» — мусорные строки отбрасываются, порядок сервера сохраняется", () => {
  assert.equal(parseCatalog(null), null);
  assert.equal(parseCatalog("<html>"), null);
  assert.equal(parseCatalog({ detail: "throttled" }), null);

  const data = parseCatalog({
    count: 7,
    page_size: 9,
    results: [
      row({ id: 3 }),
      row({ id: 1, title: "Второй" }),
      row({ id: 0 }),
      row({ id: "5" }),
      row({ id: 6, title: "  " }),
      row({ id: 8, url: "javascript:alert(1)" }),
      row({ id: 9, url: "" }),
      row({ id: 3, title: "Повтор id" }),
      "мусор",
      row({ id: 10, cover: "", cover_thumb: "", cover_width: 0, cover_height: 0, teacher: 5 }),
    ],
    suggest_url: "https://t.me/esai_academy",
  });
  assert.deepEqual(
    data.courses.map((c) => c.id),
    [3, 1, 10],
  );
  assert.equal(data.courses[0].title, "AI-мультфильмы с нуля");
  assert.equal(data.courses[0].cover, "/media/academy/covers/7-1a2b3c4d.jpg");
  assert.equal(data.courses[0].coverThumb, "/media/academy/covers/7-1a2b3c4d-480.jpg");
  assert.equal(data.courses[0].coverWidth, 1280);
  assert.equal(data.courses[2].cover, null);
  assert.equal(data.courses[2].coverThumb, null);
  assert.equal(data.courses[2].coverWidth, null);
  assert.equal(data.courses[2].teacher, "");
  assert.deepEqual(data.suggestUrl, { kind: "url", text: "https://t.me/esai_academy", href: "https://t.me/esai_academy" });
  assert.equal(data.pageSize, 9);
});

test("parseCatalog: старый ответ (только suggest_url) — ссылка или mailto:, прочее — ничего", () => {
  assert.equal(parseCatalog({ results: [], suggest_url: "" }).suggestUrl, null);
  assert.equal(parseCatalog({ results: [] }).suggestUrl, null);
  for (const bad of ["javascript:alert(1)", "data:text/html,x", "tg://resolve?domain=x", "Пишите нам", "https://esai.kg@evil.com", 5]) {
    assert.equal(parseCatalog({ results: [], suggest_url: bad }).suggestUrl, null, String(bad));
  }
  assert.deepEqual(parseCatalog({ results: [], suggest_url: "http://forms.example.com/a" }).suggestUrl, {
    kind: "url",
    text: "http://forms.example.com/a",
    href: "http://forms.example.com/a",
  });
  // Новый сервер у письма кладёт в suggest_url его href — страница без suggest всё равно поймёт.
  assert.deepEqual(parseCatalog({ results: [], suggest_url: "mailto:academy@esai.kg" }).suggestUrl, {
    kind: "email",
    text: "academy@esai.kg",
    href: "mailto:academy@esai.kg",
  });
});

test("parseCatalog: новый ответ — решает suggest, suggest_url только при его отсутствии", () => {
  const url = { kind: "url", text: "https://t.me/esai_academy", href: "https://t.me/esai_academy" };
  assert.deepEqual(parseCatalog({ results: [], suggest_url: url.href, suggest: url }).suggestUrl, url);
  const email = { kind: "email", text: "academy@esai.kg", href: "mailto:academy@esai.kg" };
  assert.deepEqual(parseCatalog({ results: [], suggest_url: email.href, suggest: email }).suggestUrl, email);
  const text = { kind: "text", text: "Пишите на academy@esai.kg\nили в Telegram", href: null };
  assert.deepEqual(parseCatalog({ results: [], suggest_url: "", suggest: text }).suggestUrl, text);
  assert.equal(parseCatalog({ results: [], suggest_url: "", suggest: null }).suggestUrl, null);
  // Сервер сказал «ничего» — старое поле не воскрешает кнопку (CONTRACT_ACADEMY §1).
  assert.equal(parseCatalog({ results: [], suggest_url: url.href, suggest: null }).suggestUrl, null);
  // Неизвестный вид или опасная ссылка — не рисуем ничего.
  assert.equal(parseCatalog({ results: [], suggest_url: "", suggest: { kind: "phone", text: "+996", href: null } }).suggestUrl, null);
  assert.equal(
    parseCatalog({ results: [], suggest_url: url.href, suggest: { kind: "url", text: "x", href: "javascript:alert(1)" } }).suggestUrl,
    null,
  );
});

test("parseSuggest: href бывает только http(s) или mailto:, письмо собираем сами из адреса", () => {
  assert.equal(parseSuggest(null), null);
  assert.equal(parseSuggest("https://x.kg"), null);
  for (const href of ["javascript:alert(1)", "data:text/html,x", "//evil.com", "https://u@evil.com/", "https://127.1/", ""]) {
    assert.equal(parseSuggest({ kind: "url", text: "x", href }), null, href);
  }
  // Любая ссылка: localhost и IP владелец разрешил.
  assert.equal(parseSuggest({ kind: "url", text: "http://localhost:8000/x", href: "http://localhost:8000/x" }).href, "http://localhost:8000/x");
  assert.equal(parseSuggest({ kind: "url", text: "", href: "https://192.168.0.1/f" }).text, "https://192.168.0.1/f");
  // Сервер прислал javascript: в href письма — берём только адрес.
  assert.deepEqual(parseSuggest({ kind: "email", text: "a.b+c@esai.kg", href: "javascript:alert(1)" }), {
    kind: "email",
    text: "a.b+c@esai.kg",
    href: "mailto:a.b+c@esai.kg",
  });
  assert.deepEqual(parseSuggest({ kind: "email", text: "", href: "mailto:info@xn--e1afmkfd.xn--p1ai?subject=x" }), {
    kind: "email",
    text: "info@xn--e1afmkfd.xn--p1ai",
    href: "mailto:info@xn--e1afmkfd.xn--p1ai",
  });
  assert.equal(parseSuggest({ kind: "email", text: "не адрес", href: "mailto:" }), null);
  assert.equal(parseSuggest({ kind: "text", text: " \n ", href: null }), null);
  assert.equal(parseSuggest({ kind: "text", text: 5, href: null }), null);
  // Правка мимо панели: невидимые знаки и лишние строки — прочь.
  assert.equal(parseSuggest({ kind: "text", text: "a\u202eb\n\n\nc", href: "https://x.kg" }).text, "ab\nc");
  assert.equal(parseSuggest({ kind: "text", text: "a", href: "https://x.kg" }).href, null);
  assert.equal(suggestFromUrl("mailto:bad"), null);
});

test("emailLink: адрес как на сервере; кириллический домен — в punycode, имя — %-кодом", () => {
  assert.deepEqual(emailLink(" academy@esai.kg "), { address: "academy@esai.kg", href: "mailto:academy@esai.kg" });
  assert.deepEqual(emailLink("info@пример.рф"), { address: "info@пример.рф", href: "mailto:info@xn--e1afmkfd.xn--p1ai" });
  assert.deepEqual(emailLink("почта@esai.kg"), {
    address: "почта@esai.kg",
    href: "mailto:%D0%BF%D0%BE%D1%87%D1%82%D0%B0@esai.kg",
  });
  assert.equal(emailLink("a_b-c.d+e@sub.esai.kg").href, "mailto:a_b-c.d+e@sub.esai.kg");
  for (const bad of [
    "academy@esai",
    "a@b@esai.kg",
    "@esai.kg",
    "a..b@esai.kg",
    ".a@esai.kg",
    "a b@esai.kg",
    "a@esai.kg.",
    "a@-esai.kg",
    "a@esai.k",
    "a@esai.123",
    "a@1.2.3.4",
    "a?subject=x@esai.kg",
    "o'brien@esai.kg",
    "a@straße.de",
    "a\u200b@esai.kg",
    `${"a".repeat(65)}@esai.kg`,
    "",
    null,
  ]) {
    assert.equal(emailLink(bad), null, String(bad));
  }
  assert.equal(emailFromMailto("MAILTO:academy@esai.kg?subject=Курс&cc=x@y.kg").href, "mailto:academy@esai.kg");
  assert.equal(emailFromMailto("mailto:a%40b@esai.kg"), null);
  assert.equal(emailFromMailto("mailto:%E0%A4%A"), null);
  assert.equal(emailFromMailto("academy@esai.kg"), null);
  // Пробел по краям после %-раскодирования сервер адресом не считает (links._email) — и здесь не адрес.
  assert.equal(emailFromMailto("mailto:%20a@b.kg"), null);
  assert.equal(emailFromMailto("mailto:a@b.kg%20"), null);
  // Точка из NFKC в домене (U+FE12, U+FE19, U+1F100, U+2488): сервер такой адрес не принимает.
  for (const bad of ["a@b\ufe12c.kg", "a@b\ufe19c.kg", "a@b\u{1f100}c.kg", "a@b\u2488c.kg", "a@esai\u2024kg"]) {
    assert.equal(emailLink(bad), null, bad);
  }
});

test("nfkcAddsDots: точка из «не точки» после NFKC — как links._nfkc_dots", () => {
  for (const odd of ["exa\u2024mple.com", "exa\ufe12mple.com", "exa\ufe19mple.com", "exa\u{1f100}mple.com", "\u2488example.com", "example\ufe52com"]) {
    assert.equal(nfkcAddsDots(odd), true, odd);
  }
  // Настоящие точки (и «\u3002», «\uff0e», «\uff61» — их браузер и сервер читают как точку) — нет.
  for (const fine of ["example.com", "курсы.рф", "example\u3002com", "example\uff0ecom", "example\uff61com", "ｅｘａｍｐｌｅ.com", ""]) {
    assert.equal(nfkcAddsDots(fine), false, fine);
  }
});

test("safeLinkHref: http(s) с тем хостом, что написан", () => {
  assert.equal(safeLinkHref("https://forms.example.com/a?b=1"), "https://forms.example.com/a?b=1");
  assert.equal(safeLinkHref("HTTP://Example.com"), "http://example.com/");
  assert.equal(safeLinkHref("http://localhost:3000/x"), "http://localhost:3000/x");
  assert.equal(safeLinkHref("https://8.8.8.8/"), "https://8.8.8.8/");
  assert.equal(safeLinkHref("http://[::1]:8080/"), "http://[::1]:8080/");
  assert.equal(safeLinkHref("https://курсы.рф/x"), "https://xn--j1amdg6b.xn--p1ai/x");
  assert.equal(safeLinkHref("https://my_site-.example.com/a@b"), "https://my_site-.example.com/a@b");
  for (const bad of [
    "https://a!b.com/",
    "https://a..b.com/",
    "https://x.kg:0/",
    "https://[1.2.3.4]/",
    "https://example.123/",
    "https://esai.kg@evil.com",
    "https://u:p@evil.com/",
    "https://@evil.com/",
    "https://127.1/",
    "https://0x7f.1/",
    "https://2130706433/",
    "https://010.0.0.1/",
    "https://ex%61mple.com/",
    "https://straße.de/",
    "https://exa mple.com",
    "https://evil.com\\@esai.kg",
    "https://esai.kg/\u202etxt.exe",
    "javascript:alert(1)",
    "//evil.com",
    "https:/evil.com",
    "ftp://x.kg",
    // Как сервер (links._open_link): пустой хост и «\u3002» в конце хоста — отказ.
    "https:///evil.com",
    "https:////evil.com/x",
    "https://example.com\u3002",
    "https://example.com\u3002/x",
    "https://example.com\uff0e:8080/",
    "http://exa\u2024mple.com/",
  ]) {
    assert.equal(safeLinkHref(bad), null, bad);
  }
  // Точка из NFKC (U+FE12, U+FE19, U+1F100, U+2488) — сервер не пускает, браузер не открывает.
  for (const bad of ["https://exa\ufe12mple.com/", "https://exa\ufe19mple.com/", "https://exa\u{1f100}mple.com/", "https://\u2488example.com/", "https://x.kg:\u2488/"]) {
    assert.equal(safeLinkHref(bad), null, bad);
  }
  // «\u3002» внутри хоста — обычная точка и у браузера, и у сервера.
  assert.equal(safeLinkHref("https://example\u3002com/"), "https://example.com/");
  assert.equal(safeLinkHref("https://example.com./"), "https://example.com./");
});

test("suggestText: строки как на сервере — без пустых, пробелы схлопнуты, не больше пяти", () => {
  assert.equal(suggestText("  Пишите\t нам  \r\n\r\n на почту  "), "Пишите нам\nна почту");
  assert.equal(suggestText("1\n2\n3\n4\n5\n6\n7"), "1\n2\n3\n4\n5 6 7");
  assert.equal(suggestText("a\u200bb\u2028c"), "abc");
  assert.equal(suggestText(null), "");
});

// Куски текста в виде строки: [ссылка](href), {почта}(href), остальное как есть.
const parts = (raw) =>
  suggestParts(raw)
    .map((p) => (p.kind === "text" ? p.text : p.kind === "url" ? `[${p.text}](${p.href})` : `{${p.text}}(${p.href})`))
    .join("");

test("suggestParts: e-mail и http(s) в тексте — ссылки, знаки после них — текст", () => {
  assert.equal(parts("Пишите на academy@esai.kg."), "Пишите на {academy@esai.kg}(mailto:academy@esai.kg).");
  assert.equal(
    parts("Анкета: https://forms.example.com/a?x=1, или (https://t.me/esai)!"),
    "Анкета: [https://forms.example.com/a?x=1](https://forms.example.com/a?x=1), или ([https://t.me/esai](https://t.me/esai))!",
  );
  assert.equal(parts("https://ru.wikipedia.org/wiki/A_(b)"), "[https://ru.wikipedia.org/wiki/A_(b)](https://ru.wikipedia.org/wiki/A_(b))");
  assert.equal(parts("почта: info@пример.рф\nтел. +996 555"), "почта: {info@пример.рф}(mailto:info@xn--e1afmkfd.xn--p1ai)\nтел. +996 555");
  assert.equal(parts("«https://x.kg/a»"), "«[https://x.kg/a](https://x.kg/a)»");
  // Не прошла проверку — остаётся текстом целиком, почта внутри неё ссылкой не становится.
  assert.equal(parts("см. https://esai.kg@evil.com/x"), "см. https://esai.kg@evil.com/x");
  assert.equal(parts("http://127.1 и a@b"), "http://127.1 и a@b");
  assert.equal(parts("javascript:alert(1) data:text/html,x www.esai.kg"), "javascript:alert(1) data:text/html,x www.esai.kg");
  assert.equal(parts("<b>жирный</b> & \"кавычки\""), "<b>жирный</b> & \"кавычки\"");
  assert.equal(parts(""), "");
  // href — только http(s) и mailto:.
  for (const p of suggestParts("a@b.kg https://x.kg mailto:c@d.kg tel:+996 javascript:x")) {
    if (p.kind !== "text") assert.match(p.href, /^(https?:\/\/|mailto:)/);
  }
  // Пустой хост и «\u3002» в конце — как у сервера: не ссылка, текст.
  assert.equal(parts("см. https:///evil.com"), "см. https:///evil.com");
});

test("suggestParts: текст, начатый со ссылки, и двоеточие без «//» (сервер хранит их текстом)", () => {
  assert.equal(
    parts("https://forms.gle/abc\nЗаполните анкету"),
    "[https://forms.gle/abc](https://forms.gle/abc)\nЗаполните анкету",
  );
  assert.equal(parts("https://t.me/x — пишите сюда"), "[https://t.me/x](https://t.me/x) — пишите сюда");
  assert.equal(parts("Contact:a@b.kg"), "Contact:{a@b.kg}(mailto:a@b.kg)");
  assert.equal(parts("mailto:a@b.kg пишите"), "mailto:{a@b.kg}(mailto:a@b.kg) пишите");
  assert.equal(parts("tel:+996555123456 и https:example.com"), "tel:+996555123456 и https:example.com");
  // Ссылка в тексте проходит те же правила, что кнопка: с логином или точкой из NFKC — остаётся текстом.
  assert.equal(parts("https://u:p@example.com и текст"), "https://u:p@example.com и текст");
  assert.equal(parts("https://exa\ufe12mple.com/form — анкета"), "https://exa\ufe12mple.com/form — анкета");
  const text = "https://forms.gle/abc\nЗаполните анкету";
  assert.deepEqual(parseCatalog({ results: [], suggest_url: "", suggest: { kind: "text", text, href: null } }).suggestUrl, {
    kind: "text",
    text,
    href: null,
  });
});

test("suggestParts: длинное (сервер столько не хранит) — текст без разбора, быстро", () => {
  const atLimit = `a@b.kg ${"x".repeat(993)}`;
  assert.equal(atLimit.length, 1000);
  assert.equal(suggestParts(atLimit)[0].kind, "email");
  for (const raw of [`a@b.kg ${"a".repeat(100_000)}`, `https://x.kg/${")".repeat(100_000)}`]) {
    const started = Date.now();
    assert.deepEqual(suggestParts(raw), [{ kind: "text", text: raw }]);
    assert.ok(Date.now() - started < 1000, "разбор не должен зависеть от длины квадратично");
  }
});

test("parseCatalog: page_size вне разумного — 9", () => {
  assert.equal(parseCatalog({ results: [] }).pageSize, 9);
  assert.equal(parseCatalog({ results: [], page_size: 0 }).pageSize, 9);
  assert.equal(parseCatalog({ results: [], page_size: 1000 }).pageSize, 9);
  assert.equal(parseCatalog({ results: [], page_size: 6 }).pageSize, 6);
});

test("courseListJsonLd: места сквозные, ссылки — на сайты авторов", () => {
  const view = paginate(catalogOf(12).courses, 2);
  const ld = courseListJsonLd(view);
  assert.equal(ld["@type"], "ItemList");
  assert.equal(ld.numberOfItems, 12);
  assert.deepEqual(
    ld.itemListElement.map((it) => it.position),
    [10, 11, 12],
  );
  assert.equal(ld.itemListElement[0].url, "https://example.com/kurs");
});

test("academyText и fill: перевод, запасной русский текст, подстановка", () => {
  assert.equal(academyText({ hero: { title: "EsAI Academy — learn" } }, "hero.title"), "EsAI Academy — learn");
  assert.equal(academyText({}, "hero.title"), ACADEMY_RU["hero.title"]);
  assert.equal(academyText({ hero: { title: "" } }, "hero.title"), ACADEMY_RU["hero.title"]);
  assert.equal(academyText(null, "card.cta"), "Перейти к курсу");
  assert.equal(fill("Страница {{page}}", { page: 3 }), "Страница 3");
  assert.equal(fill("{{page}}-бет {{x}}", { page: 2 }), "2-бет {{x}}");
});

// Плоский вид вложенного JSON: { a: { b: "x" } } → { "a.b": "x" }.
function flat(obj, prefix = "", out = {}) {
  for (const [key, value] of Object.entries(obj)) {
    const name = prefix ? `${prefix}.${key}` : key;
    if (value && typeof value === "object") flat(value, name, out);
    else out[name] = value;
  }
  return out;
}

const locale = (lang) => flat(JSON.parse(readFileSync(new URL(`../../locales/${lang}/academy.json`, import.meta.url), "utf8")));

test("academy.json: ru совпадает с текстами кода байт в байт, en/kg — те же ключи и подстановки", () => {
  const ru = locale("ru");
  assert.deepEqual(ru, { ...ACADEMY_RU });
  const marks = (s) => (s.match(/\{\{\w+\}\}/g) || []).sort().join(",");
  for (const lang of ["en", "kg"]) {
    const other = locale(lang);
    assert.deepEqual(Object.keys(other).sort(), Object.keys(ru).sort(), lang);
    for (const [key, value] of Object.entries(other)) {
      assert.equal(typeof value, "string", `${lang}:${key}`);
      assert.ok(value.trim(), `${lang}:${key} пустой`);
      assert.equal(marks(value), marks(ru[key]), `${lang}:${key} подстановки`);
    }
  }
});
