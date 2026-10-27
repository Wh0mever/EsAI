// Админка, EsAI Академия: разбор ответов, форма курса, ссылки, обложка, порядок (academyAdmin.ts).
// Запуск (Node 22.6+):  node --experimental-strip-types --test src/app/admin-new/academy/academyAdmin.test.mjs
// academyAdmin.ts берёт правила адресов у страницы через алиас "@/…", которого Node не знает.
// Поэтому хук идёт первой строкой, а сам модуль подключается динамически, уже после него.
import "../../../lib/vstudio/nodeTsHooks.mjs";
import { test } from "node:test";
import assert from "node:assert/strict";

const {
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
  classifySuggest,
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
  suggestDanger,
  suggestPunycodeHost,
  suggestScheme,
  suggestTooLong,
} = await import("./academyAdmin.ts");

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
  // Сервер до F28 не присылал suggest: сохранённая ссылка и есть кнопка.
  assert.deepEqual(list.suggest, { kind: "url", text: "https://t.me/esai", href: "https://t.me/esai" });
  assert.equal(list.limits.titleMax, 100);
  assert.equal(list.limits.teacherMax, DEFAULT_LIMITS.teacherMax);
  assert.equal(list.limits.coverMinWidth, 640);
  assert.equal(list.limits.coverMinHeight, 360);
  assert.equal(list.limits.maxCourses, 500);

  assert.equal(parseList({ results: [] }).suggestUrl, "");
  assert.equal(parseList({ results: [] }).suggest, null);
  assert.deepEqual(
    parseOrder({ results: [courseRow({ id: 3 }), courseRow({ id: 1 })] }).map((c) => c.id),
    [3, 1],
  );
  assert.equal(parseOrder({}), null);
  assert.equal(parseSettings({}), null);
  assert.equal(parseSettings({ suggest: null }), null);
  assert.deepEqual(parseSettings({ suggest_url: "" }), { suggestUrl: "", suggest: null });
  assert.deepEqual(parseSettings({ suggest_url: "https://t.me/x" }), {
    suggestUrl: "https://t.me/x",
    suggest: { kind: "url", text: "https://t.me/x", href: "https://t.me/x" },
  });
  // Новый сервер: сохранённое значение как есть и что из него покажет сайт.
  const text = "Пишите на academy@esai.kg\nили в Telegram";
  assert.deepEqual(parseSettings({ suggest_url: text, suggest: { kind: "text", text, href: null } }), {
    suggestUrl: text,
    suggest: { kind: "text", text, href: null },
  });
  assert.deepEqual(
    parseSettings({
      suggest_url: "academy@esai.kg",
      suggest: { kind: "email", text: "academy@esai.kg", href: "mailto:academy@esai.kg" },
    }).suggest,
    { kind: "email", text: "academy@esai.kg", href: "mailto:academy@esai.kg" },
  );
  // Текст без suggest (сбой разбора) кнопкой не притворяется.
  assert.equal(parseSettings({ suggest_url: text }).suggest, null);
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
  assert.equal(classifySuggest("https://straße.de/").ok, false);
});

test("checkCourseUrl: точка из NFKC (U+2024, U+FE12, U+FE19, U+1F100, U+2488) — отказ, как на сервере", () => {
  // Python видит exa.mple.com, а браузер такую ссылку не открывает: карточка на сайте молча пропала бы.
  for (const raw of ["https://exa\u2024mple.com/", "https://exa\ufe12mple.com/", "https://exa\ufe19mple.com/", "https://exa\u{1f100}mple.com/", "https://\u2488example.com/", "exa\u2024mple.com/kurs"]) {
    const r = checkCourseUrl(raw);
    assert.equal(r.ok, false, raw);
    assert.equal(r.error, URL_TEXT.invalid, raw);
  }
});

