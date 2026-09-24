// Паритет переводов (scripts/i18n-parity.mjs) и живая проверка vstudio.json
// через настоящий i18next и хелперы студии (errors.ts, composerText, settingsText).
// Запуск (Node 22.6+):  node --experimental-strip-types --test scripts/i18n-parity.test.mjs
import "../src/lib/vstudio/nodeTsHooks.mjs";
import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import path from "node:path";
import i18next from "i18next";

const P = await import("./i18n-parity.mjs");
const E = await import("../src/lib/vstudio/errors.ts");
const C = await import("../src/components/vstudio/composer/composerText.ts");
const S = await import("../src/components/vstudio/settings/settingsText.ts");
const L = await import("../src/lib/vstudio/labels.ts");

const map = (o) => new Map(Object.entries(o));
const ts = createRequire(path.join(P.NEXT_ROOT, "package.json"))("typescript");

/* ------------------------------------------------------------------ */
/* Сверка языков                                                        */
/* ------------------------------------------------------------------ */

test("flatten: вложенность, массивы по индексам, ключ с точкой — ошибка", () => {
  const problems = [];
  const out = P.flatten({ a: { b: "x", c: ["y", { d: "z" }] }, "e.f": "w", g: {} }, "", new Map(), problems);
  assert.deepEqual([...out.keys()], ["a.b", "a.c.0", "a.c.1.d", "e.f"]);
  assert.equal(problems.length, 2);
  assert.match(problems.join("\n"), /с точкой внутри «e\.f»/);
  assert.match(problems.join("\n"), /пустая группа «g»/);
});

test("comparePair: нет ключа, лишний ключ, пустое значение, не строка", () => {
  const ref = map({ "a.x": "Раз", "a.y": "Два", "a.z": "Три" });
  const { errors } = P.comparePair(ref, map({ "a.x": "One", "a.y": "  ", "a.z": 3, "a.old": "Old" }), "en");
  assert.ok(errors.includes("en: пустое значение «a.y»"));
  assert.ok(errors.includes("en: «a.z» — не строка"));
  assert.ok(errors.includes("en: лишний ключ «a.old» (нет в ru)"));
  const missing = P.comparePair(ref, map({ "a.x": "One", "a.y": "Two" }), "kg").errors;
  assert.deepEqual(missing, ["kg: нет ключа «a.z»"]);
});

test("comparePair: подстановки {{x}} должны совпадать", () => {
  const ref = map({ run: "Создать · {{credits}} кр", fmt: "{{n, number}} с" });
  const { errors } = P.comparePair(ref, map({ run: "Create · {{credit}} cr", fmt: "{{n}} s" }), "en");
  assert.equal(errors.length, 1);
  assert.match(errors[0], /«run» подстановки \{\{credit\}\}, а в ru \{\{credits\}\}/);
});

test("comparePair: метки @Image N не переводятся, а слово Image без номера — не метка", () => {
  const ref = map({ wait: "Ждём @Image {{n}}…", pin: "как Image {{k}}", hint: "пишите @Image 1", ex: "@Image — выкл", price: "Картинка — {{credits}} кр" });
  const good = map({ wait: "Waiting for @Image {{n}}…", pin: "as Image {{k}}", hint: "write @Image 1", ex: "@Image — off", price: "Image — {{credits}} cr" });
  assert.deepEqual(P.comparePair(ref, good, "en").errors, []);
  const bad = map({ wait: "Waiting for @Photo {{n}}…", pin: "as Image {{k}}", hint: "write @Image 1", ex: "@Image — off", price: "Image — {{credits}} cr" });
  const { errors } = P.comparePair(ref, bad, "en");
  assert.equal(errors.length, 1);
  assert.match(errors[0], /«wait» метки Image/);
});

