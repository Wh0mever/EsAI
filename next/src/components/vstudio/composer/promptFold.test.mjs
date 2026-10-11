// Видеостудия, панель запроса: когда поле запроса свёрнуто (composer/promptFold.ts) —
// все переходы, все условия «сворачивать нельзя», свёрнутая высота и порог с запасом.
// Запуск (Node 22.6+):  node --experimental-strip-types --test src/components/vstudio/composer/promptFold.test.mjs
import "../../../lib/vstudio/nodeTsHooks.mjs";
import { test } from "node:test";
import assert from "node:assert/strict";

const F = await import("./promptFold.ts");
const { foldStep, foldBlocked, foldCompact, foldNeeded, compactHeight, lastKnown, NO_GUARDS } = F;

const REST = { fold: "rest", leaving: false, waking: false };
const OPEN = { fold: "open", leaving: false, waking: false };
const SHUT = { fold: "shut", leaving: false, waking: false };
const LEAVING = { fold: "open", leaving: true, waking: false };

const g = (over = {}) => ({ ...NO_GUARDS, ...over });
const open = (by) => ({ type: "open", by });

/** Цепочка событий без условий. */
function run(events, from = REST, guards = NO_GUARDS) {
  return events.reduce((m, e) => foldStep(m, e, guards), from);
}

/* ------------------------------------------------------------------ */
/* Развернуть                                                          */
/* ------------------------------------------------------------------ */

test("фокус в поле, кнопка, ввод, пример и «@» разворачивают и свёрнутое само, и свёрнутое кнопкой", () => {
  for (const by of ["field", "toggle", "typed", "filled", "mention"]) {
    assert.deepEqual(foldStep(REST, open(by), NO_GUARDS), OPEN, `rest · ${by}`);
    assert.deepEqual(foldStep(SHUT, open(by), NO_GUARDS), OPEN, `shut · ${by}`);
  }
});

test("брошенный файл и проблема разворачивают только то, что свернулось само", () => {
  assert.deepEqual(foldStep(REST, open("drop"), NO_GUARDS), OPEN);
  for (const by of ["drop", "problem"]) assert.equal(foldStep(SHUT, open(by), NO_GUARDS), SHUT, by);
});

test("проблема без человека в панели: поле развёрнуто, но уже ждёт своего ухода", () => {
  assert.deepEqual(foldStep(REST, open("problem"), g({ problem: true })), { fold: "open", leaving: true, waking: false });
  assert.deepEqual(foldStep(REST, open("problem"), g({ problem: true, focusInside: true })), OPEN);
  // Пока проблема на экране, таймер упирается в неё; исчезла — поле сворачивается.
  const held = foldStep(LEAVING, { type: "timer" }, g({ problem: true }));
  assert.equal(held, LEAVING);
  assert.deepEqual(foldStep(held, { type: "timer" }, NO_GUARDS), REST);
});

test("под нажатой кнопкой мыши текст не двигается: разворот ждёт отпускания", () => {
  const down = g({ pointerDown: true });
  for (const by of ["field", "filled", "mention", "drop", "problem"]) {
    const pressed = foldStep(REST, open(by), down);
    assert.deepEqual(pressed, { fold: "rest", leaving: false, waking: true }, by);
    assert.deepEqual(foldStep(pressed, { type: "pointerUp" }, NO_GUARDS), OPEN, by);
  }
  // Свёрнутое кнопкой: фокус в поле под нажатой кнопкой — тоже после отпускания, а мягкая причина — никогда.
  assert.deepEqual(run([{ type: "pointerUp" }], foldStep(SHUT, open("field"), down)), OPEN);
  assert.equal(foldStep(SHUT, open("problem"), down), SHUT);
  // Кнопка «Показать весь запрос» срабатывает по клику — указатель уже отпущен.
  assert.deepEqual(foldStep(REST, open("toggle"), down), OPEN);
  // Отпускание без просьбы ничего не меняет.
  assert.equal(foldStep(REST, { type: "pointerUp" }, NO_GUARDS), REST);
  assert.equal(foldStep(OPEN, { type: "pointerUp" }, NO_GUARDS), OPEN);
});