// Итог подсказки одной строкой: «url → …», «email → …», «text → …», «— » (ничего) или текст отказа.
const kind = (raw, max) => {
  const r = classifySuggest(raw, max);
  if (!r.ok) return r.error;
  if (!r.suggest) return "—";
  return `${r.suggest.kind} → ${r.suggest.kind === "url" ? r.suggest.text : r.suggest.kind === "email" ? r.suggest.href : r.suggest.text}`;
};

test("classifySuggest: Telegram и ссылки — кнопка; любая ссылка, в том числе http, localhost и IP", () => {
  assert.equal(kind(""), "—");
  assert.equal(kind("  \n "), "—");
  assert.equal(kind("@my_channel"), "url → https://t.me/my_channel");
  assert.equal(kind("t.me/esai_academy"), "url → https://t.me/esai_academy");
  assert.equal(kind("http://t.me/x_bot?start=academy"), "url → https://t.me/x_bot?start=academy");
  assert.equal(kind("https://www.telegram.me/+AbC-12"), "url → https://t.me/+AbC-12");
  assert.equal(kind("https://forms.example.com/academy"), "url → https://forms.example.com/academy");
  assert.equal(kind("HTTP://Example.com/Form"), "url → http://Example.com/Form");
  assert.equal(kind("http://localhost:8000/x"), "url → http://localhost:8000/x");
  assert.equal(kind("https://192.168.0.10/form"), "url → https://192.168.0.10/form");
  assert.equal(kind("http://[::1]/"), "url → http://[::1]/");
  assert.equal(kind("https://курсы.рф/анкета"), "url → https://курсы.рф/анкета");
  assert.equal(kind("forms.example.com/a"), "url → https://forms.example.com/a");
  assert.equal(kind("www.esai.kg"), "url → https://www.esai.kg");
  // href для «Проверить ссылку» — разобранный браузером адрес.
  assert.equal(classifySuggest("https://курсы.рф/x").suggest.href, "https://xn--j1amdg6b.xn--p1ai/x");
});

test("classifySuggest: e-mail и mailto: — кнопка-письмо, параметры письма отброшены", () => {
  assert.equal(kind("academy@esai.kg"), "email → mailto:academy@esai.kg");
  assert.equal(kind("mailto:academy@esai.kg?subject=Курс"), "email → mailto:academy@esai.kg");
  assert.equal(kind("info@пример.рф"), "email → mailto:info@xn--e1afmkfd.xn--p1ai");
  assert.equal(classifySuggest("info@пример.рф").suggest.text, "info@пример.рф");
  // Не один адрес после mailto: — не отказ, а текст (как links._classify): годный адрес в нём сайт сделает ссылкой.
  for (const raw of ["mailto:", "mailto:foo", "mailto:a@b.kg,c@d.kg", "mailto:a%40b@c.kg", "mailto:a%0A@b.kg", "mailto:a@b.kg%00", "mailto:a%E2%80%AE@b.kg", "mailto:a@localhost", "mailto:javascript:alert(1)", "mailto:%20a@b.kg", "mailto://a@b.kg", "mailto:a@b\ufe12c.kg"]) {
    assert.equal(kind(raw), `text → ${raw}`, raw);
  }
  assert.equal(kind("mailto:academy@esai.kg и ещё"), "text → mailto:academy@esai.kg и ещё");
});

test("classifySuggest: всё прочее — текст без кнопки (строки, телефон, почта внутри фразы)", () => {
  assert.equal(kind("Пишите на academy@esai.kg"), "text → Пишите на academy@esai.kg");
  assert.equal(kind("Academy"), "text → Academy");
  assert.equal(kind("@abc"), "text → @abc");
  assert.equal(kind("+996 555 123 456"), "text → +996 555 123 456");
  assert.equal(kind("t.me/bad path"), "text → t.me/bad path");
  assert.equal(kind("3.14"), "text → 3.14");
  assert.equal(kind("a@b"), "text → a@b");
  assert.equal(kind("Пишите:\r\n\r\n  academy@esai.kg \t или\n1\n2\n3\n4"), "text → Пишите:\nacademy@esai.kg или\n1\n2\n3 4");
  assert.equal(kind("Note: текст"), "text → Note: текст");
});

