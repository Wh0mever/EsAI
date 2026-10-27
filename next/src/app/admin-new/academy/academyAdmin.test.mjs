// Админка, EsAI Академия: разбор ответов, форма курса, ссылки, обложка, порядок (academyAdmin.ts).
// Запуск (Node 22.6+):  node --experimental-strip-types --test src/app/admin-new/academy/academyAdmin.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  DEFAULT_LIMITS,
  EMPTY_FORM,
  ORDER_PATH,
  SETTINGS_PATH,
  SUGGEST_TEXT,
  URL_TEXT,
  aspectWarning,
  chars,
  checkCourseUrl,
  cleanText,
  courseChanges,
  coursePath,
  coverFileError,
  coverPath,
  coverSizeError,
  createBody,
  errorField,
  errorText,
  filterCounts,
  formFromCourse,
  lengthError,
  matchesFilter,
  missingForPublish,
  normalizeSuggestUrl,
  orderBy,
  parseCourse,
  parseList,
  parseOrder,
  parseSettings,
  placeLabel,
  placesChanged,
  publishHint,
  reorderIds,
  replaceCourse,
} from "./academyAdmin.ts";

// Строка в том виде, как её собирает core/academy/panel.py (CONTRACT_ACADEMY §2, row).
const courseRow = (over = {}) => ({
  id: 7,
  title: "AI-мультфильмы с нуля",
  teacher: "Айбек Садыков",
  description: "Практический курс.",
  url: "https://example.com/kurs",
  url_host: "example.com",
  cover: "/media/academy/covers/7-1a2b3c4d.jpg",
  cover_thumb: "/media/academy/covers/7-1a2b3c4d-480.jpg",
  cover_width: 1280,
  cover_height: 720,
  is_published: true,
  state: "live",
  missing: [],
  sort: 30,
  place: { page: 1, index: 3 },
  published_at: "2026-10-27T15:04:05+06:00",
  created_at: "2026-10-27T15:00:00+06:00",
  updated_at: "2026-10-27T15:04:05+06:00",
  ...over,
});

const course = (over = {}) => parseCourse(courseRow(over));

test("пути панели", () => {
  assert.equal(coursePath(7), "manage/academy/courses/7/");
  assert.equal(coverPath(7), "manage/academy/courses/7/cover/");
  assert.equal(ORDER_PATH, "manage/academy/courses/order/");
  assert.equal(SETTINGS_PATH, "manage/academy/settings/");
});

test("parseCourse: поля, состояние, место только у live", () => {
  const c = course();
  assert.equal(c.id, 7);
  assert.equal(c.urlHost, "example.com");
  assert.equal(c.coverThumb, "/media/academy/covers/7-1a2b3c4d-480.jpg");
  assert.equal(c.published, true);
  assert.equal(c.state, "live");
  assert.deepEqual(c.place, { page: 1, index: 3 });
  assert.equal(placeLabel(c.place), "стр. 1 · №3");

  const draft = course({ is_published: false, state: "draft", place: { page: 1, index: 1 }, cover: "", cover_thumb: "x" });
  assert.equal(draft.place, null);
  assert.equal(draft.cover, null);
  assert.equal(draft.coverThumb, null);
  assert.equal(placeLabel(draft.place), "");

  // Неизвестное состояние — по флагу и missing; missing — в порядке сервера, без чужих значений.
  const odd = course({ state: "weird", missing: ["url", "cover", "bogus"] });
  assert.equal(odd.state, "incomplete");
  assert.deepEqual(odd.missing, ["cover", "url"]);
  assert.equal(course({ state: "weird", is_published: false }).state, "draft");

  // «false» строкой — не публикация.
  assert.equal(course({ is_published: "true" }).published, false);

  for (const bad of [null, "x", [], { id: "7" }, { id: 0 }, { id: 1.5 }]) assert.equal(parseCourse(bad), null);
});

