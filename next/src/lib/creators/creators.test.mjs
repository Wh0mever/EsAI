// EsAI Creators: формат денег, сравнение сумм, разбор ошибок API и подписи
// (lib/creators/format.ts, errors.ts, labels.ts).
// Запуск (Node 22.6+):  node --experimental-strip-types --test src/lib/creators/creators.test.mjs
import "../vstudio/nodeTsHooks.mjs";
import { test } from "node:test";
import assert from "node:assert/strict";

const F = await import("./format.ts");
const E = await import("./errors.ts");
const L = await import("./labels.ts");

// Подделка i18next.t: ключа нет в словаре — возвращает defaultValue с подстановками.
const fakeT = (key, opts = {}) =>
  String(opts.defaultValue ?? key).replace(/\{\{\s*(\w+)\s*\}\}/g, (_, n) => (n in opts ? String(opts[n]) : `{{${n}}}`));
// Переводчик, который «знает» ключ: проверяем, что ключ собран правильно.
const keyT = (key) => `[${key}]`;

const NBSP = " ";
const response = (status, data, ok = false) => ({ ok, status, url: "", data, headers: new Headers() });

test("fmtUsdt: разряды неразрывным пробелом, знаки после точки не трогаем", () => {
  assert.equal(F.fmtUsdt("8460.00"), `8${NBSP}460.00`);
  assert.equal(F.fmtUsdt("1234567.50"), `1${NBSP}234${NBSP}567.50`);
  assert.equal(F.fmtUsdt("12.345678"), "12.345678");
  assert.equal(F.fmtUsdt("999.99"), "999.99");
  assert.equal(F.fmtUsdt("0.00"), "0.00");
  assert.equal(F.fmtUsdt("-1500.00"), `-1${NBSP}500.00`);
  assert.equal(F.fmtUsdt("1000"), `1${NBSP}000`);
  assert.equal(F.fmtUsdt(""), "0.00");
  assert.equal(F.fmtUsdt(null), "0.00");
  assert.equal(F.fmtUsdt(undefined), "0.00");
  // Не число — как есть: чужую строку не переформатируем.
  assert.equal(F.fmtUsdt("n/a"), "n/a");
});

test("fmtPercent: без хвостовых нулей", () => {
  assert.equal(F.fmtPercent("15.00"), "15");
  assert.equal(F.fmtPercent("12.50"), "12.5");
  assert.equal(F.fmtPercent("10"), "10");
  assert.equal(F.fmtPercent("100.00"), "100");
  assert.equal(F.fmtPercent("0.25"), "0.25");
  assert.equal(F.fmtPercent(null), "0");
});

test("cmpDec: сравнение десятичных строк без плавающей точки", () => {
  assert.equal(F.cmpDec("10", "10.00"), 0);
  assert.equal(F.cmpDec("9.99", "10.00"), -1);
  assert.equal(F.cmpDec("10.01", "10.00"), 1);
  assert.equal(F.cmpDec("48.50", "48.5"), 0);
  assert.equal(F.cmpDec("100", "99.999999"), 1);
  assert.equal(F.cmpDec("0.1", "0.09"), 1);
  assert.equal(F.cmpDec("-5.00", "0"), -1);
  assert.equal(F.cmpDec("-0.00", "0"), 0);
  assert.equal(F.cmpDec("007.50", "7.5"), 0);
  assert.equal(F.cmpDec(".5", "0.50"), 0);
  // Суммы, которые float сравнил бы неверно.
  assert.equal(F.cmpDec("9007199254740993.01", "9007199254740993.02"), -1);
  // Не число — ноль.
  assert.equal(F.cmpDec("abc", "0"), 0);
  assert.equal(F.cmpDec("", "0.01"), -1);
  assert.equal(F.cmpDec(null, undefined), 0);
});

test("cmpDec без BigInt (старый webview) даёт тот же ответ", () => {
  const saved = globalThis.BigInt;
  try {
    globalThis.BigInt = undefined;
    assert.equal(F.cmpDec("9.99", "10.00"), -1);
    assert.equal(F.cmpDec("10.01", "10.00"), 1);
    assert.equal(F.cmpDec("48.50", "48.5"), 0);
    assert.equal(F.cmpDec("-5.00", "0"), -1);
    assert.equal(F.cmpDec("-5", "-6"), 1);
    assert.equal(F.cmpDec("-0.00", "0"), 0);
    assert.equal(F.cmpDec("100", "99.999999"), 1);
  } finally {
    globalThis.BigInt = saved;
  }
});

test("maxLevelPercent: наибольший процент, без уровней — 25", () => {
  assert.equal(F.maxLevelPercent([{ percent: "10.00" }, { percent: "25.00" }, { percent: "15.00" }]), "25");
  assert.equal(F.maxLevelPercent([{ percent: "12.50" }]), "12.5");
  assert.equal(F.maxLevelPercent([]), "25");
  assert.equal(F.maxLevelPercent(null), "25");
});

