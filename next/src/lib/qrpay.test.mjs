// Экран оплаты по единому QR: чистые помощники (lib/qrpay.ts).
// От них зависит, увидит ли человек кнопки своего банка, когда остановится
// опрос и что покажет таймер — ошибки здесь стоят оплаты.
// Запуск (Node 22.6+):  node --experimental-strip-types --test src/lib/qrpay.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  FEATURED_BANK,
  SHOWCASE_BANKS,
  appNotOpened,
  appsForPlatform,
  bankIconSources,
  clockSkewMs,
  detectEmbed,
  detectPlatform,
  isHttpsUrl,
  isQrInvoice,
  isSafeAppUrl,
  lifetimeLeft,
  localBankIcon,
  normalizeQrInvoice,
  otherMethodStep,
  pollDelayMs,
  qrFileName,
  secondsLeft,
  shouldStopPolling,
  splitApps,
  splitFeatured,
  worksWithBanks,
} from "./qrpay.ts";

const UA = {
  iphone:
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
  ipadAsMac:
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
  android:
    "Mozilla/5.0 (Linux; Android 14; SM-A546B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36",
  chrome:
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
  instagram:
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 Instagram 337.0.0.27.79",
  facebook:
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36 [FB_IAB/FB4A;FBAV/470.0.0.40.80;]",
  webview:
    "Mozilla/5.0 (Linux; Android 14; Pixel 8 Build/UQ1A; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/126.0.0.0 Mobile Safari/537.36",
  telegramAndroid:
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36 Telegram-Android/11.2.3",
};

const app = (code, extra = {}) => ({
  code,
  name: code.toUpperCase(),
  url: `${code}://pay?qr=1`,
  icon: `https://media.example/${code}.png`,
  ios: true,
  android: true,
  ...extra,
});

/* ------------------------------------------------------------------ */

test("detectPlatform: телефон Apple, iPad под видом Mac, Android, компьютер", () => {
  assert.equal(detectPlatform(UA.iphone), "ios");
  assert.equal(detectPlatform(UA.ipadAsMac, "MacIntel", 5), "ios");
  // Настоящий Mac: тач-точек нет — это компьютер.
  assert.equal(detectPlatform(UA.ipadAsMac, "MacIntel", 0), "desktop");
  assert.equal(detectPlatform(UA.ipadAsMac, "MacIntel"), "desktop");
  assert.equal(detectPlatform(UA.android), "android");
  assert.equal(detectPlatform(UA.chrome, "Win32", 0), "desktop");
  // Windows с тач-экраном — всё равно компьютер.
  assert.equal(detectPlatform(UA.chrome, "Win32", 10), "desktop");
  assert.equal(detectPlatform(""), "desktop");
  assert.equal(detectPlatform(undefined), "desktop");
});

test("detectEmbed: Mini App только с непустым initData", () => {
  assert.equal(detectEmbed(UA.chrome, { Telegram: { WebApp: { initData: "query_id=1&user=%7B%7D" } } }), "tg_miniapp");
  // Скрипт Telegram подключён на обычном сайте: initData пустой — это не Mini App.
  assert.equal(detectEmbed(UA.chrome, { Telegram: { WebApp: { initData: "" } } }), "browser");
  assert.equal(detectEmbed(UA.chrome, { Telegram: { WebApp: {} } }), "browser");
  assert.equal(detectEmbed(UA.chrome, { Telegram: { WebApp: { initData: 42 } } }), "browser");
  // Mini App важнее, чем признаки встроенного браузера в user-agent.
  assert.equal(detectEmbed(UA.telegramAndroid, { Telegram: { WebApp: { initData: "x=1" } } }), "tg_miniapp");
});

