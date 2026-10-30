// Нижний блок бокового меню (sidebarFoot.ts): что показать при открытии.
// Запуск (Node 22.6+):  node --experimental-strip-types --test src/components/ui/sidebarFoot.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";

const { footOpenFrom, footValue, SIDEBAR_FOOT_KEY } = await import("./sidebarFoot.ts");

test("ключ хранилища — тот, что в задании", () => {
  assert.equal(SIDEBAR_FOOT_KEY, "esai-sidebar-foot");
});

test("без выбора: телефон свёрнут, компьютер развёрнут, граница — 768 px", () => {
  for (const width of [320, 390, 767]) assert.equal(footOpenFrom(null, width), false, String(width));
  for (const width of [768, 1024, 1920]) assert.equal(footOpenFrom(null, width), true, String(width));
});

test("выбор человека важнее ширины и переживает запись и чтение", () => {
  assert.equal(footOpenFrom(footValue(true), 390), true);
  assert.equal(footOpenFrom(footValue(false), 1920), false);
});

test("мусор в хранилище — как будто выбора не было", () => {
  for (const saved of ["", "1", "true", "OPEN", "{}"]) {
    assert.equal(footOpenFrom(saved, 390), false, saved);
    assert.equal(footOpenFrom(saved, 1920), true, saved);
  }
});