test("classifySuggest: примеры CONTRACT_ACADEMY §5 и решения F28", () => {
  assert.equal(kind("@esai_academy"), "url → https://t.me/esai_academy");
  assert.equal(kind("t.me/esai_bot?start=academy"), "url → https://t.me/esai_bot?start=academy");
  assert.equal(kind("http://localhost:3000/form"), "url → http://localhost:3000/form");
  assert.equal(kind("Academy@Esai.kg"), "email → mailto:Academy@esai.kg");
  assert.equal(classifySuggest("Academy@Esai.kg").suggest.text, "Academy@Esai.kg");
  assert.equal(kind("почта@курсы.рф"), "email → mailto:%D0%BF%D0%BE%D1%87%D1%82%D0%B0@xn--j1amdg6b.xn--p1ai");
  assert.equal(kind("academy"), "text → academy");
  assert.equal(kind("Email: a@b.kg"), "text → Email: a@b.kg");
  assert.equal(kind("medium.com/@user"), "text → medium.com/@user");
  assert.equal(kind("name@site.kg."), "text → name@site.kg.");
  assert.equal(kind("10.0.0.1"), "text → 10.0.0.1");
  assert.equal(kind("example.com:8080/x"), "url → https://example.com:8080/x");
  // Telegram-хост с чужим путём — обычная ссылка, не отказ.
  assert.equal(kind("t.me/esai#x"), "url → https://t.me/esai#x");
  assert.equal(kind("localhost:3000/x"), "text → localhost:3000/x");
  assert.equal(kind("https://site.kg и текст"), "text → https://site.kg и текст");
  assert.equal(kind("https://u:p@site.kg"), URL_TEXT.userinfo);
  assert.equal(kind("https://site.kg:443@evil.com"), URL_TEXT.userinfo);
  assert.equal(kind("https://site.kg/@user"), "url → https://site.kg/@user");
  assert.equal(kind("https://[1.2.3.4]/"), SUGGEST_TEXT.host);
  assert.equal(kind("https://example.123/"), SUGGEST_TEXT.host);
  assert.equal(kind("https://x.kg:99999/"), SUGGEST_TEXT.host);
  assert.equal(kind("https://my_site-.example.com/"), "url → https://my_site-.example.com/");
});

test("suggestPunycodeHost: хост в punycode только там, где есть не-ASCII (подмена кириллицей видна)", () => {
  const host = (raw) => suggestPunycodeHost(classifySuggest(raw).suggest);
  // «е» — русская: посетитель видит только кнопку, сотрудник — хост в punycode.
  assert.equal(host("https://\u0435sai.kg/form"), "xn--sai-qdd.kg");
  assert.equal(host("academy@\u0435sai.kg"), "xn--sai-qdd.kg");
  assert.equal(host("курсы.рф/анкета"), "xn--j1amdg6b.xn--p1ai");
  assert.equal(host("https://esai.kg/form"), null);
  assert.equal(host("academy@esai.kg"), null);
  assert.equal(host("@esai_academy"), null);
  assert.equal(host("Пишите на academy@\u0435sai.kg"), null);
  assert.equal(suggestPunycodeHost(null), null);
});

test("parseList: сохранённое значение и вид блока — из списка курсов (сервер F28)", () => {
  const text = "Пишите на academy@esai.kg\nили в Telegram";
  const list = parseList({ results: [], suggest_url: text, suggest: { kind: "text", text, href: null } });
  assert.equal(list.suggestUrl, text);
  assert.deepEqual(list.suggest, { kind: "text", text, href: null });
  // suggest: null — на сайте ничего, даже если поле не пустое (значение перестало проходить проверку).
  assert.equal(parseList({ results: [], suggest_url: "https://t.me/x", suggest: null }).suggest, null);
});