test("detectEmbed: встроенные браузеры приложений и обычные браузеры", () => {
  assert.equal(detectEmbed(UA.instagram), "inapp");
  assert.equal(detectEmbed(UA.facebook), "inapp");
  assert.equal(detectEmbed(UA.webview), "inapp");
  assert.equal(detectEmbed(UA.telegramAndroid), "inapp");
  assert.equal(detectEmbed(UA.chrome), "browser");
  assert.equal(detectEmbed(UA.iphone), "browser");
  assert.equal(detectEmbed(UA.android), "browser");
  assert.equal(detectEmbed(UA.chrome, null), "browser");
  assert.equal(detectEmbed(UA.chrome, undefined), "browser");
  assert.equal(detectEmbed("", {}), "browser");
});

test("isSafeAppUrl: свои схемы банков — да, исполняемые и локальные — нет", () => {
  assert.equal(isSafeAppUrl("mbank://pay?qr=0002"), true);
  assert.equal(isSafeAppUrl("odengi://qr/abc"), true);
  assert.equal(isSafeAppUrl("https://app.bank.kg/pay#0002"), true);
  assert.equal(isSafeAppUrl("intent://pay#Intent;scheme=bank;end"), true);
  assert.equal(isSafeAppUrl("kg.bank.app+qr://x"), true);
  assert.equal(isSafeAppUrl("javascript:alert(1)"), false);
  assert.equal(isSafeAppUrl("JavaScript:alert(1)"), false);
  assert.equal(isSafeAppUrl("data:text/html,<script>1</script>"), false);
  assert.equal(isSafeAppUrl("vbscript:x"), false);
  assert.equal(isSafeAppUrl("file:///etc/passwd"), false);
  assert.equal(isSafeAppUrl("blob:https://esai.kg/1"), false);
  assert.equal(isSafeAppUrl("about:blank"), false);
  assert.equal(isSafeAppUrl("/relative/path"), false);
  assert.equal(isSafeAppUrl("pay?qr=1"), false);
  assert.equal(isSafeAppUrl(" mbank://pay"), false);
  assert.equal(isSafeAppUrl(""), false);
  assert.equal(isSafeAppUrl(undefined), false);
  assert.equal(isSafeAppUrl(null), false);
  assert.equal(isSafeAppUrl("mbank://" + "a".repeat(2000 - 8)), true);
  assert.equal(isSafeAppUrl("mbank://" + "a".repeat(2001 - 8)), false);
});

test("isHttpsUrl: только https", () => {
  assert.equal(isHttpsUrl("https://pay.example/p/1/"), true);
  assert.equal(isHttpsUrl("http://pay.example/p/1/"), false);
  assert.equal(isHttpsUrl("javascript:alert(1)"), false);
  assert.equal(isHttpsUrl("https://"), false);
  assert.equal(isHttpsUrl(""), false);
  assert.equal(isHttpsUrl(null), false);
});

test("appsForPlatform: на компьютере кнопок банков нет", () => {
  assert.deepEqual(appsForPlatform([app("mbank"), app("odengi")], "desktop"), []);
});

test("appsForPlatform: iOS прячет только явное ios === false", () => {
  const apps = [app("mbank"), app("megapay", { ios: false }), app("optima", { ios: null })];
  assert.deepEqual(
    appsForPlatform(apps, "ios").map((a) => a.code),
    ["mbank", "optima"]
  );
});

test("appsForPlatform: Android прячет только явное android === false", () => {
  const apps = [app("mbank", { android: false }), app("megapay", { ios: false }), app("optima", { android: null })];
  assert.deepEqual(
    appsForPlatform(apps, "android").map((a) => a.code),
    ["megapay", "optima"]
  );
});

test("appsForPlatform: опасные ссылки выкидываются, порядок сервера сохраняется", () => {
  const apps = [app("zeta"), app("evil", { url: "javascript:alert(1)" }), app("alpha"), app("nourl", { url: "" }), app("mid")];
  assert.deepEqual(
    appsForPlatform(apps, "android").map((a) => a.code),
    ["zeta", "alpha", "mid"]
  );
});