test("displayLink, формы адреса и кода, ссылки", () => {
  assert.equal(F.displayLink("https://esai.kg/?ref=TORA20"), "esai.kg/?ref=TORA20");
  assert.equal(F.displayLink(null), "");

  assert.equal(F.isTronAddressShape("TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"), true);
  assert.equal(F.isTronAddressShape(" TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t "), true);
  assert.equal(F.isTronAddressShape("0x52908400098527886E0F7030069857D2E4169EE7"), false);
  assert.equal(F.isTronAddressShape("TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6"), false);
  assert.equal(F.isTronAddressShape("TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj0O"), false);

  assert.equal(F.isCodeShape("TORA20"), true);
  assert.equal(F.isCodeShape("ABCD"), true);
  assert.equal(F.isCodeShape("ABC"), false);
  assert.equal(F.isCodeShape("1ABC"), false);
  assert.equal(F.isCodeShape("tora20"), false);
  assert.equal(F.isCodeShape("ABCDEFGHIJKLMNOPQ"), false);
  assert.equal(F.isCodeShape("TORA-20"), false);

  assert.deepEqual(F.splitLinks(" https://a.example/1 \n\nhttps://b.example/2\thttps://c.example "), [
    "https://a.example/1",
    "https://b.example/2",
    "https://c.example",
  ]);
  assert.deepEqual(F.splitLinks(""), []);

  assert.equal(F.isHttpUrl("https://instagram.com/esai.kg"), true);
  assert.equal(F.isHttpUrl("HTTP://example.com"), true);
  assert.equal(F.isHttpUrl("instagram.com/esai.kg"), false);
  assert.equal(F.isHttpUrl("ftp://example.com"), false);
  assert.equal(F.isHttpUrl("https://"), false);
  assert.equal(F.isHttpUrl("https://a b"), false);
});

test("fmtDate / fmtInt: ru и kg — русский формат, en — американский", () => {
  const iso = "2026-10-05T12:00:00Z";
  assert.match(F.fmtDate(iso, "ru"), /^\d{2}\.\d{2}\.2026$/);
  assert.equal(F.fmtDate(iso, "kg"), F.fmtDate(iso, "ru"));
  assert.equal(F.fmtDate(iso, "ky"), F.fmtDate(iso, "ru"));
  assert.match(F.fmtDate(iso, "en"), /^\d{2}\/\d{2}\/2026$/);
  assert.equal(F.fmtDate(null, "ru"), "");
  assert.equal(F.fmtDate("не дата", "ru"), "не дата");
  assert.equal(F.fmtInt(1284, "en"), "1,284");
  assert.equal(F.fmtInt(1284, "ru").replace(/\s/g, " "), "1 284");
  assert.equal(F.fmtInt(null, "ru"), "0");
});

test("toResult: код из тела; коды DRF и статус — в свои", () => {
  const taken = E.toResult(response(409, { code: "code_taken", message: "Этот промокод уже занят", detail: "Этот промокод уже занят", taken_by: 7 }));
  assert.equal(taken.ok, false);
  assert.equal(taken.error.code, "code_taken");
  assert.equal(taken.error.status, 409);
  assert.equal(taken.error.message, "Этот промокод уже занят");
  assert.equal(taken.error.data.taken_by, 7);

  const invalid = E.toResult(response(400, { code: "validation", message: "Проверьте заполнение полей", fields: { name: "Укажите имя" } }));
  assert.deepEqual(invalid.error.fields, { name: "Укажите имя" });

  for (const code of ["not_authenticated", "authentication_failed", "token_not_valid"]) {
    assert.equal(E.toResult(response(401, { code, detail: "x" })).error.code, "unauthorized");
  }
  assert.equal(E.toResult(response(403, { code: "permission_denied", detail: "x" })).error.code, "forbidden");
  assert.equal(E.toResult(response(429, { code: "throttled", detail: "x" })).error.code, "throttled");
  // "error" — заглушка обработчика: решает статус.
  assert.equal(E.toResult(response(405, { code: "error", detail: "x" })).error.code, "unknown");

  assert.equal(E.toResult(response(0, null)).error.code, "network");
  assert.equal(E.toResult(response(401, { detail: "x" })).error.code, "unauthorized");
  assert.equal(E.toResult(response(403, null)).error.code, "forbidden");
  assert.equal(E.toResult(response(404, "<html>404</html>")).error.code, "not_found");
  assert.equal(E.toResult(response(429, null)).error.code, "throttled");
  assert.equal(E.toResult(response(502, "<html>502</html>")).error.code, "server_error");
  assert.equal(E.toResult(response(400, {})).error.code, "unknown");
  // detail идёт в message, когда message нет.
  assert.equal(E.toResult(response(401, { detail: "Нет учётных данных" })).error.message, "Нет учётных данных");
});

test("toResult: успех — данные; 2xx без JSON-объекта — ошибка", () => {
  const ok = E.toResult(response(200, { mode: "on" }, true));
  assert.equal(ok.ok, true);
  assert.deepEqual(ok.data, { mode: "on" });
  const html = E.toResult(response(200, "<html>ok</html>", true));
  assert.equal(html.ok, false);
  assert.equal(html.error.code, "unknown");
});

