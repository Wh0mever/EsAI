// Ленты первого экрана (home/strip/stripLogic.ts): края, шаг стрелки, давность проекта.
// Запуск (Node 22.6+):  node --experimental-strip-types --test src/components/vstudio/home/strip/*.test.mjs
import "../../../../lib/vstudio/nodeTsHooks.mjs";
import { test } from "node:test";
import assert from "node:assert/strict";

const L = await import("./stripLogic.ts");

/* ---------- края ---------- */

test("края: гаснет только та сторона, за которой есть продолжение", () => {
  // Всё помещается (чипы на широком экране) — маски нет.
  assert.equal(L.edgeFade(0, 600, 600), "none");
  assert.equal(L.edgeFade(0, 600, 601.5), "none");
  assert.equal(L.edgeFade(0, 0, 0), "none");
  // В начале — первая карточка не должна быть полупрозрачной.
  assert.equal(L.edgeFade(0, 360, 1800), "start");
  assert.equal(L.edgeFade(1.5, 360, 1800), "start");
  assert.equal(L.edgeFade(240, 360, 1800), "mid");
  // Дробная прокрутка на плотном экране: до конца «не хватает» полпикселя.
  assert.equal(L.edgeFade(1439.4, 360, 1800), "end");
  assert.equal(L.edgeFade(1440, 360, 1800), "end");
});

test("шаг стрелки: почти экран, но целым числом карточек", () => {
  // 1144 px ленты, карточка 220 + 12: помещается 4 целых шага.
  assert.equal(L.pageStep(1144, 232), 4 * 232);
  // Узкая лента: хотя бы одна карточка.
  assert.equal(L.pageStep(200, 232), 232);
  // Шаг карточки неизвестен — просто на экран без «хвоста».
  assert.equal(L.pageStep(1000, 0), 904);
  assert.equal(L.pageStep(120, 0), 60);
});

/* ---------- давность ---------- */

const at = (y, m, d, h = 12, min = 0, s = 0) => new Date(y, m - 1, d, h, min, s);
const iso = (date) => date.toISOString();
const ago = (lang) => new Intl.RelativeTimeFormat(lang, { numeric: "auto" });

test("давность: минуты и часы в тот же день", () => {
  const now = at(2026, 10, 7, 15, 0).getTime();
  assert.equal(L.lastActive(iso(at(2026, 10, 7, 14, 59, 30)), now, "ru"), ago("ru").format(0, "second"));
  assert.equal(L.lastActive(iso(at(2026, 10, 7, 14, 55)), now, "ru"), "5 минут назад");
  assert.equal(L.lastActive(iso(at(2026, 10, 7, 14, 0, 1)), now, "ru"), "59 минут назад");
  assert.equal(L.lastActive(iso(at(2026, 10, 7, 13, 0)), now, "ru"), "2 часа назад");
  assert.equal(L.lastActive(iso(at(2026, 10, 7, 0, 5)), now, "ru"), "14 часов назад");
  assert.equal(L.lastActive(iso(at(2026, 10, 7, 14, 55)), now, "en"), "5 minutes ago");
});

test("давность: дни по календарю, как группы «Сегодня / Вчера» в левой колонке", () => {
  // Час ночи: проект из вчерашнего вечера — «вчера», а не «2 часа назад».
  const night = at(2026, 10, 7, 1, 0).getTime();
  assert.equal(L.lastActive(iso(at(2026, 10, 6, 23, 0)), night, "ru"), "вчера");
  // Но если прошло меньше часа — минуты, через полночь тоже.
  assert.equal(L.lastActive(iso(at(2026, 10, 6, 23, 40)), at(2026, 10, 7, 0, 10).getTime(), "ru"), "30 минут назад");

  const now = at(2026, 10, 7, 15, 0).getTime();
  assert.equal(L.lastActive(iso(at(2026, 10, 6, 16, 0)), now, "ru"), "вчера");
  assert.equal(L.lastActive(iso(at(2026, 10, 5, 9, 0)), now, "ru"), ago("ru").format(-2, "day"));
  assert.equal(L.lastActive(iso(at(2026, 10, 1, 23, 59)), now, "ru"), "6 дней назад");
  assert.equal(L.lastActive(iso(at(2026, 10, 6, 16, 0)), now, "en"), "yesterday");
});

test("давность: старше недели — дата, прошлый год — с годом", () => {
  const now = at(2026, 10, 7, 15, 0).getTime();
  const week = at(2026, 9, 30, 10, 0);
  const lastYear = at(2025, 12, 31, 10, 0);
  const date = new Intl.DateTimeFormat("ru", { day: "numeric", month: "short" });
  const dateYear = new Intl.DateTimeFormat("ru", { day: "numeric", month: "short", year: "numeric" });
  assert.equal(L.lastActive(iso(week), now, "ru"), date.format(week));
  assert.equal(L.lastActive(iso(lastYear), now, "ru"), dateYear.format(lastYear));
  assert.match(L.lastActive(iso(lastYear), now, "ru"), /2025/);
});

test("давность: язык сайта «kg» — это киргизский (ky), неизвестный язык — по-русски", () => {
  const now = at(2026, 10, 7, 15, 0).getTime();
  const then = iso(at(2026, 10, 7, 14, 55));
  const kySupported = Intl.RelativeTimeFormat.supportedLocalesOf(["ky"]).length > 0;
  assert.equal(L.lastActive(then, now, "kg"), ago(kySupported ? "ky" : "ru").format(-5, "minute"));
  assert.equal(L.lastActive(then, now, "zz-unknown"), "5 минут назад");
  assert.equal(L.lastActive(then, now, ""), "5 минут назад");
});

test("давность: часы устройства отстают, дата битая, часов ещё нет — без выдумок", () => {
  const now = at(2026, 10, 7, 15, 0).getTime();
  // Проект «из будущего» (часы телефона отстают от сервера) — «сейчас», а не «через 2 минуты».
  assert.equal(L.lastActive(iso(at(2026, 10, 7, 15, 2)), now, "ru"), ago("ru").format(0, "second"));
  assert.equal(L.lastActive("не дата", now, "ru"), "");
  assert.equal(L.lastActive("", now, "ru"), "");
  // На сервере часов нет (0) — подпись не рисуем.
  assert.equal(L.lastActive(iso(at(2026, 10, 7, 14, 55)), 0, "ru"), "");
});