test("appsForPlatform: не больше 24 и мусор на входе не роняет", () => {
  const many = Array.from({ length: 30 }, (_, i) => app(`bank${i}`));
  const out = appsForPlatform(many, "ios");
  assert.equal(out.length, 24);
  assert.equal(out[0].code, "bank0");
  assert.equal(out[23].code, "bank23");
  assert.deepEqual(appsForPlatform(undefined, "ios"), []);
  assert.deepEqual(appsForPlatform([null, {}, app("ok")], "ios").map((a) => a.code), ["ok"]);
});

test("splitApps: 8 сразу, остальные под «показать все»", () => {
  const list = (n) => Array.from({ length: n }, (_, i) => app(`b${i}`));
  let s = splitApps(list(3));
  assert.equal(s.main.length, 3);
  assert.equal(s.rest.length, 0);
  s = splitApps(list(8));
  assert.equal(s.main.length, 8);
  assert.equal(s.rest.length, 0);
  // Девять: один спрятанный банк прятать незачем — показываем все девять.
  s = splitApps(list(9));
  assert.equal(s.main.length, 9);
  assert.equal(s.rest.length, 0);
  s = splitApps(list(10));
  assert.equal(s.main.length, 8);
  assert.equal(s.rest.length, 2);
  s = splitApps(list(20));
  assert.equal(s.main.length, 8);
  assert.equal(s.rest.length, 12);
  assert.equal(s.main[0].code, "b0");
  assert.equal(s.rest[0].code, "b8");
  // Ни один банк не теряется.
  assert.equal(s.main.length + s.rest.length, 20);
  s = splitApps(list(6), 4);
  assert.equal(s.main.length, 4);
  assert.equal(s.rest.length, 2);
  assert.deepEqual(splitApps([]), { main: [], rest: [] });
});

test("localBankIcon: наш файл есть ровно у тех банков, чьи значки лежат в public", async () => {
  assert.equal(localBankIcon("mbank"), "/images/banks/mbank.webp");
  assert.equal(localBankIcon(" MBank "), "/images/banks/mbank.webp");
  assert.equal(localBankIcon("newbank"), "");
  assert.equal(localBankIcon(""), "");
  assert.equal(localBankIcon(null), "");
  // Код уходит в адрес файла — чужой путь через него не подставить.
  assert.equal(localBankIcon("../mbank"), "");
  // Каждый банк из списка действительно лежит файлом: иначе вместо значка —
  // битая картинка и снова буква.
  const { existsSync } = await import("node:fs");
  const known = ["mbank", "odengi", "bakaibank", "optima", "megapay", "kompanion", "elcart", "demirbank", "kicb", "eldik", "nambaone", "simbank"];
  for (const code of known) {
    const src = localBankIcon(code);
    assert.equal(src, `/images/banks/${code}.webp`);
    assert.equal(existsSync(new URL(`../../public${src}`, import.meta.url)), true, code);
  }
});

test("bankIconSources: свой файл → https-адрес сервера → ничего (буква)", () => {
  // Свой значок первым; адрес сервера остаётся запасным.
  assert.deepEqual(bankIconSources("mbank", "https://media.gopay.kg/payment_apps/mbank.webp"), [
    "/images/banks/mbank.webp",
    "https://media.gopay.kg/payment_apps/mbank.webp",
  ]);
  // Сервер прислал пусто или путь без узла — свой значок всё равно есть.
  assert.deepEqual(bankIconSources("mbank", ""), ["/images/banks/mbank.webp"]);
  assert.deepEqual(bankIconSources("mbank", "payment_apps/mbank.webp"), ["/images/banks/mbank.webp"]);
  // Банк, которого у нас нет: только https-адрес сервера.
  assert.deepEqual(bankIconSources("newbank", "https://media.gopay.kg/payment_apps/newbank.webp"), [
    "https://media.gopay.kg/payment_apps/newbank.webp",
  ]);
  assert.deepEqual(bankIconSources("newbank", "http://media.gopay.kg/x.webp"), []);
  assert.deepEqual(bankIconSources("newbank", "payment_apps/newbank.webp"), []);
  assert.deepEqual(bankIconSources("newbank", "javascript:alert(1)"), []);
  assert.deepEqual(bankIconSources("newbank"), []);
  assert.deepEqual(bankIconSources(undefined, null), []);
});