test("errorText: текст по коду, подстановки из params и из тела", () => {
  assert.equal(E.errorText(fakeT, { code: "disabled" }), "Программа EsAI Creators сейчас недоступна");
  assert.equal(E.errorText(fakeT, { code: "amount_below_min" }, { min: "10.00" }), "Минимальная сумма вывода — 10.00 USDT");
  assert.equal(E.errorText(fakeT, { code: "что-то новое" }), E.ERROR_RU.unknown);
  assert.equal(E.errorText(keyT, { code: "code_taken" }), "[errors.code_taken]");
  // Служебные поля тела не становятся опциями перевода.
  let seen = null;
  E.errorText((key, opts) => ((seen = opts), ""), {
    code: "insufficient_available",
    data: { code: "insufficient_available", message: "m", detail: "m", count: 3, context: "x", available: "48.50" },
  });
  assert.equal(seen.ns, "creators");
  assert.equal(seen.available, "48.50");
  assert.equal("count" in seen, false);
  assert.equal("context" in seen, false);
  assert.equal("code" in seen, false);
});

test("fieldErrorText: русский текст сервера только в русском интерфейсе", () => {
  assert.equal(E.fieldErrorText(fakeT, "ru", "Укажите имя"), "Укажите имя");
  assert.equal(E.fieldErrorText(fakeT, "en", "Укажите имя"), "Проверьте это поле");
  assert.equal(E.fieldErrorText(keyT, "kg", "Укажите имя"), "[errors.field_invalid]");
  assert.equal(E.fieldErrorText(fakeT, "ru", ""), "Проверьте это поле");
});

test("поле промокода: код креатора", () => {
  assert.equal(E.promoCreatorAccepted(fakeT, "Tora"), "Промокод принят — вы пришли по приглашению Tora");
  assert.equal(E.promoCreatorError(fakeT, "too_late", "текст сервера"), E.PROMO_ERROR_RU.too_late);
  assert.equal(E.promoCreatorError(keyT, "self", "текст сервера"), "[promo.errors.self]");
  // Незнакомый код и отсутствие кода — текст сервера.
  assert.equal(E.promoCreatorError(fakeT, "retry", "текст сервера"), "текст сервера");
  assert.equal(E.promoCreatorError(fakeT, undefined, "текст сервера"), "текст сервера");
});

test("таблицы ошибок: у каждого кода сервера есть русский текст", () => {
  for (const [code, text] of Object.entries({ ...E.ERROR_RU, ...E.PROMO_ERROR_RU })) {
    assert.ok(text.trim(), code);
  }
  assert.equal(E.ERROR_RU.amount_below_min.includes("{{min}}"), true);
});

test("подписи: ключ = префикс + значение; незнакомое значение — как есть", () => {
  assert.equal(L.statusLabel(fakeT, "withdrawal", "paid"), "Выплачено");
  assert.equal(L.statusLabel(keyT, "application", "new"), "[status.application.new]");
  assert.equal(L.statusLabel(keyT, "publication", "review"), "[status.publication.review]");
  assert.equal(L.statusLabel(keyT, "commission", "held"), "[status.commission.held]");
  assert.equal(L.statusLabel(keyT, "commission", "accrued"), "[status.commission.available]");
  assert.equal(L.statusLabel(fakeT, "withdrawal", "новый_статус"), "новый_статус");
  assert.equal(L.networkLabel(keyT, "x"), "[network.x]");
  assert.equal(L.sourceLabel(fakeT, "bot"), "Telegram-бот");
  assert.equal(L.creditCategoryLabel(keyT, "start"), "[credits.category.start]");
  assert.equal(L.creditCategoryLabel(fakeT, "новая", "Подпись сервера"), "Подпись сервера");
  assert.equal(L.navLabel(fakeT), "Creators");
  assert.equal(L.labelOf(keyT, "source.", L.SOURCE_RU, "promo"), "[source.promo]");
  assert.deepEqual([...L.NETWORKS].sort(), Object.keys(L.NETWORK_RU).sort());
});

test("commissionStatusKey: accrued делится на hold и available по сроку холда", () => {
  const now = Date.parse("2026-10-05T00:00:00Z");
  assert.equal(L.commissionStatusKey({ status: "accrued", available_at: "2026-10-19T00:00:00Z" }, now), "hold");
  assert.equal(L.commissionStatusKey({ status: "accrued", available_at: "2026-10-01T00:00:00Z" }, now), "available");
  assert.equal(L.commissionStatusKey({ status: "accrued", available_at: null }, now), "available");
  assert.equal(L.commissionStatusKey({ status: "held", available_at: "2026-10-19T00:00:00Z" }, now), "held");
  // reversed: «возврат платежа» — только когда сервер назвал причину refund.
  assert.equal(L.commissionStatusKey({ status: "reversed", reason: "refund" }, now), "reversed");
  assert.equal(L.commissionStatusKey({ status: "reversed", reason: "cancelled" }, now), "cancelled");
  assert.equal(L.commissionStatusKey({ status: "reversed" }, now), "cancelled");
  assert.equal(L.commissionStatusKey({ status: "void", reason: "cancelled" }, now), "void");
});
