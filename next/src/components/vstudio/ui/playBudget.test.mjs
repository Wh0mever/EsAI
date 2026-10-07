// Бюджет одновременно играющих роликов первого экрана (ui/playBudget.ts).
// Запуск (Node 22.6+):  node --experimental-strip-types --test src/components/vstudio/ui/*.test.mjs
import "../../../lib/vstudio/nodeTsHooks.mjs";
import { beforeEach, test } from "node:test";
import assert from "node:assert/strict";

const B = await import("./playBudget.ts");

const on = (id) => (B.playState(id) & B.PLAY_ON) !== 0;
const solo = (id) => (B.playState(id) & B.PLAY_SOLO) !== 0;
const blocked = (id) => (B.playState(id) & B.PLAY_BLOCKED) !== 0;
const playing = (ids) => ids.filter(on);

beforeEach(() => B.resetPlayBudget());

test("играет не больше четырёх: кто раньше попросил, тот и играет", () => {
  assert.equal(B.MAX_PLAYING, 4);
  const ids = ["a", "b", "c", "d", "e", "f"];
  for (const id of ids) B.requestPlay(id);
  assert.deepEqual(playing(ids), ["a", "b", "c", "d"]);
  // Место освободилось — его получает первый из ждущих, а не последний.
  B.releasePlay("b");
  assert.deepEqual(playing(ids), ["a", "c", "d", "e"]);
  B.releasePlay("a");
  assert.deepEqual(playing(ids), ["c", "d", "e", "f"]);
});

test("активный кадр карусели играет всегда — за счёт последней из обычных карточек", () => {
  const ids = ["a", "b", "c", "d"];
  for (const id of ids) B.requestPlay(id);
  B.requestPlay("reel", true);
  assert.ok(on("reel"));
  assert.deepEqual(playing(ids), ["a", "b", "c"]);
  // Карусель ушла с экрана — карточка возвращается сама.
  B.releasePlay("reel");
  assert.deepEqual(playing(ids), ids);
});

test("повторная заявка не сдвигает очередь, смена приоритета её сохраняет", () => {
  for (const id of ["a", "b", "c", "d", "e"]) B.requestPlay(id);
  B.requestPlay("a");
  assert.deepEqual(playing(["a", "b", "c", "d", "e"]), ["a", "b", "c", "d"]);
  B.requestPlay("e", true);
  assert.deepEqual(playing(["a", "b", "c", "d", "e"]), ["a", "b", "c", "e"]);
  B.requestPlay("e", false);
  assert.deepEqual(playing(["a", "b", "c", "d", "e"]), ["a", "b", "c", "d"]);
});

test("запуск нажатием: играет один, прежний останавливается; releaseAuto его не трогает", () => {
  B.requestSolo("a");
  assert.ok(on("a") && solo("a"));
  B.requestSolo("b");
  assert.ok(!on("a") && !solo("a"));
  assert.ok(on("b") && solo("b"));
  // Увели курсор — запущенный нажатием продолжает играть.
  B.releaseAuto("b");
  assert.ok(on("b"));
  B.releasePlay("b");
  assert.ok(!on("b") && !solo("b"));
});

test("запуск нажатием находит место и в полном бюджете", () => {
  for (const id of ["a", "b", "c", "d"]) B.requestPlay(id);
  B.requestSolo("x");
  assert.ok(on("x"));
  assert.deepEqual(playing(["a", "b", "c", "d"]), ["a", "b", "c"]);
});

test("releaseAuto снимает только автоматическую заявку", () => {
  B.requestPlay("a");
  B.releaseAuto("a");
  assert.ok(!on("a"));
  B.releaseAuto("нет такого");
  B.releasePlay("нет такого");
});

test("браузер запретил автозапуск: автоматические заявки сняты, запущенный нажатием остаётся", () => {
  B.requestPlay("a");
  B.requestPlay("b", true);
  B.requestSolo("c");
  B.markAutoplayBlocked();
  assert.ok(!on("a") && !on("b"));
  assert.ok(on("c"));
  assert.ok(blocked("a") && blocked("никто"));
  B.resetPlayBudget();
  assert.ok(!blocked("a"));
});

test("подписчики узнают об изменениях и перестают после отписки", () => {
  let calls = 0;
  const off = B.subscribePlay(() => {
    calls += 1;
  });
  B.requestPlay("a");
  B.requestPlay("a"); // та же заявка — ничего не изменилось
  B.releasePlay("a");
  assert.equal(calls, 2);
  off();
  B.requestPlay("b");
  assert.equal(calls, 2);
});