test("splitFeatured: МБанк — наверх, остальные в порядке сервера, никто не теряется", () => {
  assert.equal(FEATURED_BANK, "mbank");
  const list = [app("odengi"), app("mbank"), app("optima")];
  let s = splitFeatured(list);
  assert.equal(s.featured.code, "mbank");
  // Ссылка главной кнопки — та же самая, что пришла с сервера.
  assert.equal(s.featured.url, list[1].url);
  assert.deepEqual(s.others.map((a) => a.code), ["odengi", "optima"]);
  // МБанка нет (не работает на этой платформе) — главной кнопки нет.
  s = splitFeatured([app("odengi"), app("optima")]);
  assert.equal(s.featured, null);
  assert.deepEqual(s.others.map((a) => a.code), ["odengi", "optima"]);
  assert.deepEqual(splitFeatured([]), { featured: null, others: [] });
  assert.deepEqual(splitFeatured(undefined), { featured: null, others: [] });
  // Вместе с главной кнопкой показаны все банки, что и раньше.
  const many = Array.from({ length: 12 }, (_, i) => app(i === 0 ? "mbank" : `b${i}`));
  s = splitFeatured(many);
  const grid = splitApps(s.others);
  assert.equal(1 + grid.main.length + grid.rest.length, 12);
});

test("worksWithBanks: значки банков счёта, а без списка — известные всем", () => {
  const list = (n) => Array.from({ length: n }, (_, i) => app(`b${i}`));
  // Списка нет — пять банков, которые знает каждый, и никакого «+N».
  let w = worksWithBanks([]);
  assert.deepEqual(w.shown.map((b) => b.code), SHOWCASE_BANKS.map((b) => b.code));
  assert.equal(w.more, 0);
  assert.deepEqual(worksWithBanks(undefined).shown.length, SHOWCASE_BANKS.length);
  // У каждого «известного» банка есть наш значок.
  for (const bank of SHOWCASE_BANKS) assert.notEqual(localBankIcon(bank.code), "", bank.code);
  // Влезают все.
  w = worksWithBanks(list(7));
  assert.equal(w.shown.length, 7);
  assert.equal(w.more, 0);
  // Не влезли — последнее место под счётчик, и ни один банк не потерян.
  w = worksWithBanks(list(12));
  assert.equal(w.shown.length, 6);
  assert.equal(w.more, 6);
  assert.equal(w.shown[0].code, "b0");
  // Банк без значка в ряд не идёт (буква там ничего не скажет), но посчитан.
  w = worksWithBanks([app("mbank", { icon: "" }), app("nologo", { icon: "" }), app("optima", { icon: "x" })]);
  assert.deepEqual(w.shown.map((b) => b.code), ["mbank", "optima"]);
  assert.equal(w.more, 1);
  // Повтор кода и мусор не роняют и не двоят значок.
  w = worksWithBanks([app("mbank"), app("MBANK"), null, {}, app("kicb")]);
  assert.deepEqual(w.shown.map((b) => b.code), ["mbank", "kicb"]);
  assert.equal(w.more, 0);
  // Список есть, но значков нет ни у кого — показываем известные.
  w = worksWithBanks([app("x1", { icon: "" }), app("x2", { icon: "" })]);
  assert.deepEqual(w.shown.map((b) => b.code), SHOWCASE_BANKS.map((b) => b.code));
});