test("в поле печатают — оно разворачивается сразу, и под нажатием, которое так и не отпустили", () => {
  const down = g({ pointerDown: true, focusInside: true });
  // Правый клик в свёрнутый текст на macOS: отпускание забрало меню, разворот остался отложенным.
  const pressed = foldStep(REST, open("field"), down);
  assert.deepEqual(pressed, { fold: "rest", leaving: false, waking: true });
  // Повторный фокус и «текст дорос до обрезки» его не разворачивают — только ввод.
  assert.equal(foldStep(pressed, open("field"), down), pressed);
  assert.deepEqual(foldStep(pressed, open("typed"), down), OPEN);
  assert.deepEqual(foldStep(REST, open("typed"), down), OPEN);
  assert.deepEqual(foldStep(SHUT, open("typed"), down), OPEN);
  // Развёрнутое поле ввод не трогает: тот же объект, стор не дёргается на каждую букву.
  assert.equal(foldStep(OPEN, open("typed"), down), OPEN);
});

test("нажал в поле и увёл фокус, не отпуская, — разворот отменяется", () => {
  const pressed = foldStep(REST, open("field"), g({ pointerDown: true }));
  const left = foldStep(pressed, { type: "leave" }, g({ pointerDown: true }));
  assert.deepEqual(left, REST);
  assert.deepEqual(foldStep(left, { type: "pointerUp" }, NO_GUARDS), REST);
});

test("уже развёрнуто: фокус в поле отменяет уход, мягкая причина — нет", () => {
  assert.equal(foldStep(OPEN, open("field"), NO_GUARDS), OPEN);
  assert.deepEqual(foldStep(LEAVING, open("field"), NO_GUARDS), OPEN);
  assert.deepEqual(foldStep(LEAVING, open("field"), g({ pointerDown: true })), OPEN);
  for (const by of ["drop", "problem"]) assert.equal(foldStep(LEAVING, open(by), NO_GUARDS), LEAVING, by);
});

/* ------------------------------------------------------------------ */
/* Свернуть само                                                       */
/* ------------------------------------------------------------------ */

test("ушёл из панели: поле сворачивается после паузы, а не сразу", () => {
  const left = foldStep(OPEN, { type: "leave" }, NO_GUARDS);
  assert.deepEqual(left, LEAVING);
  assert.equal(foldStep(left, { type: "leave" }, NO_GUARDS), left);
  assert.deepEqual(foldStep(left, { type: "timer" }, NO_GUARDS), REST);
});

test("фокус перешёл на кнопку той же панели — уход отменён, поле остаётся развёрнутым", () => {
  const back = run([{ type: "leave" }, { type: "return" }], OPEN);
  assert.deepEqual(back, OPEN);
  assert.equal(foldStep(back, { type: "timer" }, NO_GUARDS), back);
  // Свёрнутое поле кнопки панели не разворачивают: чип параметра нажали — текст на месте.
  assert.equal(foldStep(REST, { type: "return" }, NO_GUARDS), REST);
  assert.equal(foldStep(SHUT, { type: "return" }, NO_GUARDS), SHUT);
});

test("уход из свёрнутого поля ничего не заводит", () => {
  assert.equal(foldStep(REST, { type: "leave" }, NO_GUARDS), REST);
  assert.equal(foldStep(SHUT, { type: "leave" }, NO_GUARDS), SHUT);
  assert.equal(foldStep(REST, { type: "timer" }, NO_GUARDS), REST);
});

