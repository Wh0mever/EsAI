// Баннер «незавершённая оплата по QR»: слежение за счётом (lib/qrBannerWatch.ts).
// Первый ответ статуса обычно устаревший (сервер только ставит перепроверку у
// GoPay в очередь) — если на нём остановиться, только что оплативший видит
// «незавершённая оплата» и платит второй раз.
// Запуск (Node 22.6+):  node --experimental-strip-types --test src/lib/qrBannerWatch.test.mjs
import "./vstudio/nodeTsHooks.mjs";
import { test } from "node:test";
import assert from "node:assert/strict";

const W = await import("./qrBannerWatch.ts");

const ORDER = "tokpkg-7-3-0a1b2c3d4e";
const T0 = Date.parse("2026-10-06T10:00:00+00:00");
/** Счёт создан в T0 и живёт 15 минут. */
const DEADLINE = T0 + 15 * 60_000;

/** Ответ адреса статуса на текущий момент часов теста. */
function answer(h, uiState, extra = {}) {
  return {
    ok: true,
    status: 200,
    data: {
      kind: "qr",
      provider: "gopay",
      order_id: ORDER,
      status: uiState === "awaiting_payment" ? "created" : uiState,
      ui_state: uiState,
      amount: "392.00",
      currency: "KGS",
      package: { id: 3, name: "Про", tokens: 500, bonus_tokens: 0 },
      credits: { total: 500, credited: uiState === "paid" ? 500 : 0 },
      qr: { data: "https://pay.example#0002", image_url: "" },
      apps: [],
      checkout_url: "https://pay.example/p/1/",
      // Срок — по часам сервера; часы сервера = часы теста + расхождение.
      expires_at: new Date(DEADLINE + h.skew).toISOString(),
      server_time: new Date(h.now + h.skew).toISOString(),
      seconds_left: 0,
      lifetime_seconds: 900,
      ...extra,
    },
  };
}

/** Ручные часы и таймеры: тест сам решает, когда «прошло» время. */
function harness({ hidden = false, skew = 0 } = {}) {
  const h = {
    now: T0 + 60_000,
    skew,
    hidden,
    timers: [],
    seq: 0,
    calls: [],
    replies: [],
    updates: [],
    opened: [],
    closed: [],
  };
  h.deps = {
    now: () => h.now,
    hidden: () => h.hidden,
    timers: {
      set: (fn, ms) => {
        const id = ++h.seq;
        h.timers.push({ id, fn, ms });
        return id;
      },
      clear: (id) => {
        h.timers = h.timers.filter((t) => t.id !== id);
      },
    },
    fetch: (orderId) => {
      h.calls.push(orderId);
      const next = h.replies.shift();
      if (next === undefined) throw new Error("тест не подготовил ответ");
      if (next === "throw") return Promise.reject(new Error("network"));
      return Promise.resolve(typeof next === "function" ? next() : next);
    },
    onUpdate: (invoice, skewMs) => h.updates.push({ invoice, skewMs }),
    onOpen: (invoice) => h.opened.push(invoice),
    onClosed: (orderId) => h.closed.push(orderId),
  };
  /** Дать отработать ответам «в полёте». */
  h.flush = async () => {
    for (let i = 0; i < 5; i++) await Promise.resolve();
  };
  /** Сработал единственный таймер: время ушло вперёд на его паузу. */
  h.fire = async () => {
    assert.equal(h.timers.length, 1, "ожидался ровно один таймер");
    const [t] = h.timers;
    h.timers = [];
    h.now += t.ms;
    t.fn();
    await h.flush();
    return t.ms;
  };
  /** Ответ «ждёт оплаты», уже полученный useQrReturn. */
  h.seed = () => ({ invoice: answer(h, "awaiting_payment").data, skewMs: h.skew });
  return h;
}

/* ------------------------------------------------------------------ */

test("bannerVerdict: оплачен — открыть, ждёт — следить, закрыт — убрать", () => {
  const deadline = 1_000_000;
  assert.equal(W.bannerVerdict("paid", deadline, deadline - 5000), "open");
  assert.equal(W.bannerVerdict("processing", deadline, deadline - 5000), "open");
  assert.equal(W.bannerVerdict("awaiting_payment", deadline, deadline - 5000), "keep");
  assert.equal(W.bannerVerdict("cancelled", deadline, deadline - 5000), "drop");
  assert.equal(W.bannerVerdict("failed", deadline, deadline - 5000), "drop");
  // Истёкший досматриваем минуту: оплата могла уйти на последней секунде.
  assert.equal(W.bannerVerdict("expired", deadline, deadline + 30_000), "keep");
  assert.equal(W.bannerVerdict("expired", deadline, deadline + 60_001), "drop");
  assert.equal(W.bannerVerdict("expired", NaN, deadline), "drop");
});