test("lifetimeLeft: доля срока для полоски, без срока — полоски нет", () => {
  assert.equal(lifetimeLeft(900, 900), 1);
  assert.equal(lifetimeLeft(450, 900), 0.5);
  assert.equal(lifetimeLeft(0, 900), 0);
  assert.equal(lifetimeLeft(-5, 900), 0);
  // Часы сервера и браузера разошлись — полоска не вылезает за край.
  assert.equal(lifetimeLeft(1200, 900), 1);
  assert.equal(lifetimeLeft(100, 0), null);
  assert.equal(lifetimeLeft(100, NaN), null);
  assert.equal(lifetimeLeft(NaN, 900), 0);
});

test("pollDelayMs: 3 с первые две минуты, потом 5 с", () => {
  assert.equal(pollDelayMs(0, 0, "awaiting_payment"), 3000);
  assert.equal(pollDelayMs(119_000, 0, "awaiting_payment"), 3000);
  assert.equal(pollDelayMs(120_000, 0, "awaiting_payment"), 5000);
  assert.equal(pollDelayMs(900_000, 0, "awaiting_payment"), 5000);
  assert.equal(pollDelayMs(0, 0, "processing"), 5000);
});

test("pollDelayMs: закрытый счёт досматриваем раз в 10 с", () => {
  assert.equal(pollDelayMs(0, 0, "expired"), 10000);
  assert.equal(pollDelayMs(0, 0, "cancelled"), 10000);
  assert.equal(pollDelayMs(0, 0, "failed"), 10000);
});

test("pollDelayMs: сбои удлиняют паузу, но не дольше 20 с", () => {
  assert.equal(pollDelayMs(0, 1, "awaiting_payment"), 6000);
  assert.equal(pollDelayMs(0, 2, "awaiting_payment"), 12000);
  assert.equal(pollDelayMs(0, 3, "awaiting_payment"), 20000);
  assert.equal(pollDelayMs(0, 10, "awaiting_payment"), 20000);
  assert.equal(pollDelayMs(300_000, 1, "awaiting_payment"), 10000);
  assert.equal(pollDelayMs(0, 1, "expired"), 20000);
  assert.equal(pollDelayMs(0, 50, "processing"), 20000);
});

test("shouldStopPolling: по каждому состоянию", () => {
  const exp = 1_000_000;
  assert.equal(shouldStopPolling("awaiting_payment", exp, exp - 5000), false);
  // Ждём оплату и после нуля на таймере: закрыть счёт может только сервер.
  assert.equal(shouldStopPolling("awaiting_payment", exp, exp + 600_000), false);
  assert.equal(shouldStopPolling("paid", exp, exp - 5000), true);
  assert.equal(shouldStopPolling("failed", exp, exp - 5000), true);
  assert.equal(shouldStopPolling("cancelled", exp, exp - 5000), true);
});

test("shouldStopPolling: просроченный счёт досматриваем ещё минуту", () => {
  const exp = 1_000_000;
  assert.equal(shouldStopPolling("expired", exp, exp + 1000), false);
  assert.equal(shouldStopPolling("expired", exp, exp + 60_000), false);
  assert.equal(shouldStopPolling("expired", exp, exp + 60_001), true);
  // Срок неизвестен — досматривать нечего.
  assert.equal(shouldStopPolling("expired", NaN, exp), true);
});

test("shouldStopPolling: «зачисляем» опрашиваем не дольше пяти минут", () => {
  const exp = 1_000_000;
  const started = 2_000_000;
  assert.equal(shouldStopPolling("processing", exp, started + 1000, started), false);
  assert.equal(shouldStopPolling("processing", exp, started + 300_000, started), false);
  assert.equal(shouldStopPolling("processing", exp, started + 300_001, started), true);
  // Момент начала неизвестен — не останавливаемся.
  assert.equal(shouldStopPolling("processing", exp, started + 900_000), false);
});

test("clockSkewMs: часы сервера минус часы браузера", () => {
  const at = Date.parse("2026-10-06T10:00:00+00:00");
  assert.equal(clockSkewMs("2026-10-06T10:00:05+00:00", at), 5000);
  assert.equal(clockSkewMs("2026-10-06T09:59:50+00:00", at), -10000);
  assert.equal(clockSkewMs("2026-10-06T16:00:00+06:00", at), 0);
  assert.equal(clockSkewMs(null, at), 0);
  assert.equal(clockSkewMs("", at), 0);
  assert.equal(clockSkewMs("не дата", at), 0);
  assert.equal(clockSkewMs("2026-10-06T10:00:05+00:00", NaN), 0);
});

