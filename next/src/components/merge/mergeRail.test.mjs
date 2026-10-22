// «Мои склейки»: строка склейки и отказ удаления под ней (MergeRail.tsx). Разметку проверяем по
// дереву TSX (компилятор TypeScript проекта), геометрию — по классам Tailwind (шаг 4 px).
// Запуск (Node 22.6+):  node --experimental-strip-types --test src/components/merge/*.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import ts from "typescript";

const source = readFileSync(new URL("./MergeRail.tsx", import.meta.url), "utf8");
const file = ts.createSourceFile("MergeRail.tsx", source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);

function findAll(root, pred) {
  const out = [];
  const visit = (n) => {
    if (pred(n)) out.push(n);
    ts.forEachChild(n, visit);
  };
  visit(root);
  return out;
}

const isElement = (n) => ts.isJsxElement(n) || ts.isJsxSelfClosingElement(n);
const opening = (n) => (ts.isJsxElement(n) ? n.openingElement : n);
const tagOf = (n) => opening(n).tagName.getText(file);

function attr(n, name) {
  const a = opening(n).attributes.properties.find((p) => ts.isJsxAttribute(p) && p.name.getText(file) === name);
  if (!a) return undefined;
  if (!a.initializer) return true;
  return ts.isStringLiteral(a.initializer) ? a.initializer.text : a.initializer.getText(file);
}

/** Все классы элемента: строка или строки внутри vx(...) — условные тоже (худший случай). */
function classes(n) {
  const a = opening(n).attributes.properties.find((p) => ts.isJsxAttribute(p) && p.name.getText(file) === "className");
  if (!a || !a.initializer) return [];
  const texts = findAll(a.initializer, (x) => ts.isStringLiteral(x) || ts.isNoSubstitutionTemplateLiteral(x)).map((x) => x.text);
  return texts.join(" ").split(/\s+/).filter(Boolean);
}

/** Tailwind-отступ в px: «pt-0.5» → 2; нет класса — 0. */
function px(list, prefix) {
  const re = new RegExp(`^${prefix.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}(\\d+(?:\\.\\d+)?)$`);
  const hit = list.map((c) => c.match(re)).find(Boolean);
  return hit ? Number(hit[1]) * 4 : 0;
}

function parentElement(n) {
  let p = n.parent;
  while (p && !isElement(p)) p = p.parent;
  return p;
}

const inside = (outer, inner) => inner.pos >= outer.pos && inner.end <= outer.end;

const item = findAll(file, (n) => ts.isFunctionDeclaration(n) && n.name?.text === "MergeItem")[0];
assert.ok(item, "MergeItem в MergeRail.tsx");
const elements = findAll(item, isElement);
const one = (pred, what) => {
  const found = elements.filter(pred);
  assert.equal(found.length, 1, what);
  return found[0];
};
const li = one((n) => tagOf(n) === "li", "<li> строки");
const link = one((n) => tagOf(n) === "a", "<a> строки");
const dots = one((n) => attr(n, "aria-haspopup") === "menu", "кнопка ⋯");
const menu = one((n) => attr(n, "role") === "menu", "меню");
const alert = one((n) => attr(n, "role") === "alert", "отказ удаления");
const close = one((n) => tagOf(n) === "button" && inside(alert, n), "✕ отказа");

test("⋯ и меню привязаны к строке, а не ко всему пункту: отказ ниже их не сдвигает (MA_FIX5, V4 frontend W1)", () => {
  const row = parentElement(dots);
  assert.equal(tagOf(row), "div", "у ⋯ своя обёртка строки");
  assert.ok(classes(row).includes("relative"), "обёртка — точка отсчёта для top-1/2 и top-full");
  assert.equal(parentElement(row), li, "обёртка — прямо в пункте списка");
  assert.equal(parentElement(menu), row, "меню — в той же обёртке");
  assert.equal(parentElement(link), row, "ссылка строки — в той же обёртке");
  assert.ok(classes(dots).includes("top-1/2") && classes(menu).includes("top-full"));
  // Отказ — после строки и вне её обёртки: растёт пункт, а не строка.
  assert.ok(!inside(row, alert), "отказ не внутри строки");
  assert.equal(parentElement(alert), li);
  assert.ok(alert.pos >= row.end, "отказ под строкой");
  assert.ok(!classes(li).includes("relative"), "пункт — не точка отсчёта для ⋯");
});

test("зона нажатия ✕ — 44 px и не заходит на строку с ⋯ (MA_FIX5, V4 frontend W1)", () => {
  const box = classes(alert);
  const btn = classes(close);
  const inset = px(btn, "before:-inset-");
  const size = px(btn, "size-");
  assert.ok(size + 2 * inset >= 44, `✕: ${size} + 2×${inset} ≥ 44`);
  // Верх зоны от верха блока отказа (он сразу под строкой): не выше нуля — значит, не на ⋯.
  const top = px(box, "pt-") + px(btn, "mt-") - inset;
  assert.ok(top >= 0, `верх зоны ✕: ${top} px от низа строки`);
  // Низ зоны — внутри блока: нижний отступ не меньше запаса зоны.
  assert.ok(px(box, "pb-") >= inset, "нижний отступ вмещает зону ✕");
  // И ⋯ не выходит за строку: его зона не выше минимальной высоты строки.
  const dotsZone = px(classes(dots), "size-") + 2 * px(classes(dots), "before:-inset-");
  assert.ok(dotsZone <= px(classes(link), "min-h-"), `⋯: ${dotsZone} px в строке ≥ ${px(classes(link), "min-h-")} px`);
});