test("parseList / parseOrder / parseSettings: «чужие руки»", () => {
  assert.equal(parseList(null), null);
  assert.equal(parseList("<html>"), null);
  assert.equal(parseList({ detail: "x" }), null);
  const list = parseList({
    results: [courseRow({ id: 2 }), "мусор", courseRow({ id: 1 }), courseRow({ id: 2, title: "повтор" })],
    suggest_url: " https://t.me/esai ",
    limits: { title: 100, cover_min: [640, 360], max_courses: 0 },
    counts: { live: 2 },
  });
  assert.deepEqual(
    list.courses.map((c) => c.id),
    [2, 1],
  );
  assert.equal(list.suggestUrl, "https://t.me/esai");
  assert.equal(list.limits.titleMax, 100);
  assert.equal(list.limits.teacherMax, DEFAULT_LIMITS.teacherMax);
  assert.equal(list.limits.coverMinWidth, 640);
  assert.equal(list.limits.coverMinHeight, 360);
  assert.equal(list.limits.maxCourses, 500);

  assert.equal(parseList({ results: [] }).suggestUrl, "");
  assert.deepEqual(
    parseOrder({ results: [courseRow({ id: 3 }), courseRow({ id: 1 })] }).map((c) => c.id),
    [3, 1],
  );
  assert.equal(parseOrder({}), null);
  assert.equal(parseSettings({ suggest_url: "https://t.me/x" }), "https://t.me/x");
  assert.equal(parseSettings({ suggest_url: "" }), "");
  assert.equal(parseSettings({}), null);
});

test("errorText / errorField: detail сервера, обрыв, 413 и 429 без тела", () => {
  assert.equal(errorText({ status: 0 }, "x"), "Нет связи с сервером. Проверьте интернет и повторите.");
  assert.equal(
    errorText({ status: 400, data: { detail: "Ссылка должна начинаться с https:// или http://", code: "url_scheme", field: "url" } }, "x"),
    "Ссылка должна начинаться с https:// или http://",
  );
  assert.equal(
    errorText({ status: 413, data: { detail: "Обложка больше 15 МБ — уменьшите её" } }, "x"),
    "Обложка больше 15 МБ — уменьшите её",
  );
  assert.match(errorText({ status: 413, data: "<html>413</html>" }, "x"), /больше, чем пропускает сервер/);
  assert.match(errorText({ status: 429, data: null }, "x"), /Подождите минуту/);
  assert.equal(errorText({ status: 500, data: null }, "Не удалось"), "Не удалось (HTTP 500)");
  assert.equal(errorField({ data: { field: "url" } }), "url");
  assert.equal(errorField({ data: { detail: "x" } }), null);
  assert.equal(errorField({ data: null }), null);
});

test("cleanText и счётчики: как чистит сервер", () => {
  assert.equal(cleanText("  Курс \n\n по   AI\t "), "Курс по AI");
  assert.equal(cleanText("A\u202eB\u200bC\u0007D\ufeff"), "ABCD");
  assert.equal(chars("  ab  c ", 120), "4/120");
});

test("lengthError: тот же текст, что у сервера (too_long)", () => {
  const limits = DEFAULT_LIMITS;
  assert.equal(lengthError({ ...EMPTY_FORM, title: "x".repeat(120) }, limits), null);
  assert.deepEqual(lengthError({ ...EMPTY_FORM, title: "x".repeat(121) }, limits), {
    field: "title",
    text: "Название длиннее 120 символов",
  });
  assert.equal(lengthError({ ...EMPTY_FORM, teacher: "я".repeat(81) }, limits).text, "Преподаватель длиннее 80 символов");
  assert.equal(lengthError({ ...EMPTY_FORM, description: "д ".repeat(201) }, limits).text, "Описание длиннее 400 символов");
  // Пробелы схлопываются до проверки длины.
  assert.equal(lengthError({ ...EMPTY_FORM, title: `${"x".repeat(60)}          ${"x".repeat(59)}` }, limits), null);
});

test("createBody / courseChanges: почищенные поля, в PATCH — только изменённые", () => {
  assert.deepEqual(createBody({ title: " Курс  A ", teacher: "", description: "x\ny", url: " example.com " }), {
    title: "Курс A",
    teacher: "",
    description: "x y",
    url: "example.com",
  });
  const c = course();
  assert.deepEqual(courseChanges(c, formFromCourse(c)), {});
  // Те же слова с лишними пробелами — не правка: сервер ответил бы «Нечего менять».
  assert.deepEqual(courseChanges(c, { ...formFromCourse(c), title: "  AI-мультфильмы   с нуля " }), {});
  assert.deepEqual(courseChanges(c, { ...formFromCourse(c), title: "  AI-сериалы   с нуля " }), {
    title: "AI-сериалы с нуля",
  });
  assert.deepEqual(courseChanges(c, { ...formFromCourse(c), description: "", url: "https://example.com/new" }), {
    description: "",
    url: "https://example.com/new",
  });
});