test("classifySuggest: отказы — тексты сервера", () => {
  assert.equal(kind(`https://example.com/${"a".repeat(300)}`), suggestTooLong(300, 320));
  assert.equal(kind("я".repeat(301)), suggestTooLong(300, 301));
  // Длина в символах, как у сервера: эмодзи — один символ, а не два.
  assert.equal(kind("😀".repeat(300)), `text → ${"😀".repeat(300)}`);
  // t.me/… в 295 символов становится https://t.me/… в 303 — длиннее предела.
  assert.equal(kind(`t.me/${"a".repeat(290)}`, 300), suggestTooLong(300, 303));
  assert.equal(kind("Пишите\u200b нам"), SUGGEST_TEXT.hidden);
  assert.equal(kind("abc\u202etxt"), SUGGEST_TEXT.hidden);
  assert.equal(kind("a\u0007b"), SUGGEST_TEXT.hidden);
  assert.equal(kind("javascript:alert(1)"), suggestDanger("javascript"));
  assert.equal(kind("java\nscript:alert(1)"), suggestDanger("javascript"));
  // Пробелы у переносов сервер срезает, и текст склеивается в опасное начало — его вторая проверка.
  for (const glued of ["java \n script:alert(1)", "java\n script:alert(1)", "java \nscript:alert(1)", "javascript\n :alert(1)"]) {
    assert.equal(kind(glued), suggestDanger("javascript"), JSON.stringify(glued));
  }
  assert.equal(kind("vb \r\n script:msgbox(1)"), suggestDanger("vbscript"));
  // Склейка U+200D внутри эмодзи невидима — текст отказа говорит о ней прямо.
  assert.equal(kind("Курсы \u{1F469}\u200d\u{1F4BB}"), SUGGEST_TEXT.hidden);
  assert.match(SUGGEST_TEXT.hidden, /составных эмодзи/);
  assert.equal(kind("Курсы \u{1F600} \u2764\ufe0f"), "text → Курсы \u{1F600} \u2764\ufe0f");
  assert.equal(kind("DATA:text/html,x"), suggestDanger("data"));
  // file: — файл с компьютера посетителя; переносы строк, как у javascript:, не спасают.
  for (const raw of ["file:///etc/passwd", "FILE:C:/Users/x.html", "fi\nle:///etc/passwd", "fi \n le:x"]) {
    assert.equal(kind(raw), suggestDanger("file"), JSON.stringify(raw));
  }
  // Одно слово вида <схема>://… — кнопка с такой ссылкой у посетителя не откроется.
  for (const [raw, scheme] of [["tg://resolve?domain=x", "tg"], ["ftp://files.example.com/x", "ftp"], ["whatsapp://send?phone=996555", "whatsapp"], ["intent://x#Intent;end", "intent"], ["Chrome://settings", "chrome"], ["ws://x.kg", "ws"]]) {
    assert.equal(kind(raw), suggestScheme(scheme), raw);
  }
  assert.equal(kind("https://esai.kg@evil.com/"), URL_TEXT.userinfo);
  for (const bad of ["https://127.1/", "https://0x7f.1/", "http://010.0.0.1/", "https://ex%61mple.com", "https://a!b.com/", "https://x.kg\\y", "https://"]) {
    assert.equal(kind(bad), SUGGEST_TEXT.host, bad);
  }
  // Сервер отказывает и здесь (пустой хост, «\u3002» в конце, точка из U+2024) — подсказка тоже.
  for (const bad of ["https:///evil.com", "https://example.com\u3002", "https://example.com\u3002/x", "http://exa\u2024mple.com"]) {
    assert.equal(kind(bad), SUGGEST_TEXT.host, bad);
  }
  assert.equal(kind("exa\u2024mple.com"), "text → exa\u2024mple.com");
  assert.equal(kind("academy@esai\u2024kg"), "text → academy@esai\u2024kg");
});

