// Админка, «Склейка: цена»: разбор ответа, проверка поля, подписи (mergePrice.ts).
// Запуск (Node 22.6+):  node --experimental-strip-types --test src/app/admin-new/settings/mergePrice.test.mjs
import "../../../lib/vstudio/nodeTsHooks.mjs";
import { test } from "node:test";
import assert from "node:assert/strict";

const mp = await import("./mergePrice.ts");

test("parseMergePrice: ответ сервера → карточка; мусор не роняет", () => {
  // Ответ GET manage/settings/ из CONTRACT_M §5 (m1_logs/examples.json, manage_get).
  assert.deepEqual(mp.parseMergePrice({ price_credits: 20, default_price_credits: 20, overridden: false }), {
    price: 20,
    defaultPrice: 20,
    overridden: false,
  });
  assert.deepEqual(mp.parseMergePrice({ price_credits: 0, default_price_credits: 20, overridden: true }), {
    price: 0,
    defaultPrice: 20,
    overridden: true,
  });
  assert.equal(mp.parseMergePrice(null), null);
  assert.equal(mp.parseMergePrice({ price_credits: "20" }), null);
  assert.equal(mp.parseMergePrice({ price_credits: -1 }), null);
  assert.equal(mp.parseMergePrice({ price_credits: 2.5 }), null);
  assert.deepEqual(mp.parseMergePrice({ price_credits: 25 }), { price: 25, defaultPrice: 25, overridden: false });
});

test("parsePriceInput: целое 0…100000", () => {
  assert.deepEqual(mp.parsePriceInput("20"), { ok: true, value: 20 });
  assert.deepEqual(mp.parsePriceInput(" 0 "), { ok: true, value: 0 });
  assert.deepEqual(mp.parsePriceInput("100000"), { ok: true, value: 100000 });
  for (const bad of ["", "-1", "1.5", "1e3", "100001", "20 кр", "99999999999999999999"]) {
    assert.equal(mp.parsePriceInput(bad).ok, false, bad);
  }
});

test("подписи: цена из кода и своя, бесплатно", () => {
  assert.equal(mp.priceSummary({ price: 20, defaultPrice: 20, overridden: false }), "Склейка стоит 20 кр за готовый ролик — это цена из кода.");
  assert.equal(mp.priceSummary({ price: 25, defaultPrice: 20, overridden: true }), "Склейка стоит 25 кр за готовый ролик. В коде — 20 кр.");
  assert.equal(mp.priceSummary({ price: 0, defaultPrice: 20, overridden: true }), "Склейка сейчас бесплатная. В коде — 20 кр.");
  assert.equal(mp.priceText(0), "бесплатно");
});

test("errorText: связь, доступ, отказ сервера", () => {
  assert.match(mp.errorText({ status: 0 }, "x"), /Нет связи/);
  assert.match(mp.errorText({ status: 403 }, "x"), /сотрудники/);
  assert.equal(
    mp.errorText(
      { status: 400, data: { detail: "Цена склейки — целое число от 0 до 100000", errors: { price_credits: "Не число" } } },
      "x",
    ),
    "Не число",
  );
  assert.equal(mp.errorText({ status: 400, data: { detail: "Нечего сохранять: пришлите price_credits" } }, "x"), "Нечего сохранять: пришлите price_credits");
  assert.equal(mp.errorText({ status: 500, data: "<html>" }, "Не удалось"), "Не удалось (HTTP 500)");
});