test("missingForPublish и publishHint: порядок сервера, ссылка — только на пустоту", () => {
  assert.deepEqual(missingForPublish(EMPTY_FORM, false), ["cover", "title", "teacher", "description", "url"]);
  assert.deepEqual(missingForPublish({ title: "A", teacher: "B", description: "C", url: "x" }, true), []);
  assert.deepEqual(missingForPublish({ title: " ", teacher: "B", description: "C", url: "" }, true), ["title", "url"]);
  assert.equal(
    publishHint(["url", "cover", "teacher"]),
    "Чтобы опубликовать, добавьте: обложку, имя преподавателя, ссылку на курс",
  );
  assert.equal(publishHint([]), "");
});

test("checkCourseUrl: те же случаи, что в тестах сервера", () => {
  const ok = (raw, url) => {
    const r = checkCourseUrl(raw);
    assert.equal(r.ok, true, raw);
    assert.equal(r.url, url, raw);
  };
  const bad = (raw, error) => {
    const r = checkCourseUrl(raw);
    assert.equal(r.ok, false, raw);
    assert.equal(r.error, error, raw);
  };
  ok("", "");
  ok("https://example.com/kurs", "https://example.com/kurs");
  ok("HTTPS://Example.com/Kurs?utm=1", "https://Example.com/Kurs?utm=1");
  ok("example.com/kurs", "https://example.com/kurs");
  ok("www.example.com", "https://www.example.com");
  ok("https://курсы.рф/x", "https://курсы.рф/x");
  assert.equal(checkCourseUrl("https://курсы.рф/x").host, "xn--j1amdg6b.xn--p1ai");
  ok("https://example.com:8443/x", "https://example.com:8443/x");

  bad("javascript:alert(1)", URL_TEXT.scheme);
  bad("data:text/html,x", URL_TEXT.scheme);
  bad("mailto:a@b.com", URL_TEXT.scheme);
  bad("tg://resolve?domain=x", URL_TEXT.scheme);
  bad("ftp://x.y", URL_TEXT.scheme);
  bad("курс", URL_TEXT.scheme);
  bad("https://u:p@x.com", URL_TEXT.userinfo);
  bad("https://x.com@evil.com/", URL_TEXT.userinfo);
  bad("https://localhost/", URL_TEXT.local);
  bad("https://intranet/", URL_TEXT.local);
  bad("http://10.0.0.1/", URL_TEXT.local);
  bad("http://127.1/", URL_TEXT.local);
  bad("http://0x7f.1/", URL_TEXT.local);
  bad("http://2130706433/", URL_TEXT.local);
  bad("http://[::1]/", URL_TEXT.local);
  bad("https://site.local/", URL_TEXT.local);
  bad("https://a.example/", URL_TEXT.local);
  bad("http://8.8.8.8/", URL_TEXT.invalid);
  bad("https://exa mple.com", URL_TEXT.invalid);
  bad("https://example.com\\@evil.com", URL_TEXT.invalid);
  bad("https://exa\u202emple.com", URL_TEXT.invalid);
  bad("https://ex_ample.com", URL_TEXT.invalid);
  bad("https://example.c0m", URL_TEXT.invalid);
  bad(`https://example.com/${"a".repeat(1000)}`, "Ссылка длиннее 1000 символов");
  ok(`https://example.com/${"a".repeat(1000 - "https://example.com/".length)}`, `https://example.com/${"a".repeat(980)}`);
});

test("checkCourseUrl: ß/ẞ/ς в хосте — отказ, как на сервере (у Python и браузера разные хосты)", () => {
  for (const raw of ["https://straße.de/kurs", "https://STRAẞE.de/", "straße.de", "https://ας.gr/", "https://kurs.straße.de/"]) {
    const r = checkCourseUrl(raw);
    assert.equal(r.ok, false, raw);
    assert.equal(r.error, URL_TEXT.invalid, raw);
  }
  // В пути и запросе — можно; заглавную сигму оба пишут как σ.
  assert.equal(checkCourseUrl("https://example.com/straße?q=ς").ok, true);
  assert.equal(checkCourseUrl("https://ΑΣ.gr/").host, "xn--mxa0b.gr");
  assert.equal(normalizeSuggestUrl("https://straße.de/").ok, false);
});

