// Видеостудия, композер: строка баланса в раскладке цены (composer/priceText.ts) —
// какой текст выбирается с резервом и без, и что числа в строке сходятся на глаз.
// Запуск (Node 22.6+):  node --experimental-strip-types --test src/components/vstudio/composer/priceText.test.mjs
import "../../../lib/vstudio/nodeTsHooks.mjs";
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const P = await import("./priceText.ts");
const T = await import("./composerText.ts");
const { fmtNum } = await import("./composerLogic.ts");

const { balanceLines } = P;

/** Строки так, как их складывает PriceBreakdown: [первая, тихая, «не хватает»]. */
function shown(balance, credits) {
  const b = balanceLines(balance, credits);
  if (!b) return null;
  const say = (line) => T.ruText(line.key, Object.fromEntries(Object.entries(line.params).map(([k, v]) => [k, fmtNum(v)])));
  // Пробел тысяч у ru-RU неразрывный — в ожидаемых строках пишем обычный.
  const plain = (s) => s.replace(/[  ]/g, " ");
  return [
    plain(say(b.head) + (b.after ? ` → ${say(b.after)}` : "")),
    b.held ? plain(say(b.held)) : null,
    b.missing > 0 ? plain(T.ruText("price.missing", { n: fmtNum(b.missing) })) : null,
  ];
}

test("гость: баланса в ответе нет — строки нет", () => {
  assert.equal(balanceLines(null, 164), null);
  assert.equal(balanceLines(undefined, 164), null);
});

test("резерва нет — строка прежняя: «На балансе … → останется …»", () => {
  const b = { balance: 1200, reserved: 0, available: 1200, after: 1036 };
  assert.deepEqual(balanceLines(b, 164), {
    head: { key: "price.balance", params: { balance: 1200 } },
    after: { key: "price.after", params: { after: 1036 } },
    held: null,
    missing: 0,
  });
  assert.deepEqual(shown(b, 164), ["На балансе 1 200 кр → останется 1 036 кр", null, null]);
});

test("случай клиента: 987 992 на балансе, 390 держит идущая генерация, запуск за 390", () => {
  const b = { balance: 987992, reserved: 390, available: 987602, after: 987212 };
  const lines = balanceLines(b, 390);
  assert.equal(lines.head.key, "price.available");
  assert.equal(lines.held.key, "price.held");
  assert.deepEqual(shown(b, 390), [
    "Свободно 987 602 кр → останется 987 212 кр",
    "Ещё 390 кр в резерве, пока идёт генерация. Всего на балансе 987 992 кр.",
    null,
  ]);
  // В первой строке — ровно те два числа, между которыми стоит цена из «Итого».
  assert.equal(lines.head.params.available - 390, lines.after.params.after);
  // Весь баланс больше не стоит рядом со стрелкой: его называет только тихая строка.
  assert.ok(!shown(b, 390)[0].includes("987 992"));
});

test("не хватает кредитов: «останется» нет, сколько не хватает — отдельной строкой", () => {
  // Сервер шлёт after = available − цена, при нехватке оно отрицательное.
  assert.deepEqual(shown({ balance: 100, reserved: 0, available: 100, after: -64 }, 164), ["На балансе 100 кр", null, "Не хватает 64 кр"]);
  assert.deepEqual(shown({ balance: 500, reserved: 390, available: 110, after: -54 }, 164), [
    "Свободно 110 кр",
    "Ещё 390 кр в резерве, пока идёт генерация. Всего на балансе 500 кр.",
    "Не хватает 54 кр",
  ]);
  // Дробная нехватка округляется вверх — столько и надо докупить.
  assert.equal(balanceLines({ balance: 10, reserved: 0, available: 10.4, after: null }, 12).missing, 2);
});

test("остатка в ответе нет (запуск без quote) или цена не посчитана — без стрелки", () => {
  assert.deepEqual(shown({ balance: 1200, reserved: 0, available: 1200 }, 164), ["На балансе 1 200 кр", null, null]);
  assert.deepEqual(shown({ balance: 1200, reserved: 0, available: 1200, after: null }, null), ["На балансе 1 200 кр", null, null]);
  assert.deepEqual(shown({ balance: 1200, reserved: 120, available: 1080, after: null }, null), [
    "Свободно 1 080 кр",
    "Ещё 120 кр в резерве, пока идёт генерация. Всего на балансе 1 200 кр.",
    null,
  ]);
});