test("множественное число: ru — 4 формы, en — one/other, kg — все формы ru", () => {
  assert.deepEqual(P.pluralCategories("en"), ["one", "other"]);
  assert.deepEqual(P.pluralCategories("kg"), ["one", "few", "many", "other"]);
  assert.deepEqual([...P.pluralCategories("ru")].sort(), ["few", "many", "one", "other"]);
  const ref = map({
    "p.n_one": "{{count}} генерация",
    "p.n_few": "{{count}} генерации",
    "p.n_many": "{{count}} генераций",
    "p.n_other": "{{count}} генераций",
    // «cat_other» без «cat_one» — не множественное число, обычный ключ.
    "p.cat_other": "Другое",
  });
  const en = map({ "p.n_one": "{{count}} generation", "p.n_other": "{{count}} generations", "p.cat_other": "Other" });
  assert.deepEqual(P.comparePair(ref, en, "en").errors, []);
  const kg = P.comparePair(ref, en, "kg").errors;
  assert.deepEqual(kg, ["kg: нет формы «p.n_few»", "kg: нет формы «p.n_many»"]);
  const noCount = map({ "p.n_one": "generation", "p.n_other": "generations", "p.cat_other": "Other" });
  assert.match(P.comparePair(ref, noCount, "en").errors.join("\n"), /«p\.n_\*» подстановки —, а в ru \{\{count\}\}/);
});

test("checkReference: пустое значение и «текст и группа сразу»", () => {
  const errors = P.checkReference(map({ a: "x", "a.b": "y", c: "" }));
  assert.ok(errors.includes("ru: пустое значение «c»"));
  assert.ok(errors.some((e) => e.includes("«a» — и текст, и группа")));
});

/* ------------------------------------------------------------------ */
/* Сверка с кодом                                                       */
/* ------------------------------------------------------------------ */

const SAMPLE = `
export const DEMO_RU = { "demo.table": "Из таблицы", "demo.shared": "Общий" } as const;
export const CODES_RU: Record<string, string> = { boom: "Взрыв", quiet: "" };
export const LIST = [{ id: "one", title: "Первый" }, { id: "two", title: "Второй" }];
function View({ t, cond, code }) {
  t("demo.plain", { defaultValue: "Просто" });
  ct(t, cond ? "demo.yes" : "demo.no");
  tx("demo.local", "Локальный", { n: 1 });
  t("page.items", { count: 3, defaultValue: plural(3) });
  t("demo.ctx", { context: "frame", defaultValue: "Кадр" });
  t("other.key", { ns: "common", defaultValue: "Чужой" });
  t("vstudio:demo.prefixed", { defaultValue: "С префиксом" });
  t(\`errors.\${code}\`);
  t(\`mystery.\${code}\`);
  const map = { upload: "demo.loose" };
  document.querySelector("div.card");
  return { key: "demo.phrase", ru: "Фраза" };
}
`;
const SAMPLE_CONFIG = {
  tables: [
    { file: "src/demo.tsx", name: "DEMO_RU", prefix: "" },
    { file: "src/demo.tsx", name: "CODES_RU", prefix: "errors." },
  ],
  lists: [{ file: "src/demo.tsx", name: "LIST", id: "id", fields: { title: "demo.list.{id}" } }],
  dynamic: ["errors."],
};

test("extractFromSources: вызовы, ?:, локальный tx(key, ru), count, context, ns, таблицы, {key, ru}, шаблоны", () => {
  const ex = P.extractFromSources(ts, [{ file: "src/demo.tsx", text: SAMPLE }]);
  const byKey = Object.fromEntries(ex.calls.map((c) => [c.key, c]));
  assert.equal(byKey["demo.plain"].def, "Просто");
  assert.ok(byKey["demo.yes"] && byKey["demo.no"], "обе ветки ?: — ключи");
  assert.equal(byKey["demo.local"].def, "Локальный");
  assert.equal(byKey["page.items"].plural, true);
  assert.equal(byKey["demo.ctx"].context, "frame");
  assert.equal(byKey["other.key"].ns, "common");
  assert.deepEqual(ex.phrases.map((p) => [p.key, p.ru]), [["demo.phrase", "Фраза"]]);
  // Строка «a.b» не в функции перевода — не ключ, а лишь «похожая» (без падения).
  assert.deepEqual(ex.loose.map((l) => l.key), ["demo.loose", "div.card"]);
  assert.ok(!byKey["div.card"]);
  assert.deepEqual(ex.templates.map((t) => t.head), ["errors.", "mystery."]);
  assert.deepEqual(ex.tables.get("src/demo.tsx#CODES_RU"), [["boom", "Взрыв"], ["quiet", ""]]);
  assert.deepEqual(ex.lists.get("src/demo.tsx#LIST"), [{ id: "one", title: "Первый" }, { id: "two", title: "Второй" }]);
});