test("bannerPollDelayMs: первый повтор через 4 с, дальше 7 с, сбои удлиняют паузу", () => {
  const deadline = 1_000_000;
  const now = deadline - 600_000;
  assert.equal(W.bannerPollDelayMs(1, 0, deadline, now), 4000);
  assert.equal(W.bannerPollDelayMs(2, 0, deadline, now), 7000);
  assert.equal(W.bannerPollDelayMs(9, 0, deadline, now), 7000);
  assert.equal(W.bannerPollDelayMs(0, 1, deadline, now), 8000);
  assert.equal(W.bannerPollDelayMs(2, 1, deadline, now), 14000);
  assert.equal(W.bannerPollDelayMs(2, 3, deadline, now), 30000);
  // Шесть сбоев подряд — молчим до возврата на вкладку.
  assert.equal(W.bannerPollDelayMs(2, 6, deadline, now), null);
  // Минута после срока прошла — по расписанию больше не спрашиваем.
  assert.equal(W.bannerPollDelayMs(2, 0, deadline, deadline + 60_000), 7000);
  assert.equal(W.bannerPollDelayMs(2, 0, deadline, deadline + 60_001), null);
  // Срок неизвестен — спрашиваем дальше.
  assert.equal(W.bannerPollDelayMs(2, 0, NaN, now), 7000);
});

test("регрессия: первое «ждёт оплаты» не окончательно — спрашиваем снова и ловим оплату", async () => {
  // Сценарий: оплатил в банке, вкладку перезагрузило. Первый GET статуса
  // (useQrReturn) вернул «ждёт» и лишь поставил перепроверку у GoPay.
  const h = harness();
  const watch = W.createQrBannerWatch(ORDER, h.deps, h.seed());
  // Сразу не спрашиваем: ответ только что был. Повтор — через ~4 с.
  assert.deepEqual(h.calls, []);
  assert.equal(watch.inspect().scheduled, 4000);

  h.replies.push(() => answer(h, "paid"));
  assert.equal(await h.fire(), 4000);
  assert.deepEqual(h.calls, [ORDER]);
  assert.equal(h.opened.length, 1);
  assert.equal(h.opened[0].order_id, ORDER);
  assert.equal(h.opened[0].ui_state, "paid");
  assert.deepEqual(h.closed, []);
  // Дело сделано: таймеров нет, возврат на вкладку ничего не запускает.
  assert.equal(h.timers.length, 0);
  assert.equal(watch.inspect().done, true);
  watch.wake();
  await h.flush();
  assert.deepEqual(h.calls, [ORDER]);
});

test("баннер с сервера (подсказки нет): спрашиваем сразу и продолжаем, пока счёт ждёт", async () => {
  const h = harness();
  h.replies.push(() => answer(h, "awaiting_payment"));
  const watch = W.createQrBannerWatch(ORDER, h.deps);
  await h.flush();
  assert.deepEqual(h.calls, [ORDER]);
  assert.equal(h.updates.length, 1);
  assert.equal(watch.inspect().scheduled, 4000);

  h.replies.push(() => answer(h, "awaiting_payment"));
  await h.fire();
  assert.equal(watch.inspect().scheduled, 7000);

  // «Зачисляем» — тоже повод открыть экран: деньги уже пришли.
  h.replies.push(() => answer(h, "processing"));
  assert.equal(await h.fire(), 7000);
  assert.equal(h.calls.length, 3);
  assert.equal(h.opened.length, 1);
  assert.equal(h.opened[0].ui_state, "processing");
  assert.equal(h.updates.length, 2);
});

test("закрыт без оплаты или счёта нет — баннер убираем и замолкаем", async () => {
  for (const reply of [
    (h) => answer(h, "cancelled"),
    (h) => answer(h, "failed"),
    () => ({ ok: false, status: 404 }),
  ]) {
    const h = harness();
    const watch = W.createQrBannerWatch(ORDER, h.deps, h.seed());
    h.replies.push(() => reply(h));
    await h.fire();
    assert.deepEqual(h.closed, [ORDER]);
    assert.deepEqual(h.opened, []);
    assert.equal(h.timers.length, 0);
    assert.equal(watch.inspect().done, true);
  }
});

test("сессии нет (401/403): молчим и баннер не трогаем", async () => {
  for (const status of [401, 403]) {
    const h = harness();
    const watch = W.createQrBannerWatch(ORDER, h.deps, h.seed());
    h.replies.push({ ok: false, status });
    await h.fire();
    assert.deepEqual(h.closed, []);
    assert.deepEqual(h.opened, []);
    assert.equal(watch.inspect().done, true);
    assert.equal(h.timers.length, 0);
  }
});