test("ровно хватает: останется 0 — показываем, это не нехватка", () => {
  assert.deepEqual(shown({ balance: 164, reserved: 0, available: 164, after: 0 }, 164), ["На балансе 164 кр → останется 0 кр", null, null]);
});

test("мусор вместо резерва не включает строку про резерв", () => {
  const lines = balanceLines({ balance: 300, reserved: -5, available: 300, after: 136 }, 164);
  assert.equal(lines.head.key, "price.balance");
  assert.equal(lines.held, null);
});

test("«Повторить» в ленте: без резерва — только остаток, при резерве — ещё и свободная сумма перед ним", () => {
  const { retryBalance } = P;
  // Баланс в верхней строке 1 200, повтор за 164: 1 200 − 164 = 1 036 — сходится само.
  assert.deepEqual(retryBalance({ balance: 1200, reserved: 0, available: 1200, after: 1036 }, 164), { free: null, after: 1036 });
  // Идёт другая генерация: 987 992 − 390 ≠ 987 212, поэтому называем 987 602.
  const held = retryBalance({ balance: 987992, reserved: 390, available: 987602, after: 987212 }, 390);
  assert.deepEqual(held, { free: 987602, after: 987212 });
  assert.equal(held.free - 390, held.after);
  // Не хватает — строки нет: рядом кнопка «Пополнить · не хватает N кр».
  assert.equal(retryBalance({ balance: 500, reserved: 390, available: 110, after: -54 }, 164), null);
  assert.equal(retryBalance({ balance: 100, reserved: 0, available: 100, after: 0 }, 164), null);
  // Остатка в ответе нет, баланса нет (гость), цена не посчитана.
  assert.equal(retryBalance({ balance: 1200, reserved: 0, available: 1200, after: null }, 164), null);
  assert.equal(retryBalance(null, 164), null);
  assert.deepEqual(retryBalance({ balance: 1200, reserved: 0, available: 1200, after: 1200 }, null), { free: null, after: 1200 });
});

test("тексты строки баланса есть на трёх языках, а старая «из них … ждут результата» убрана", () => {
  const root = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..", "locales");
  for (const lang of ["ru", "en", "kg"]) {
    const price = JSON.parse(readFileSync(join(root, lang, "vstudio.json"), "utf8")).price;
    for (const key of ["balance", "available", "held", "after", "missing"]) {
      assert.equal(typeof price[key], "string", `${lang}: price.${key}`);
    }
    assert.ok(price.available.includes("{{available}}"), lang);
    assert.ok(price.held.includes("{{reserved}}") && price.held.includes("{{balance}}"), lang);
    assert.equal(price.reserved, undefined, `${lang}: price.reserved`);
    // Русский текст в коде — тот же, что в файле перевода: иначе до загрузки переводов строка была бы другой.
    if (lang === "ru") for (const key of ["balance", "available", "held", "after", "missing"]) assert.equal(price[key], T.COMPOSER_RU[`price.${key}`], key);
  }
  assert.equal(T.COMPOSER_RU["price.reserved"], undefined);
});

test("строка про резерв не говорит, сколько генераций идёт: сумма в ней — по всем сразу", () => {
  // Идут ролик за 390 и картинка за 14: «404 кр держит генерация, которая сейчас идёт» прочли бы
  // как цену одной генерации — а на её карточке 390.
  const b = { balance: 1000, reserved: 404, available: 596, after: 206 };
  assert.deepEqual(shown(b, 390).slice(0, 2), [
    "Свободно 596 кр → останется 206 кр",
    "Ещё 404 кр в резерве, пока идёт генерация. Всего на балансе 1 000 кр.",
  ]);
  const root = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..", "locales");
  const held = (lang) => JSON.parse(readFileSync(join(root, lang, "vstudio.json"), "utf8")).price.held;
  assert.ok(!/которая|держит генерация/.test(held("ru")), held("ru"));
  assert.ok(!/\ba generation\b|that's still/i.test(held("en")), held("en"));
  assert.ok(!/жаткан генерацияда/.test(held("kg")), held("kg"));
});