test("шторка панели открыта или поле во весь экран: уход не считается уходом", () => {
  for (const name of ["overlay", "fullscreen"]) {
    assert.equal(foldStep(OPEN, { type: "leave" }, g({ [name]: true })), OPEN, name);
    // Уход, начатый до шторки, она сама не отменяет (это делает return), но и заново не начинает.
    assert.equal(foldStep(LEAVING, { type: "leave" }, g({ [name]: true })), LEAVING, name);
    assert.equal(foldStep(REST, { type: "leave" }, g({ [name]: true })), REST, name);
  }
  // Ожидание отпускания уход снимает в любом случае.
  assert.deepEqual(foldStep({ fold: "rest", leaving: false, waking: true }, { type: "leave" }, g({ overlay: true })), REST);
  // Остальные условия на сам уход не влияют: они держат поле уже на таймере.
  for (const name of ["pointerDown", "composing", "selection", "dragging", "problem"]) {
    assert.deepEqual(foldStep(OPEN, { type: "leave" }, g({ [name]: true })), LEAVING, name);
  }
});

test("каждое условие само по себе держит поле развёрнутым; таймер возвращает то же состояние", () => {
  const names = Object.keys(NO_GUARDS);
  assert.deepEqual(names.sort(), ["composing", "dragging", "focusInside", "fullscreen", "overlay", "pointerDown", "problem", "selection"]);
  for (const name of names) {
    const guards = g({ [name]: true });
    assert.equal(foldBlocked(guards), name);
    const held = foldStep(LEAVING, { type: "timer" }, guards);
    assert.equal(held, LEAVING, name);
    // Условие ушло — следующая пауза сворачивает.
    assert.deepEqual(foldStep(held, { type: "timer" }, NO_GUARDS), REST, name);
  }
  assert.equal(foldBlocked(NO_GUARDS), null);
  // Несколько сразу: называется первое по порядку проверки.
  assert.equal(foldBlocked(g({ overlay: true, pointerDown: true })), "pointerDown");
});

test("таймер, оставшийся от прошлого ухода, свёрнутое кнопкой не трогает", () => {
  assert.deepEqual(foldStep({ fold: "shut", leaving: true, waking: false }, { type: "timer" }, NO_GUARDS), SHUT);
});

/* ------------------------------------------------------------------ */
/* Кнопка                                                              */
/* ------------------------------------------------------------------ */

test("кнопка «Свернуть запрос» сворачивает, не глядя на условия", () => {
  const all = Object.fromEntries(Object.keys(NO_GUARDS).map((k) => [k, true]));
  assert.deepEqual(foldStep(OPEN, { type: "shut" }, all), SHUT);
  assert.deepEqual(foldStep(LEAVING, { type: "shut" }, all), SHUT);
  assert.equal(foldStep(SHUT, { type: "shut" }, NO_GUARDS), SHUT);
});

test("свернул кнопкой → кликнул в текст → снова развёрнуто и дальше живёт по общему правилу", () => {
  const m = run([{ type: "shut" }, open("field"), { type: "leave" }, { type: "timer" }], OPEN);
  assert.deepEqual(m, REST);
});

test("развернул кнопкой — остаётся развёрнутым, пока не свернёт сам или не уйдёт из панели", () => {
  const opened = foldStep(REST, open("toggle"), NO_GUARDS);
  // Фокус на самой кнопке: без ухода таймеру нечего делать.
  assert.equal(foldStep(opened, { type: "timer" }, g({ focusInside: true })), opened);
  assert.deepEqual(run([{ type: "leave" }, { type: "timer" }], opened), REST);
  assert.deepEqual(foldStep(opened, { type: "shut" }, NO_GUARDS), SHUT);
});

/* ------------------------------------------------------------------ */
/* Запуск, короткий текст, новый проект                                */
/* ------------------------------------------------------------------ */

test("запуск принят: поле уступает место результату; запуск с клавиатуры поле не трогает", () => {
  assert.deepEqual(foldStep(OPEN, { type: "run", typing: false }, g({ focusInside: true, overlay: true })), REST);
  assert.deepEqual(foldStep(LEAVING, { type: "run", typing: false }, NO_GUARDS), REST);
  assert.equal(foldStep(OPEN, { type: "run", typing: true }, NO_GUARDS), OPEN);
  assert.equal(foldStep(REST, { type: "run", typing: false }, NO_GUARDS), REST);
  assert.equal(foldStep(SHUT, { type: "run", typing: false }, NO_GUARDS), SHUT);
});

