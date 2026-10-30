// Прогрев «Скачать» на iPhone (saveWarm.ts): где включается и какой файл качать следующим.
// Сами загрузки, обрыв и таймеры проверяет src/tools/saveMedia.test.mjs.
// Запуск (Node 22.6+):  node --experimental-strip-types --test src/components/ui/saveWarm.test.mjs
import "../../lib/vstudio/nodeTsHooks.mjs";
import { test } from "node:test";
import assert from "node:assert/strict";

const { planWarm, warmAllowed, warmTooBig, WARM_MAX_BYTES, WARM_MAX_KEPT, WARM_MIN_RATIO, WARM_VISIBLE_MS } =
  await import("./saveWarm.ts");
const { detectEnv } = await import("../../tools/saveEnv.ts");

const IPHONE_SAFARI =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.0 Mobile/15E148 Safari/604.1";
// Установленное приложение: в user agent нет «Safari/», detectEnv считает его wkwebview.
const IPHONE_PWA =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148";
const ANDROID =
  "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Mobile Safari/537.36";
const WINDOWS = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36";

const hints = (over = {}) => ({
  userAgent: IPHONE_SAFARI,
  platform: "iPhone",
  maxTouchPoints: 5,
  standalone: false,
  tgProxy: false,
  tgAndroidBridge: false,
  tgMiniApp: false,
  hasShare: true,
  hasCanShare: true,
  ...over,
});
const allowed = (over, saveData = false) => {
  const h = hints(over);
  return warmAllowed(detectEnv(h), h, saveData);
};

test("пороги — как в задании: половина кнопки, секунда, два файла, 30 МБ", () => {
  assert.equal(WARM_MIN_RATIO, 0.5);
  assert.equal(WARM_VISIBLE_MS, 1000);
  assert.equal(WARM_MAX_KEPT, 2);
  assert.equal(WARM_MAX_BYTES, 30 * 1024 * 1024);
  assert.equal(warmTooBig(WARM_MAX_BYTES), false);
  assert.equal(warmTooBig(WARM_MAX_BYTES + 1), true);
  assert.equal(warmTooBig(0), false, "длина неизвестна — порог проверяется по факту");
});

test("warmAllowed: iPhone в Safari и установленное приложение — да", () => {
  assert.equal(allowed(), true);
  assert.equal(allowed({ userAgent: IPHONE_PWA, standalone: true }), true);
});

test("warmAllowed: экономия трафика, нет окна с файлом, не iPhone — нет", () => {
  assert.equal(allowed({}, true), false);
  assert.equal(allowed({ hasShare: false }), false);
  assert.equal(allowed({ hasCanShare: false }), false);
  assert.equal(allowed({ userAgent: ANDROID, platform: "Linux armv8l" }), false);
  assert.equal(allowed({ userAgent: WINDOWS, platform: "Win32", maxTouchPoints: 0 }), false);
});

test("warmAllowed: встроенные браузеры и Mini App — нет, там файл в окно не идёт", () => {
  assert.equal(allowed({ tgProxy: true }), false);
  assert.equal(allowed({ tgMiniApp: true }), false);
  assert.equal(allowed({ userAgent: `${IPHONE_SAFARI} Instagram 300.0` }), false);
  assert.equal(allowed({ userAgent: IPHONE_PWA }), false, "чужой WKWebView, не установленное приложение");
});

const none = new Set();
const entry = (url, over = {}) => ({ url, loading: false, spare: false, ...over });

test("planWarm: первый файл в очереди стартует, уже начатый и неудачный пропускаются", () => {
  assert.deepEqual(planWarm(["a", "b"], [], none), { start: "a", evict: null });
  assert.deepEqual(planWarm(["a", "b"], [entry("a")], none), { start: "b", evict: null });
  assert.deepEqual(planWarm(["a", "b"], [], new Set(["a"])), { start: "b", evict: null });
  assert.deepEqual(planWarm(["a"], [], new Set(["a"])), { start: null, evict: null });
  assert.deepEqual(planWarm([], [entry("a")], none), { start: null, evict: null });
});

test("planWarm: одновременно качается один файл — и своё нажатие тоже занимает канал", () => {
  assert.deepEqual(planWarm(["b"], [entry("a", { loading: true })], none), { start: null, evict: null });
  assert.deepEqual(planWarm(["c"], [entry("a"), entry("b", { loading: true, spare: true })], none), {
    start: null,
    evict: null,
  });
});

test("planWarm: в памяти два файла, вытесняется самый старый из ушедших с экрана", () => {
  const out = planWarm(["c"], [entry("a", { spare: true }), entry("b", { spare: true })], none);
  assert.deepEqual(out, { start: "c", evict: "a" });
  assert.deepEqual(planWarm(["c"], [entry("a"), entry("b", { spare: true })], none), { start: "c", evict: "b" });
});

test("planWarm: выбросить нечего (кнопки на экране, шторка, нажатие) — ждём", () => {
  assert.deepEqual(planWarm(["c"], [entry("a"), entry("b")], none), { start: null, evict: null });
});

test("planWarm: файлов уже больше двух из-за нажатий — новый прогрев памяти не добавляет", () => {
  const three = [entry("a", { spare: true }), entry("b"), entry("c")];
  assert.deepEqual(planWarm(["d"], three, none), { start: null, evict: null });
});