test("expectedFromCode + compareWithCode: пропуски, расхождение с defaultValue, формы, шаблоны", () => {
  const ex = P.extractFromSources(ts, [{ file: "src/demo.tsx", text: SAMPLE }]);
  const code = P.expectedFromCode(ex, SAMPLE_CONFIG, "vstudio");
  assert.ok(code.expected.has("demo.ctx_frame"), "context → ключ _frame");
  assert.ok(code.expected.has("demo.prefixed"), "префикс ns снят");
  assert.ok(!code.expected.has("other.key"), "чужой ns не наш");
  assert.ok(code.expected.has("errors.boom") && !code.expected.has("errors.quiet"), "пустой текст таблицы не ждём");
  assert.ok(code.expected.has("demo.list.two"));
  assert.deepEqual(code.uncovered.map((t) => t.head), ["mystery."]);

  const full = {
    "demo.table": "Из таблицы", "demo.shared": "Общий", "demo.plain": "Просто", "demo.yes": "Да", "demo.no": "Нет",
    "demo.local": "Локальный", "page.items_one": "{{count}} штука", "page.items_few": "{{count}} штуки",
    "page.items_many": "{{count}} штук", "page.items_other": "{{count}} штук", "demo.ctx_frame": "Кадр",
    "demo.prefixed": "С префиксом", "demo.phrase": "Фраза", "demo.list.one": "Первый", "demo.list.two": "Второй",
    "errors.boom": "Взрыв", "errors.backend_only": "Код бэкенда", "demo.loose": "Карта", "demo.stale": "Старое",
  };
  const ok = P.compareWithCode(map(full), code, { loose: ex.loose });
  assert.deepEqual(ok.errors, []);
  // Шаблон mystery.* не описан; demo.stale нигде не используется; errors.* — динамика, не «лишнее».
  assert.equal(ok.warnings.length, 2);
  assert.match(ok.warnings[0], /mystery\./);
  assert.match(ok.warnings[1], /\(1\): demo\.stale$/);

  const broken = { ...full, "demo.plain": "Устарело" };
  delete broken["demo.yes"];
  delete broken["page.items_few"];
  const res = P.compareWithCode(map(broken), code, { loose: ex.loose });
  assert.equal(res.errors.length, 3);
  assert.ok(res.errors.some((e) => e.startsWith("ru: нет ключа «demo.yes»")));
  assert.ok(res.errors.some((e) => e.startsWith("ru: нет формы «page.items_few»")));
  assert.ok(res.errors.some((e) => e.startsWith("ru: «demo.plain» = «Устарело», а в коде «Просто»")));
});

test("пропавшая из кода таблица — ошибка конфигурации, а не тихий пропуск", () => {
  const ex = P.extractFromSources(ts, [{ file: "src/demo.tsx", text: "export const X = 1;" }]);
  const code = P.expectedFromCode(ex, SAMPLE_CONFIG, "vstudio");
  assert.equal(code.errors.length, 3);
  assert.match(code.errors[0], /не найдена таблица DEMO_RU/);
});

/* ------------------------------------------------------------------ */
/* Настоящие файлы                                                      */
/* ------------------------------------------------------------------ */

test("vstudio.json: паритет ru/en/kg и сверка с кодом студии без ошибок", () => {
  const res = P.checkNamespace(P.NEXT_ROOT, "vstudio");
  assert.deepEqual(res.errors, []);
  assert.deepEqual(res.warnings, []);
});

test("home.json: паритет (nav.vstudio во всех языках)", () => {
  assert.deepEqual(P.checkNamespace(P.NEXT_ROOT, "home").errors, []);
  for (const lang of P.LANGS) assert.ok(P.loadLocale(P.NEXT_ROOT, lang, "home").keys.get("nav.vstudio"));
});