test("отказ запуска события не даёт — поле остаётся как было", () => {
  // Композер шлёт run только из ветки успешного ответа; без события состояние не меняется.
  assert.equal(run([], OPEN), OPEN);
});

test("текст снова помещается или открыт другой проект: «свёрнуто кнопкой» становится обычным", () => {
  for (const type of ["fits", "reset"]) {
    assert.deepEqual(foldStep(SHUT, { type }, NO_GUARDS), REST, type);
    assert.equal(foldStep(REST, { type }, NO_GUARDS), REST, type);
    assert.equal(foldStep(OPEN, { type }, NO_GUARDS), OPEN, type);
    assert.equal(foldStep(LEAVING, { type }, NO_GUARDS), LEAVING, type);
  }
});

test("подсказки ещё в пути (сменили модель или параметр): «мешает запуску» держит прошлый ответ", () => {
  // Ответ известен — он и есть ответ, что бы ни было раньше.
  assert.equal(lastKnown(true, true, false), true);
  assert.equal(lastKnown(true, false, true), false);
  // Ответа на новый запрос ещё нет: подсказок нет вовсе (now = false), но ошибка не исправлена.
  assert.equal(lastKnown(false, false, true), true);
  // И наоборот: до ответа проблема из ниоткуда не появляется.
  assert.equal(lastKnown(false, false, false), false);
  assert.equal(lastKnown(false, true, false), false);
});

test("состояния не смешиваются: уход бывает только у развёрнутого, ожидание отпускания — только у свёрнутого", () => {
  const events = [
    open("field"),
    open("toggle"),
    open("typed"),
    open("drop"),
    open("problem"),
    { type: "shut" },
    { type: "leave" },
    { type: "return" },
    { type: "pointerUp" },
    { type: "timer" },
    { type: "run", typing: false },
    { type: "run", typing: true },
    { type: "fits" },
    { type: "reset" },
  ];
  const guardSets = [NO_GUARDS, g({ pointerDown: true }), g({ focusInside: true }), g({ problem: true, overlay: true })];
  let seen = [REST];
  for (let depth = 0; depth < 4; depth++) {
    const next = [];
    for (const m of seen) {
      for (const e of events) {
        for (const guards of guardSets) {
          const n = foldStep(m, e, guards);
          assert.ok(["rest", "open", "shut"].includes(n.fold));
          if (n.leaving) assert.equal(n.fold, "open", `leaving при ${n.fold} после ${e.type}`);
          if (n.waking) assert.notEqual(n.fold, "open", `waking при open после ${e.type}`);
          if (!next.some((x) => x.fold === n.fold && x.leaving === n.leaving && x.waking === n.waking)) next.push(n);
        }
      }
    }
    seen = next;
  }
});

/* ------------------------------------------------------------------ */
/* Что видно                                                           */
/* ------------------------------------------------------------------ */

test("обрезка: всё, кроме open; во весь экран — никогда", () => {
  assert.equal(foldCompact("rest", false), true);
  assert.equal(foldCompact("shut", false), true);
  assert.equal(foldCompact("open", false), false);
  for (const fold of ["rest", "open", "shut"]) assert.equal(foldCompact(fold, true), false, fold);
});

/* ------------------------------------------------------------------ */
/* Высота                                                              */
/* ------------------------------------------------------------------ */

// Поле редактора: поля 6 + 6 px, не ниже 52 px; строка 26 px (16 px) или 24.375 px (15 px с мышью).
const TOUCH = { lineHeight: 26, padTop: 6, padBottom: 6, minHeight: 52 };
const MOUSE = { lineHeight: 24.375, padTop: 6, padBottom: 6, minHeight: 52 };
const textHeight = (box, lines) => Math.max(box.minHeight, lines * box.lineHeight + box.padTop + box.padBottom);