test("сбои сети: отступ, потом тишина до возврата на вкладку", async () => {
  const h = harness();
  const watch = W.createQrBannerWatch(ORDER, h.deps, h.seed());
  const delays = [];
  for (let i = 0; i < 6; i++) {
    h.replies.push(i % 2 ? "throw" : { ok: false, status: 502 });
    delays.push(await h.fire());
  }
  assert.deepEqual(delays, [4000, 8000, 16000, 30000, 30000, 30000]);
  assert.equal(watch.inspect().failures, 6);
  assert.equal(h.timers.length, 0);
  assert.deepEqual(h.closed, []);
  assert.equal(watch.inspect().done, false);

  // Человек вернулся на вкладку — пробуем снова, и оплата находится.
  h.replies.push(() => answer(h, "paid"));
  watch.wake();
  await h.flush();
  assert.equal(h.opened.length, 1);
});

test("скрытая вкладка не опрашивает; возврат из банка — запрос сразу", async () => {
  const h = harness();
  const watch = W.createQrBannerWatch(ORDER, h.deps, h.seed());
  h.hidden = true;
  await h.fire();
  assert.deepEqual(h.calls, []);
  assert.equal(h.timers.length, 0);
  // Пока скрыта — wake ничего не делает.
  watch.wake();
  await h.flush();
  assert.deepEqual(h.calls, []);

  h.hidden = false;
  h.replies.push(() => answer(h, "paid"));
  watch.wake();
  await h.flush();
  assert.deepEqual(h.calls, [ORDER]);
  assert.equal(h.opened.length, 1);
});

test("страница открылась скрытой: первый запрос ждёт возврата", async () => {
  const h = harness({ hidden: true });
  const watch = W.createQrBannerWatch(ORDER, h.deps);
  await h.flush();
  assert.deepEqual(h.calls, []);
  h.hidden = false;
  h.replies.push(() => answer(h, "awaiting_payment"));
  watch.wake();
  await h.flush();
  assert.deepEqual(h.calls, [ORDER]);
  assert.equal(watch.inspect().scheduled, 4000);
});

test("один запрос за раз и ничего после stop()", async () => {
  const h = harness();
  let release;
  h.replies.push(() => new Promise((resolve) => (release = resolve)));
  const watch = W.createQrBannerWatch(ORDER, h.deps);
  await h.flush();
  assert.equal(watch.inspect().inFlight, true);
  // Возврат на вкладку во время запроса второй запрос не плодит.
  watch.wake();
  await h.flush();
  assert.equal(h.calls.length, 1);

  watch.stop();
  release(answer(h, "paid"));
  await h.flush();
  // Баннер уже убран — ответ в полёте никого не открывает.
  assert.deepEqual(h.opened, []);
  assert.equal(h.timers.length, 0);
});

test("подсказка о другом заказе ответом не считается — спрашиваем сразу", async () => {
  const h = harness();
  const foreign = h.seed();
  foreign.invoice = { ...foreign.invoice, order_id: "tokpkg-7-3-ffffffffff" };
  h.replies.push(() => answer(h, "awaiting_payment"));
  W.createQrBannerWatch(ORDER, h.deps, foreign);
  await h.flush();
  assert.deepEqual(h.calls, [ORDER]);
});

test("баннеру отдаём срок и поправку на часы сервера", async () => {
  // Часы телефона спешат на 4 минуты: сервер «позади» на 240 с.
  const h = harness({ skew: -240_000 });
  h.replies.push(() => answer(h, "awaiting_payment"));
  W.createQrBannerWatch(ORDER, h.deps);
  await h.flush();
  assert.equal(h.updates.length, 1);
  assert.equal(h.updates[0].skewMs, -240_000);
  assert.equal(h.updates[0].invoice.expires_at, new Date(DEADLINE - 240_000).toISOString());
});

test("после срока досматриваем минуту, потом убираем баннер", async () => {
  // Часы телефона врут — «минута после срока» всё равно считается верно.
  const h = harness({ skew: 90_000 });
  const watch = W.createQrBannerWatch(ORDER, h.deps, h.seed());
  // Перематываем к сроку счёта: таймер сработает ровно в срок.
  h.now = DEADLINE - 4000;
  h.replies.push(() => answer(h, "expired"));
  await h.fire();
  assert.deepEqual(h.closed, []);
  // Истёкший счёт баннеру не показываем.
  assert.equal(h.updates.length, 0);
  let polls = 1;
  while (h.timers.length) {
    h.replies.push(() => answer(h, "expired"));
    await h.fire();
    polls += 1;
    assert.ok(polls < 20, "опрос должен закончиться");
  }
  assert.deepEqual(h.closed, [ORDER]);
  assert.ok(h.now - DEADLINE > 60_000);
  assert.ok(h.now - DEADLINE < 75_000);
  assert.equal(watch.inspect().done, true);
});

test("оплата на последней секунде: «истёк», а следом «оплачен» — экран открываем", async () => {
  const h = harness();
  W.createQrBannerWatch(ORDER, h.deps, h.seed());
  h.now = DEADLINE + 1000;
  h.replies.push(() => answer(h, "expired"));
  await h.fire();
  h.replies.push(() => answer(h, "paid"));
  await h.fire();
  assert.equal(h.opened.length, 1);
  assert.deepEqual(h.closed, []);
});
