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
  fill,
  pageCount,
  pageFromParam,
  pageFromSearch,
  pageHref,
  pagerItems,
  paginate,
  parseCatalog,
  safeExternalUrl,
  safeMediaPath,
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
  assert.equal(data.suggestUrl, "https://t.me/esai_academy");
  assert.equal(data.pageSize, 9);
});

test("parseCatalog: ссылка кнопки — только http(s); page_size вне разумного — 9", () => {
  assert.equal(parseCatalog({ results: [], suggest_url: "" }).suggestUrl, null);
  assert.equal(parseCatalog({ results: [], suggest_url: "javascript:alert(1)" }).suggestUrl, null);
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