test("secondsLeft: целое, не меньше нуля, с поправкой на часы", () => {
  const exp = "2026-10-06T10:15:00+00:00";
  const now = Date.parse("2026-10-06T10:00:00+00:00");
  assert.equal(secondsLeft(exp, now, 0), 900);
  // Часы браузера отстают на 30 с: по серверу осталось меньше.
  assert.equal(secondsLeft(exp, now, 30_000), 870);
  // Часы браузера спешат на минуту.
  assert.equal(secondsLeft(exp, now, -60_000), 960);
  assert.equal(secondsLeft(exp, now + 899_400, 0), 1);
  assert.equal(secondsLeft(exp, now + 900_000, 0), 0);
  assert.equal(secondsLeft(exp, now + 5_000_000, 0), 0);
  assert.equal(Number.isInteger(secondsLeft(exp, now + 123, 77)), true);
  assert.equal(secondsLeft(null, now, 0), 0);
  assert.equal(secondsLeft("не дата", now, 0), 0);
  assert.equal(secondsLeft(exp, now, NaN), 900);
});

test("otherMethodStep: пока QR ждёт оплаты — отмена, пауза, уход после паузы", () => {
  assert.equal(otherMethodStep("awaiting_payment", "idle"), "cancel");
  assert.equal(otherMethodStep("awaiting_payment", "sending"), "wait");
  // Банк обрабатывает оплату: полминуты с QR не отпускаем.
  assert.equal(otherMethodStep("awaiting_payment", "hold"), "wait");
  assert.equal(otherMethodStep("awaiting_payment", "armed"), "abandon");
});

test("otherMethodStep: закрытый счёт отпускает сразу, даже во время паузы", () => {
  // Регрессия: после ответа «busy» счёт истёк или банк отказал, а кнопка
  // «Оплатить другим способом» на экране закрытого счёта молчала до 30 с.
  for (const state of ["expired", "failed", "cancelled"]) {
    for (const phase of ["idle", "sending", "hold", "armed"]) {
      assert.equal(otherMethodStep(state, phase), "leave", `${state}/${phase}`);
    }
  }
});

test("appNotOpened: подсказка только если страница не уходила с экрана", () => {
  const WAIT = 2500;
  // Таймер сработал вовремя, страница всё время была на экране — банк не открылся.
  assert.equal(appNotOpened(false, false, 2500, WAIT), true);
  assert.equal(appNotOpened(false, false, 2600, WAIT), true);
  // Страница скрыта прямо сейчас — человек в приложении банка.
  assert.equal(appNotOpened(false, true, 2500, WAIT), false);
  // Регрессия (iOS): банк открылся, вкладку заморозили, человек вернулся — в
  // момент срабатывания таймера страница снова видна.
  assert.equal(appNotOpened(true, false, 2500, WAIT), false);
  assert.equal(appNotOpened(true, false, 40_000, WAIT), false);
  // Событие ухода не пришло, но таймер сработал намного позже срока — страница спала.
  assert.equal(appNotOpened(false, false, 40_000, WAIT), false);
  assert.equal(appNotOpened(false, false, NaN, WAIT), false);
});

test("qrFileName: хвост номера заказа, только буквы и цифры", () => {
  assert.equal(qrFileName("tokpkg-7-3-0a1b2c3d4e"), "esai-qr-2c3d4e.png");
  assert.equal(qrFileName("TOKPKG-7-3-0A1B2C3D4E"), "esai-qr-2c3d4e.png");
  assert.equal(qrFileName("a-b"), "esai-qr-ab.png");
  assert.equal(qrFileName("../../x/..\\y"), "esai-qr-xy.png");
  assert.equal(qrFileName(""), "esai-qr.png");
  assert.equal(qrFileName(undefined), "esai-qr.png");
});