test("свёрнутая высота: две строки с 768 px, на телефоне — обычная высота пустого поля", () => {
  assert.equal(compactHeight(MOUSE, F.FOLD_LINES.wide), 61);
  assert.equal(compactHeight(TOUCH, F.FOLD_LINES.wide), 64);
  // Одна строка (38 px) ниже самого поля (52 px): короткий запрос не должен стать ниже.
  assert.equal(compactHeight(TOUCH, F.FOLD_LINES.phone), 52);
  // Мусор в замерах (поле ещё не в документе) не даёт NaN и нулевой высоты строки.
  assert.equal(compactHeight({ lineHeight: NaN, padTop: NaN, padBottom: 0, minHeight: 52 }, 2), 52);
  assert.equal(compactHeight(TOUCH, 0), 52);
});

/** Текст в lines строк в поле box (extra — лишние пиксели: строка с чипом чуть выше обычной). */
const text = (box, lines, extra = 0) => ({ ...box, content: textHeight(box, lines) + extra });

test("что помещается — не сворачивается; что на строку длиннее — сворачивается", () => {
  const wide = compactHeight(MOUSE, 2);
  assert.equal(foldNeeded(false, text(MOUSE, 1), wide), false);
  assert.equal(foldNeeded(false, text(MOUSE, 2), wide), false);
  assert.equal(foldNeeded(false, text(MOUSE, 3), wide), true);
  // Планшет с пальцем: шрифт 16 px, две строки.
  const tablet = compactHeight(TOUCH, 2);
  assert.equal(foldNeeded(false, text(TOUCH, 2), tablet), false);
  assert.equal(foldNeeded(false, text(TOUCH, 3), tablet), true);
});

test("телефон: запрос в две строки не сворачивается — свёрнутое поле и так показывает почти обе", () => {
  const phone = compactHeight(TOUCH, 1);
  assert.equal(foldNeeded(false, text(TOUCH, 1), phone), false);
  // 64 px против 52: выигрыш 12 px, а человек получил бы кнопку и рывок при каждом фокусе.
  assert.equal(foldNeeded(false, text(TOUCH, 2), phone), false);
  assert.equal(foldNeeded(false, text(TOUCH, 3), phone), true);
  // И обратно: из трёх строк стёрли одну — сворачивать больше нечего.
  assert.equal(foldNeeded(true, text(TOUCH, 2), phone), false);
});

test("у границы ответ не мигает: включается с запасом, выключается ниже", () => {
  const h = 61;
  const line = MOUSE.lineHeight;
  const at = (content) => ({ content, lineHeight: line });
  const enter = h + line * F.FOLD_ENTER_LINES;
  const exit = h + line * F.FOLD_EXIT_LINES;
  assert.equal(foldNeeded(false, at(enter), h), false);
  assert.equal(foldNeeded(false, at(enter + 0.5), h), true);
  // Между порогами держится прошлое решение — в обе стороны.
  const between = (enter + exit) / 2;
  assert.equal(foldNeeded(false, at(between), h), false);
  assert.equal(foldNeeded(true, at(between), h), true);
  assert.equal(foldNeeded(true, at(exit), h), false);
  // Строки с чипами выше на пару пикселей каждая — две строки всё ещё «помещаются», три всё ещё нет.
  assert.equal(foldNeeded(false, text(MOUSE, 2, 8), h), false);
  assert.equal(foldNeeded(true, text(MOUSE, 2, 8), h), false);
  assert.equal(foldNeeded(false, text(MOUSE, 3, -4), h), true);
  assert.ok(0 < F.FOLD_EXIT_LINES && F.FOLD_EXIT_LINES < F.FOLD_ENTER_LINES && F.FOLD_ENTER_LINES < 1);
});

test("нет замера — сворачивать нечего", () => {
  assert.equal(foldNeeded(true, { content: 500, lineHeight: 24 }, 0), false);
  assert.equal(foldNeeded(true, { content: NaN, lineHeight: 24 }, 61), false);
  assert.equal(foldNeeded(true, { content: 500, lineHeight: 0 }, 61), false);
  assert.equal(foldNeeded(true, { content: 500, lineHeight: NaN }, 61), false);
});
