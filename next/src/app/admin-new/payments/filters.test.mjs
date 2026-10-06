// Админка, список платежей: фильтр из адреса страницы (filters.ts).
// Запуск (Node 22.6+):  node --experimental-strip-types --test src/app/admin-new/payments/filters.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { FILTERS, filterFromParams, reviewLabel } from "./filters.ts";

test("filterFromParams: ?unsettled=1 открывает «Оплачено, не зачислено»", () => {
  assert.equal(filterFromParams(new URLSearchParams("unsettled=1")), "unsettled");
  assert.equal(filterFromParams(new URLSearchParams("page=2&unsettled=1")), "unsettled");
  assert.equal(filterFromParams(new URLSearchParams("")), "all");
  assert.equal(filterFromParams(new URLSearchParams("unsettled=0")), "all");
  assert.equal(filterFromParams(new URLSearchParams("unsettled=true")), "all");
  assert.equal(filterFromParams(null), "all");
  assert.equal(filterFromParams(undefined), "all");
});

test("FILTERS: у фильтра из ссылки есть кнопка и запрос к серверу", () => {
  const unsettled = FILTERS.find((f) => f.key === filterFromParams(new URLSearchParams("unsettled=1")));
  assert.ok(unsettled);
  assert.equal(unsettled.query, "unsettled=1");
  assert.equal(FILTERS[0].key, "all");
  assert.equal(new Set(FILTERS.map((f) => f.key)).size, FILTERS.length);
});

test("страница берёт параметры у роутера, а не из window.location", () => {
  // Регрессия: ссылка <Link href="/admin-new/payments?unsettled=1"> из настроек
  // открывала список без фильтра. При клиентском переходе Next меняет адрес
  // (history.pushState) в useInsertionEffect, то есть ПОСЛЕ первого рендера
  // новой страницы, и window.location в инициализаторе useState ещё старый.
  // Отрендерить страницу в node-тесте нечем, поэтому сторожим сам источник.
  const page = readFileSync(new URL("./page.tsx", import.meta.url), "utf8");
  assert.equal(/window\.location/.test(page), false, "page.tsx не должен читать window.location");
  assert.match(page, /filterFromParams\(\s*searchParams\s*\)/);
  assert.match(page, /useSearchParams\(\)/);
  assert.match(page, /<Suspense\b/);
});

test("reviewLabel: причина разбора словами, незнакомый код — как есть", () => {
  assert.equal(reviewLabel("paid_after_refund_mark"), "оплачен после отметки возврата");
  assert.equal(reviewLabel("mismatch:amount"), "сумма не совпала с заказом");
  assert.equal(reviewLabel("discount_reused"), "скидка использована дважды");
  // Крипта и будущие коды: причина не должна пропасть.
  assert.equal(reviewLabel("overpaid"), "overpaid");
  assert.equal(reviewLabel(true), "true");
  assert.equal(reviewLabel(undefined), "");
  const page = readFileSync(new URL("./page.tsx", import.meta.url), "utf8");
  assert.match(page, /reviewLabel\(reviewFlag\)/);
});