test("isQrInvoice: ответ покупки — это QR-счёт, а не ссылка на банк", () => {
  assert.equal(isQrInvoice({ kind: "qr", order_id: "tokpkg-7-3-0a1b2c3d4e" }), true);
  assert.equal(isQrInvoice({ kind: "qr", order_id: "" }), false);
  assert.equal(isQrInvoice({ kind: "qr" }), false);
  assert.equal(isQrInvoice({ kind: "qr", order_id: 5 }), false);
  assert.equal(isQrInvoice({ kind: "crypto", order_id: "x" }), false);
  assert.equal(isQrInvoice({ redirect_url: "https://pay.example/", order_id: "x" }), false);
  assert.equal(isQrInvoice(null), false);
  assert.equal(isQrInvoice(undefined), false);
  assert.equal(isQrInvoice("qr"), false);
});

test("normalizeQrInvoice: полный ответ проходит как есть", () => {
  const full = {
    kind: "qr",
    provider: "gopay",
    resumed: false,
    order_id: "tokpkg-7-3-0a1b2c3d4e",
    status: "created",
    ui_state: "awaiting_payment",
    amount: "392.00",
    currency: "KGS",
    original_amount: "490.00",
    discount_percent: 20,
    package: { id: 3, name: "Про", tokens: 500, bonus_tokens: 0 },
    credits: { total: 500, credited: 0 },
    qr: { data: "https://pay.example#0002", image_url: "https://pay.example/p/1/qr/" },
    apps: [{ code: "megapay", name: "MegaPay", url: "megapay://x", icon: "https://m.example/i.png", ios: false, android: true }],
    checkout_url: "https://pay.example/p/1/",
    created_at: "2026-10-06T10:00:00+00:00",
    expires_at: "2026-10-06T10:15:00+00:00",
    server_time: "2026-10-06T10:00:01+00:00",
    seconds_left: 899,
    lifetime_seconds: 900,
    is_test: false,
    can_cancel: true,
    return_to: "/profile",
  };
  assert.deepEqual(normalizeQrInvoice(full), full);
});

test("normalizeQrInvoice: недостающие поля не роняют экран", () => {
  const n = normalizeQrInvoice({ kind: "qr", order_id: "tokpkg-1-1-aaaaaaaaaa", ui_state: "что-то новое" });
  assert.equal(n.ui_state, "awaiting_payment");
  assert.deepEqual(n.apps, []);
  assert.deepEqual(n.qr, { data: "", image_url: "" });
  assert.deepEqual(n.package, { id: null, name: "", tokens: 0, bonus_tokens: 0 });
  assert.deepEqual(n.credits, { total: 0, credited: 0 });
  assert.equal(n.original_amount, null);
  assert.equal(n.discount_percent, null);
  assert.equal(n.expires_at, null);
  assert.equal(n.seconds_left, 0);
  assert.equal(n.is_test, false);
  assert.equal(n.checkout_url, "");
});

test("normalizeQrInvoice: false у банка не превращается в null", () => {
  const n = normalizeQrInvoice({
    kind: "qr",
    order_id: "tokpkg-1-1-aaaaaaaaaa",
    ui_state: "awaiting_payment",
    apps: [
      { code: "megapay", url: "megapay://x", ios: false, android: true },
      { code: "nolink" },
      null,
      { code: "optima", name: "Optima", url: "optima://x" },
    ],
  });
  assert.equal(n.apps.length, 2);
  assert.equal(n.apps[0].ios, false);
  assert.equal(n.apps[0].android, true);
  assert.equal(n.apps[0].name, "megapay");
  assert.equal(n.apps[1].ios, null);
  assert.equal(n.apps[1].android, null);
  assert.deepEqual(
    appsForPlatform(n.apps, "ios").map((a) => a.code),
    ["optima"]
  );
});
