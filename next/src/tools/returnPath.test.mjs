// Регрессия открытого редиректа через ?next= (tools/returnPath.ts).
// Запуск (Node 22.6+):  node --experimental-strip-types --test src/tools/returnPath.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { safeReturnPath } from "./returnPath.ts";

// За nginx middleware видит внутренний адрес — проверяем и его.
const BASES = ["https://esai.kg/auth/signin?next=x", "http://localhost:3000/auth/signin"];

test("свои пути проходят и нормализуются", () => {
  for (const base of BASES) {
    assert.equal(safeReturnPath("/studio", base), "/studio");
    assert.equal(safeReturnPath("  /plans?tab=pro#top ", base), "/plans?tab=pro#top");
    assert.equal(safeReturnPath("/dashboard/../studio", base), "/studio");
  }
  assert.equal(safeReturnPath("/studio"), "/studio");
});

test("управляющие символы не дают уйти на чужой сайт", () => {
  // «/\t/evil.example»: new URL() выкидывает \t и получает //evil.example.
  const evil = ["/\t/evil.example", "/\n/evil.example", "/\r/evil.example", "/\u0000/evil.example", "/\u007f/evil.example"];
  for (const base of BASES) {
    for (const v of evil) assert.equal(safeReturnPath(v, base), null, JSON.stringify(v));
  }
  for (const v of evil) assert.equal(safeReturnPath(v), null, JSON.stringify(v));
});

test("чужие и кривые адреса отбрасываются", () => {
  const bad = [
    "//evil.example",
    "/\\evil.example",
    "\\\\evil.example",
    "https://evil.example/",
    "javascript:alert(1)",
    "evil.example",
    "",
    "/" + "a".repeat(300),
    null,
    undefined,
    42,
  ];
  for (const base of BASES) {
    for (const v of bad) assert.equal(safeReturnPath(v, base), null, String(v));
  }
});

test("возврат на вход (петля) отбрасывается и после нормализации", () => {
  for (const v of ["/auth/signin", "/./auth/signin", "/x/../auth/signup?next=/studio"]) {
    assert.equal(safeReturnPath(v), null, v);
  }
});
