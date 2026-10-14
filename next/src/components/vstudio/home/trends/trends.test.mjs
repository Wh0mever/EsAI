// Первый экран: «Тренды» — порции сетки и подписи карточки (trends/trendsLogic.ts).
// Запуск (Node 22.6+):  node --experimental-strip-types --test src/components/vstudio/home/trends/*.test.mjs
import "../../../../lib/vstudio/nodeTsHooks.mjs";
import { test } from "node:test";
import assert from "node:assert/strict";

const L = await import("./trendsLogic.ts");
const S = await import("../showreelData.ts");

/** Карточка «Трендов» так, как её собирает showreelData.trendItems. */
const trend = (over = {}) =>
  S.trendItems({
    trends: [
      {
        id: 7,
        title: "Кот в очках",
        category: "other",
        kind: "video",
        model: { id: "bytedance/seedance-2.0", name: "Seedance 2.0" },
        aspect_ratio: "16:9",
        duration_s: 5,
        video_url: "/media/vstudio/clips/7.mp4",
        poster_url: "/media/vstudio/7.jpg",
        prompt: "Кот в очках читает газету",
        params: { duration: 5, resolution: "720p", aspect_ratio: "16:9" },
        ...over,
      },
    ],
  })[0];

test("порции: восемь карточек, каждое «Показать ещё» — ещё восемь", () => {
  assert.equal(L.TRENDS_PAGE, 8);
  assert.deepEqual([0, 1, 2].map(L.trendsLimit), [8, 16, 24]);
  // Двух нажатий хватает на весь потолок сервера.
  assert.ok(L.trendsLimit(2) >= S.TRENDS_MAX);
  for (const odd of [-1, -0.5, 0.7, Number.NaN, Number.POSITIVE_INFINITY]) {
    assert.equal(L.trendsLimit(odd), 8, String(odd));
  }
  assert.equal(L.trendsLimit(1.9), 16, "дробь — по целой части");
});

test("действие карточки — как у кнопки карусели: с запросом «снять похожее», без него — модель", () => {
  assert.equal(L.trendAction(trend()), "like");
  assert.equal(L.trendAction(trend({ prompt: null })), "model");
  assert.equal(L.trendAction(trend({ prompt: "   " })), "model");
});

test("подписи: название и модель; без названия карточку называет модель, второй строкой её не повторяем", () => {
  assert.deepEqual(L.trendText(trend()), { title: "Кот в очках", subtitle: "Seedance 2.0" });
  assert.deepEqual(L.trendText(trend({ title: "" })), { title: "Seedance 2.0", subtitle: "" });
  // Ни названия, ни модели — запасное название подставит компонент.
  assert.deepEqual(L.trendText(trend({ title: " ", model: null })), { title: "", subtitle: "" });
});

test("секунды на плашке: целые, без длительности — плашки нет", () => {
  assert.equal(L.trendSeconds(trend()), 5);
  assert.equal(L.trendSeconds(trend({ duration_s: 4.6 })), 5);
  assert.equal(L.trendSeconds(trend({ duration_s: 0.3 })), 1, "короче секунды — всё равно 1, а не «0 с»");
  assert.equal(L.trendSeconds(trend({ duration_s: null, params: { duration: 8 } })), 8, "из параметров, если сервер не дал своей");
  assert.equal(L.trendSeconds(trend({ duration_s: null, params: null })), 0);
});

test("вертикальный ролик в рамке 16:9 — целиком, остальные заполняют рамку", () => {
  assert.equal(L.trendFit(trend({ aspect_ratio: "9:16" })), "contain");
  assert.equal(L.trendFit(trend({ aspect_ratio: "3:4" })), "contain");
  for (const aspect of ["16:9", "1:1", "21:9", "auto", ""]) {
    assert.equal(L.trendFit(trend({ aspect_ratio: aspect, params: null })), "cover", aspect);
  }
});