test("classifySuggest: точка из NFKC (U+FE12, U+FE19, U+1F100) — как у сервера", () => {
  // Python делит имя на метки до NFKC и видит другой хост — сервер их не пускает: ссылка — отказ, остальное — текст.
  for (const bad of ["https://exa\ufe12mple.com/", "https://exa\ufe19mple.com/", "https://exa\u{1f100}mple.com/"]) {
    assert.equal(kind(bad), SUGGEST_TEXT.host, bad);
  }
  for (const raw of ["exa\ufe12mple.com", "exa\ufe19mple.com", "exa\u{1f100}mple.com", "a@b\ufe12c.kg", "a@b\ufe19c.kg", "a@b\u{1f100}c.kg", "a@b\u2488c.kg"]) {
    assert.equal(kind(raw), `text → ${raw}`, raw);
  }
});

test("classifySuggest: ссылка, а за ней слова или строки, — текст; двоеточие без «//» — тоже текст", () => {
  // Как links._classify: ссылку в таком тексте сайт сделает ссылкой сам, если она проходит правила.
  assert.equal(kind("https://forms.gle/abc\r\nЗаполните анкету"), "text → https://forms.gle/abc\nЗаполните анкету");
  assert.equal(kind("https://t.me/x — пишите сюда"), "text → https://t.me/x — пишите сюда");
  assert.equal(kind("https://exa mple.com"), "text → https://exa mple.com");
  assert.equal(kind("HTTPS://example.com/a   b"), "text → HTTPS://example.com/a b");
  assert.equal(kind("http://t.me/a b"), "text → http://t.me/a b");
  assert.equal(kind("https://u:p@example.com и текст"), "text → https://u:p@example.com и текст");
  for (const raw of ["Contact:a@b.kg", "Почта:a@b.kg", "tel:+996555123456", "https:example.com", "https:/example.com", "HTTPS:\\\\example.com", "localhost:3000/x", "sms:+996555", "about:blank", "ftp://x.example.com и текст", "tg://resolve?domain=esai — пишите"]) {
    assert.equal(kind(raw), `text → ${raw}`, raw);
  }
});

test("classifySuggest: адрес без схемы — кнопка, только если похож на сайт, а не на прозу", () => {
  // Как links._schemeless: домен верхнего уровня латиницей (2–24 буквы) или настоящий кириллический.
  for (const [raw, url] of [["esai.kg", "https://esai.kg"], ["ESAI.KG/Kurs", "https://ESAI.KG/Kurs"], ["www.example.com/path?a=1", "https://www.example.com/path?a=1"], ["курсы.рф", "https://курсы.рф"], ["КУРСЫ.РФ", "https://КУРСЫ.РФ"], ["курсы.kg", "https://курсы.kg"], ["мектеп.қаз", "https://мектеп.қаз"], ["магазин.онлайн/x", "https://магазин.онлайн/x"], ["t.me/esai#x", "https://t.me/esai#x"]]) {
    assert.equal(kind(raw), `url → ${url}`, raw);
  }
  // Кириллица с латиницей в одной метке — подмена букв; со схемой правила прежние.
  for (const raw of ["Скоро.Ждите", "Привет.Мир", "курсы.ру", "a.b", "e.g", "10.0.0.1", "127.0.0.1:8000/x", "сайт.kg1", `x.${"a".repeat(25)}`, "xn--j1amdg6b.xn--p1ai", "p\u0430ypal.com", "\u0435sai.kg/form", "esai.\u043ag", "example.com\u3002"]) {
    assert.equal(kind(raw), `text → ${raw}`, raw);
  }
  assert.equal(kind("https://\u0435sai.kg/form"), "url → https://\u0435sai.kg/form");
  assert.equal(kind("http://10.0.0.1"), "url → http://10.0.0.1");
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
