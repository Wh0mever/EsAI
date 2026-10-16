// Витрина цен показывает то, что дал сервер, и не выдумывает цену видео сама.
// Запуск (Node 22.6+):  node --experimental-strip-types --test src/lib/modelBilling.prices.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { fluxImageCredits, videoPriceFrom } from "./modelBilling.ts";

test("картинка FLUX: цена сервера главнее коэффициента", () => {
  // Режим «наценка»: FLUX Klein стоит 3, хотя коэффициент 2.
  assert.equal(fluxImageCredits({ credits_per_image: 3, markup_coefficient: 2 }), 3);
  assert.equal(fluxImageCredits({ credits_per_image: "10", markup_coefficient: 12 }), 10);
});

test("картинка FLUX без цены сервера — legacy-формула", () => {
  assert.equal(fluxImageCredits({ markup_coefficient: 4 }), 4);
  assert.equal(fluxImageCredits({ credits_per_image: null, markup_coefficient: 3.9 }), 3);
  assert.equal(fluxImageCredits({ credits_per_image: 0, markup_coefficient: 0 }), 1);
  assert.equal(fluxImageCredits({}), 1);
});

test("«от N» — самая дешёвая ячейка обеих таблиц", () => {
  const table = { "720p": { "5": 122, "10": 244 }, "480p": { "5": 54 } };
  const byAspect = { "1:1": { "480p": { "5": 31 } }, "16:9": { "480p": { "5": 54 } } };
  assert.equal(videoPriceFrom(table, byAspect), 31);
  assert.equal(videoPriceFrom(table, {}), 54);
  assert.equal(videoPriceFrom(table), 54);
});

test("нет таблицы — нет цены, а не «секунды × тариф»", () => {
  assert.equal(videoPriceFrom({}, {}), null);
  assert.equal(videoPriceFrom(undefined, undefined), null);
  assert.equal(videoPriceFrom(null, null), null);
  assert.equal(videoPriceFrom({ "720p": {} }), null);
  // Мусор в ячейке ценой не считается.
  assert.equal(videoPriceFrom({ "720p": { "5": 0, "10": Number.NaN } }), null);
});