test("normalizeSuggestUrl: @имя, t.me, https — как сохранит сервер", () => {
  const url = (raw) => {
    const r = normalizeSuggestUrl(raw);
    return r.ok ? r.url : r.error;
  };
  assert.equal(url(""), "");
  assert.equal(url("@my_channel"), "https://t.me/my_channel");
  assert.equal(url("my_channel"), "https://t.me/my_channel");
  assert.equal(url("t.me/esai_academy"), "https://t.me/esai_academy");
  assert.equal(url("http://t.me/x_bot?start=academy"), "https://t.me/x_bot?start=academy");
  assert.equal(url("https://www.telegram.me/+AbC-12"), "https://t.me/+AbC-12");
  assert.equal(url("https://forms.example.com/academy"), "https://forms.example.com/academy");
  assert.equal(url("@abc"), SUGGEST_TEXT);
  assert.equal(url("http://example.com/form"), SUGGEST_TEXT);
  assert.equal(url("t.me/bad path"), SUGGEST_TEXT);
  assert.equal(url("javascript:alert(1)"), SUGGEST_TEXT);
  assert.equal(url(`https://example.com/${"a".repeat(300)}`), "Ссылка для кнопки длиннее 300 символов");
});

test("обложка: тип и размер файла, минимум, предупреждение о пропорциях", () => {
  const limits = DEFAULT_LIMITS;
  assert.equal(coverFileError({ name: "a.jpg", size: 1000, type: "image/jpeg" }, limits), null);
  assert.equal(coverFileError({ name: "IMG_1.HEIC", size: 1000, type: "" }, limits), null);
  assert.equal(coverFileError({ name: "a.svg", size: 1000, type: "image/svg+xml" }, limits), "Обложка — картинка JPG, PNG, WebP или HEIC");
  assert.equal(coverFileError({ name: "a.mp4", size: 1000, type: "video/mp4" }, limits), "Обложка — картинка JPG, PNG, WebP или HEIC");
  assert.equal(
    coverFileError({ name: "a.png", size: 16 * 1024 * 1024, type: "image/png" }, limits),
    "Обложка больше 15 МБ — уменьшите её",
  );

  assert.equal(coverSizeError(0, 0, limits), null);
  assert.equal(coverSizeError(480, 270, limits), null);
  assert.equal(
    coverSizeError(300, 200, limits),
    "Обложка слишком маленькая: нужно не меньше 480×270, лучше 1280×720 (16:9)",
  );

  assert.equal(aspectWarning(1280, 720), null);
  assert.equal(aspectWarning(1920, 1080), null);
  assert.equal(aspectWarning(0, 0), null);
  assert.match(aspectWarning(1280, 960), /не 16:9/);
  assert.match(aspectWarning(720, 1280), /не 16:9/);
  assert.match(aspectWarning(960, 540), /меньше 1280×720/);
});

test("фильтры и счётчики: «Скрытые» — и снятые, и недозаполненные", () => {
  const list = [
    course({ id: 1 }),
    course({ id: 2, is_published: false, state: "draft", missing: ["cover"] }),
    course({ id: 3, is_published: false, state: "hidden" }),
    course({ id: 4, state: "incomplete", missing: ["url"] }),
  ];
  assert.deepEqual(filterCounts(list), { all: 4, live: 1, draft: 1, hidden: 2 });
  assert.deepEqual(
    list.filter((c) => matchesFilter(c, "hidden")).map((c) => c.id),
    [3, 4],
  );
});

test("порядок: reorderIds, orderBy, replaceCourse, placesChanged", () => {
  assert.deepEqual(reorderIds([1, 2, 3, 4], 0, 2), [2, 3, 1, 4]);
  assert.deepEqual(reorderIds([1, 2, 3, 4], 3, 0), [4, 1, 2, 3]);
  assert.deepEqual(reorderIds([1, 2, 3], 1, 99), [1, 3, 2]);
  assert.deepEqual(reorderIds([1, 2, 3], 1, -5), [2, 1, 3]);
  assert.deepEqual(reorderIds([1, 2, 3], 7, 0), [1, 2, 3]);

  const list = [course({ id: 1 }), course({ id: 2 }), course({ id: 3 })];
  assert.deepEqual(
    orderBy(list, [3, 1, 2]).map((c) => c.id),
    [3, 1, 2],
  );
  // Список id не совпал — порядок не трогаем.
  assert.deepEqual(
    orderBy(list, [3, 1]).map((c) => c.id),
    [1, 2, 3],
  );

  const renamed = course({ id: 2, title: "Новое" });
  assert.equal(replaceCourse(list, renamed)[1].title, "Новое");
  assert.deepEqual(
    replaceCourse(list, course({ id: 9 })).map((c) => c.id),
    [1, 2, 3, 9],
  );

  assert.equal(placesChanged(course(), course({ is_published: false, state: "hidden" })), true);
  assert.equal(placesChanged(course(), course({ title: "x" })), false);
});
