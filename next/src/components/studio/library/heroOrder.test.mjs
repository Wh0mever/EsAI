// Мультстудия, лента героев: порядок карточек.
// Запуск (Node 22.6+):  node --experimental-strip-types --test src/components/studio/library/*.test.mjs
import "../../../lib/vstudio/nodeTsHooks.mjs";
import { test } from "node:test";
import assert from "node:assert/strict";

const { heroOrder } = await import("./heroOrder.ts");

const hero = (id, is_mine = false, audience = "kids") => ({
  id,
  name: `Герой ${id}`,
  image: `/h/${id}.png`,
  source: is_mine ? "upload" : "library",
  is_mine,
  audience,
});

const ids = (list) => list.map((c) => c.id);

test("свои — перед библиотечными, порядок внутри групп сохраняется", () => {
  const heroes = [hero(1), hero(2, true), hero(3), hero(4, true)];
  assert.deepEqual(ids(heroOrder(heroes, [], null)), [2, 4, 1, 3]);
});

test("герои мультфильма — первыми и без повторов", () => {
  const heroes = [hero(1), hero(2, true), hero(3)];
  assert.deepEqual(ids(heroOrder(heroes, [hero(3), hero(2, true)], null)), [3, 2, 1]);
});

test("выбранный из видимых остаётся на своём месте", () => {
  const heroes = [hero(1), hero(2), hero(3, true)];
  assert.deepEqual(ids(heroOrder(heroes, [], hero(2))), [3, 1, 2]);
});

test("выбранного спрятал фильтр аудитории — он сразу за героями мультфильма", () => {
  const heroes = [hero(1), hero(2, true)];
  assert.deepEqual(ids(heroOrder(heroes, [hero(5)], hero(9, false, "adults"))), [5, 9, 2, 1]);
});

test("выбранный, уже стоящий в мультфильме, не дублируется", () => {
  const heroes = [hero(1)];
  assert.deepEqual(ids(heroOrder(heroes, [hero(9, false, "adults")], hero(9, false, "adults"))), [9, 1]);
});

test("пустые списки", () => {
  assert.deepEqual(heroOrder([], [], null), []);
});