test("main: строгий namespace с ошибкой → код 1", () => {
  const lines = [];
  assert.equal(P.main(["vstudio", "home"], P.NEXT_ROOT, (l) => lines.push(l)), 0);
  assert.equal(P.main(["no_such_ns"], P.NEXT_ROOT, (l) => lines.push(l)), 1);
  assert.match(lines.join("\n"), /нет файла/);
});

/* ------------------------------------------------------------------ */
/* Живой i18next                                                        */
/* ------------------------------------------------------------------ */

const resources = {};
for (const lang of P.LANGS) {
  const file = P.localePath(P.NEXT_ROOT, lang, "vstudio");
  resources[lang] = { vstudio: JSON.parse((await import("node:fs")).readFileSync(file, "utf8")) };
}
// Та же конфигурация, что в src/i18n/i18n.ts (fallback ru, без экранирования).
const i18n = i18next.createInstance();
await i18n.init({
  lng: "ru",
  fallbackLng: "ru",
  supportedLngs: P.LANGS,
  ns: ["vstudio"],
  defaultNS: "vstudio",
  resources,
  interpolation: { escapeValue: false },
});
const tFor = (lang) => i18n.getFixedT(lang, "vstudio");

test("каждый ключ во всех языках находится и подставляет все {{x}}", () => {
  const ref = P.loadLocale(P.NEXT_ROOT, "ru", "vstudio").keys;
  for (const lang of P.LANGS) {
    const t = tFor(lang);
    const own = P.loadLocale(P.NEXT_ROOT, lang, "vstudio").keys;
    for (const [key, ru] of ref) {
      if (/_(one|few|many|other)$/.test(key)) continue;
      const params = Object.fromEntries([...P.placeholders(ru)].map((p) => [p, `<${p}>`]));
      const out = t(key, { ...params, defaultValue: "__MISSING__" });
      assert.notEqual(out, "__MISSING__", `${lang}: ${key}`);
      assert.ok(!out.includes("{{"), `${lang}: ${key} → ${out}`);
      assert.equal(out, String(own.get(key)).replace(/\{\{\s*(\w+)\s*\}\}/g, "<$1>"), `${lang}: ${key}`);
    }
  }
});

test("errorText: перевод по коду побеждает русский текст бэкенда", () => {
  const backend = { code: "prompt_empty", message: "Опишите, что должно происходить в кадре." };
  assert.equal(E.errorText(tFor("en"), backend), "Describe what should happen in the shot.");
  assert.equal(E.errorText(tFor("kg"), backend), "Кадрда эмне болушу керектигин жазыңыз.");
  assert.equal(E.errorText(tFor("ru"), backend), backend.message);
  // Параметры 409 лежат прямо в теле.
  const limit = { code: "too_many_open", message: "", data: { limit: 2, kind: "video" } };
  assert.equal(E.errorText(tFor("en"), limit), "You can run at most 2 at a time — wait until one generation finishes.");
  // Код, которого нет в таблицах фронта, но шлёт бэкенд.
  assert.equal(E.errorText(tFor("en"), { code: "take_not_ready", message: "Видео ещё не готово" }), "The video isn't ready yet — you can take a frame once the clip appears.");
  assert.equal(E.errorText(tFor("en"), { code: "canceled", message: "" }), "Canceled");
});

