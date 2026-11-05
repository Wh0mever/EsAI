// Какой пакет показать первым, когда кредитов не хватило.
// Запуск (Node 22.6+):  node --experimental-strip-types --test src/lib/packagePick.test.mjs
import "./vstudio/nodeTsHooks.mjs";
import { test } from "node:test";
import assert from "node:assert/strict";

const pp = await import("./packagePick.ts");

// Состав пакетов как на проде: Старт 150 / Про 500 / Премиум / Максимум.
const PACKS = [
  { id: 1, tokens: 150, price: 199 },
  { id: 2, tokens: 500, price: 490 },
  { id: 3, tokens: 1200, bonus_tokens: 100, price: 990 },
  { id: 4, tokens: 3000, price: 2190 },
];

test("примеры клиента: не хватает 12 — Старт, не хватает 202 — Про", () => {
  assert.equal(pp.recommendPackage(PACKS, pp.shortfall(63, 51)).id, 1);
  assert.equal(pp.recommendPackage(PACKS, pp.shortfall(253, 51)).id, 2);
});

test("ровно на границе хватает; бонус считается", () => {
  assert.equal(pp.recommendPackage(PACKS, 150).id, 1);
  assert.equal(pp.recommendPackage(PACKS, 151).id, 2);
  assert.equal(pp.recommendPackage(PACKS, 1300).id, 3);
  assert.equal(pp.recommendPackage(PACKS, 1301).id, 4);
});

test("самый дешёвый, а не первый по порядку", () => {
  const shuffled = [PACKS[3], PACKS[1], PACKS[0], PACKS[2]];
  assert.equal(pp.recommendPackage(shuffled, 100).id, 1);
});

test("не хватает ни одного — самый большой; нехватки нет — ничего", () => {
  assert.equal(pp.recommendPackage(PACKS, 99999).id, 4);
  assert.equal(pp.recommendPackage(PACKS, 0), null);
  assert.equal(pp.recommendPackage(PACKS, null), null);
  assert.equal(pp.recommendPackage([], 10), null);
});

test("адрес тарифов: нехватка туда и обратно, мусор отбрасывается", () => {
  const href = pp.needHref("/pricing/studio", 63, 51, "scene");
  assert.equal(href, "/pricing/studio?need=12&cost=63&for=scene");
  assert.deepEqual(pp.parseNeed(href.split("?")[1]), { missing: 12, cost: 63, for: "scene" });
  assert.equal(pp.needHref("/pricing/studio", 40, 51, "scene"), "/pricing/studio");
  assert.equal(pp.parseNeed("need=abc"), null);
  assert.equal(pp.parseNeed("need=-5"), null);
  assert.deepEqual(pp.parseNeed("need=12&cost=3&for=hack"), { missing: 12, cost: 0, for: "generation" });
});