test("issueText: кадры — свой род в ru (context frame), подстановки и поля переведены", () => {
  const frame = { code: "ref_too_small", params: { asset: "a".repeat(32), slot: "first_frame", n: null, label: "first_frame", model: "Seedance 2.0", min: 300 }, message: "" };
  assert.equal(E.issueText(tFor("ru"), frame, "errors"), "@Первый кадр слишком маленький для Seedance 2.0: нужно от 300 px по короткой стороне.");
  assert.equal(E.issueText(tFor("en"), frame, "errors"), "@First frame is too small for Seedance 2.0: the short side must be at least 300 px.");
  assert.equal(E.issueText(tFor("kg"), frame, "errors"), "@Биринчи кадр Seedance 2.0 үчүн өтө кичинекей: кыска тарабы кеминде 300 px болушу керек.");
  const ref = { ...frame, params: { ...frame.params, slot: "reference", n: 2, label: "Image 2" } };
  assert.equal(E.issueText(tFor("ru"), ref, "errors"), "@Image 2 слишком маленькое для Seedance 2.0: нужно от 300 px по короткой стороне.");

  const param = { code: "invalid_param", params: { field: "duration", value: 7, allowed: [5, 10], model: "Veo 3.1" }, message: "" };
  assert.equal(E.issueText(tFor("en"), param, "errors"), "Veo 3.1 doesn't support duration = 7. Available: 5, 10.");
  assert.equal(E.issueText(tFor("kg"), param, "errors"), "Veo 3.1 узактык = 7 колдобойт. Жеткиликтүү: 5, 10.");

  const aspect = { code: "ref_bad_aspect", params: { asset: "b".repeat(32), slot: "reference", n: 1, label: "Image 1", model: "Seedance 2.0", lo: 0.4, hi: 2.5 }, message: "" };
  assert.equal(E.issueText(tFor("en"), aspect, "errors"), "@Image 1 is too elongated for Seedance 2.0: an aspect ratio from 2:5 to 5:2 will work.");

  const auto = { code: "aspect_in_text", params: { value: "21:9", current: "auto" }, message: "" };
  assert.equal(E.issueText(tFor("en"), auto, "warnings"), "The text says 21:9, but the settings say Auto. Apply 21:9?");
});

test("context image и причины condense_failed: свои ключи есть, без них — общий текст", () => {
  // Ключи ждут проводки context в errors.ts и ленте (см. отчёт FE-6); i18next уже умеет.
  for (const lang of P.LANGS) {
    const t = tFor(lang);
    for (const code of ["provider_error", "bad_params", "save_failed"]) {
      const withCtx = t(`errors.${code}`, { context: "image" });
      assert.notEqual(withCtx, t(`errors.${code}`), `${lang}: ${code}_image`);
    }
    assert.equal(t("errors.image_real_person", { context: "image" }), t("errors.image_real_person"), "нет _image — базовый текст");
    assert.equal(t("errors.condense_failed", { context: "provider" }), t("errors.condense_failed_provider"));
    assert.equal(t("errors.condense_failed", { context: "placeholders" }), t("errors.condense_failed"));
  }
  assert.equal(tFor("ru")("errors.provider_error", { context: "image" }), "Не удалось сгенерировать изображение. Кредиты не списаны.");
});

test("page.restored: формы числа в ru, en и kg", () => {
  const ru = tFor("ru");
  assert.equal(ru("page.restored", { count: 1 }), "Восстановили 1 генерацию");
  assert.equal(ru("page.restored", { count: 3 }), "Восстановили 3 генерации");
  assert.equal(ru("page.restored", { count: 5 }), "Восстановили 5 генераций");
  assert.equal(ru("page.restored", { count: 21 }), "Восстановили 21 генерацию");
  assert.equal(tFor("en")("page.restored", { count: 1 }), "Restored 1 generation");
  assert.equal(tFor("en")("page.restored", { count: 4 }), "Restored 4 generations");
  for (const n of [1, 2, 5]) assert.equal(tFor("kg")("page.restored", { count: n }), `${n} генерация калыбына келтирилди`);
});

test("хелперы композера, панели и меток отдают перевод", () => {
  assert.equal(C.ct(tFor("en"), "composer.run", { credits: 164 }), "Create · 164 cr");
  assert.equal(C.ct(tFor("kg"), "composer.topup", { n: 12 }), "Толуктоо · 12 кр жетишпейт");
  assert.equal(S.tx(tFor("en"), "settings.durationForced", { model: "Seedance 2.0", n: 5 }), "With reference photos Seedance 2.0 shoots only 5 s — other values are unavailable");
  assert.equal(S.tx(tFor("kg"), "settings.seconds", { n: 10 }), "10 сек");
  const labels = L.buildRefLabels(
    { tray: [{ lid: "l1", assetUid: "c".repeat(32), status: "ready", included: true, progress: 100, role: "" }], frames: { first_frame: null, last_frame: null } },
    tFor("kg"),
  );
  const label = labels["c".repeat(32)];
  assert.equal(label.text, "@Image 1", "метка чипа не переводится");
  assert.match(label.aria, /Сүрөт 1/);
});
