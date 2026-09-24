// Опрос открытых дублей (feed/takePoller.ts): расписание §9.4 без браузера.
// Запуск (Node 22.6+):  node --experimental-strip-types --test src/components/vstudio/feed/*.test.mjs
import "../../../lib/vstudio/nodeTsHooks.mjs";
import { test } from "node:test";
import assert from "node:assert/strict";

const P = await import("./takePoller.ts");

const U = (n) => n.toString(16).padStart(32, "0");

function take(n, status = "running") {
  return {
    uid: U(n),
    shot: U(0x500),
    kind: "video",
    status,
    stage: "",
    mode: "t2v",
    charge_state: status === "done" ? "charged" : ["failed", "lost", "canceled"].includes(status) ? "released" : "reserved",
    credits: { quoted: 10, reserved: 10, charged: status === "done" ? 10 : 0 },
    effective: {},
    warnings: [],
    dropped: [],
    result: null,
    error: null,
    eta_s: 60,
    elapsed_s: 5,
    queue_position: null,
    created_at: "2026-09-24T10:00:00Z",
    submitted_at: null,
    finished_at: null,
  };
}

/** Ручные часы и таймеры: тест сам решает, когда «прошло» время. */
function harness({ hidden = false } = {}) {
  const h = {
    now: 1_000_000,
    hidden,
    timers: [],
    seq: 0,
    calls: [],
    replies: [],
    items: [],
    errors: [],
    gone: [],
    store: new Map(),
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
    poll: async (uids) => {
      h.calls.push([...uids]);
      const r = h.replies.shift();
      if (typeof r === "function") return r(uids);
      return r ?? { ok: true, status: 200, data: { items: [] } };
    },
    known: (uid) => h.store.get(uid),
    onItems: (items, settled) => {
      h.items.push({ items, settled });
      for (const t of items) h.store.set(t.uid, t);
    },
    onError: (e) => h.errors.push(e.code),
    onGone: (uids) => h.gone.push(...uids),
  };
  /** Выполнить ближайший таймер и дождаться ответа «сервера». */
  h.fire = async (advanceMs) => {
    const t = h.timers.shift();
    assert.ok(t, "ожидался запланированный опрос");
    if (advanceMs !== undefined) h.now += advanceMs;
    else h.now += t.ms;
    t.fn();
    await new Promise((r) => setImmediate(r));
    return t.ms;
  };
  return h;
}

const ok = (items) => ({ ok: true, status: 200, data: { items } });
const fail = (code, status = 0) => ({ ok: false, status, error: { status, code, message: "", data: {} } });

test("pollDelay: 3 с для свежих, 6 с после 2 минут, отступ после ошибок, 15 с на 429", () => {
  const now = 1_000_000;
  assert.equal(P.pollDelay({ now, firstSeen: [now - 10_000], failures: 0, lastCode: null }), 3000);
  assert.equal(P.pollDelay({ now, firstSeen: [now - 121_000], failures: 0, lastCode: null }), 6000);
  // Один свежий среди старых — снова часто.
  assert.equal(P.pollDelay({ now, firstSeen: [now - 500_000, now - 1000], failures: 0, lastCode: null }), 3000);
  assert.equal(P.pollDelay({ now, firstSeen: [now], failures: 1, lastCode: "network" }), 6000);
  assert.equal(P.pollDelay({ now, firstSeen: [now], failures: 2, lastCode: "network" }), 12000);
  assert.equal(P.pollDelay({ now, firstSeen: [now], failures: 9, lastCode: "server_error" }), 30000);
  assert.equal(P.pollDelay({ now, firstSeen: [now], failures: 1, lastCode: "throttled" }), 15000);
});

test("settledFrom: только закрывшиеся этим ответом", () => {
  const store = new Map([
    [U(1), take(1, "running")],
    [U(2), take(2, "canceled")],
  ]);
  const got = P.settledFrom([take(1, "done"), take(2, "canceled"), take(3, "running"), take(4, "failed")], (u) =>
    store.get(u),
  );
  assert.deepEqual(
    got.map((s) => [s.take.uid, s.prev?.status ?? null]),
    [
      [U(1), "running"],
      [U(4), null],
    ],
  );
});

test("нет открытых — нет таймеров; появились — опрос через 3 с", async () => {
  const h = harness();
  const p = P.createTakePoller(h.deps);
  p.setOpen([]);
  assert.equal(h.timers.length, 0);
  p.setOpen([U(1), U(1)]);
  assert.equal(h.timers.length, 1);
  assert.equal(h.timers[0].ms, 3000);
  h.store.set(U(1), take(1, "running"));
  h.replies.push(ok([take(1, "running")]));
  await h.fire();
  assert.deepEqual(h.calls, [[U(1)]]);
  // Следующий тик запланирован сам.
  assert.equal(h.timers.length, 1);
  assert.equal(h.timers[0].ms, 3000);
  p.stop();
  assert.equal(h.timers.length, 0);
});

test("через 2 минуты — каждые 6 с", async () => {
  const h = harness();
  const p = P.createTakePoller(h.deps);
  h.store.set(U(1), take(1));
  p.setOpen([U(1)]);
  h.replies.push(ok([take(1)]));
  await h.fire(121_000);
  assert.equal(h.timers[0].ms, 6000);
  p.stop();
});

test("закрылся — onItems с settled, дубль больше не спрашиваем, таймер гаснет", async () => {
  const h = harness();
  const p = P.createTakePoller(h.deps);
  h.store.set(U(1), take(1, "running"));
  h.store.set(U(2), take(2, "running"));
  p.setOpen([U(1), U(2)]);
  h.replies.push(ok([take(1, "done"), take(2, "running")]));
  await h.fire();
  assert.equal(h.items.length, 1);
  assert.deepEqual(
    h.items[0].settled.map((s) => s.take.uid),
    [U(1)],
  );
  h.replies.push(ok([take(2, "failed")]));
  await h.fire();
  assert.deepEqual(h.calls[1], [U(2)]);
  assert.deepEqual(h.items[1].settled.map((s) => s.take.uid), [U(2)]);
  // Открытых не осталось — опрос замер сам, даже до setOpen из стора.
  assert.equal(h.timers.length, 0);
  assert.deepEqual(p.inspect().active, []);
});

test("скрытая вкладка — пауза; wake() — сразу запрос", async () => {
  const h = harness({ hidden: true });
  const p = P.createTakePoller(h.deps);
  h.store.set(U(1), take(1));
  p.setOpen([U(1)]);
  await h.fire();
  assert.equal(h.calls.length, 0, "на скрытой вкладке не спрашиваем");
  assert.equal(h.timers.length, 0, "и не крутим таймер впустую");
  p.wake(); // всё ещё скрыта
  assert.equal(h.calls.length, 0);
  h.hidden = false;
  h.replies.push(ok([take(1)]));
  p.wake();
  await new Promise((r) => setImmediate(r));
  assert.equal(h.calls.length, 1);
  assert.equal(h.timers.length, 1);
  p.stop();
});

test("ошибки сети — отступ растёт; успех сбрасывает; 429 — 15 с", async () => {
  const h = harness();
  const p = P.createTakePoller(h.deps);
  h.store.set(U(1), take(1));
  p.setOpen([U(1)]);
  h.replies.push(fail("network"), fail("server_error", 502), ok([take(1)]), fail("throttled", 429));
  await h.fire();
  assert.equal(h.timers[0].ms, 6000);
  await h.fire();
  assert.equal(h.timers[0].ms, 12000);
  await h.fire();
  assert.equal(h.timers[0].ms, 3000);
  await h.fire();
  assert.equal(h.timers[0].ms, 15000);
  assert.deepEqual(h.errors, ["network", "server_error", "throttled"]);
  p.stop();
});

test("401 — пауза до нового дубля или wake()", async () => {
  const h = harness();
  const p = P.createTakePoller(h.deps);
  h.store.set(U(1), take(1));
  p.setOpen([U(1)]);
  h.replies.push(fail("unauthorized", 401));
  await h.fire();
  assert.equal(h.timers.length, 0);
  assert.equal(p.inspect().paused, true);
  // Тот же набор — пауза остаётся.
  p.setOpen([U(1)]);
  assert.equal(h.timers.length, 0);
  // Новый дубль (человек вошёл заново и запустил) — опрос снова идёт.
  p.setOpen([U(1), U(2)]);
  assert.equal(h.timers.length, 1);
  p.stop();
});

test("uid, которого сервер трижды не вернул, больше не спрашиваем", async () => {
  const h = harness();
  const p = P.createTakePoller(h.deps);
  h.store.set(U(1), take(1));
  h.store.set(U(9), take(9));
  p.setOpen([U(1), U(9)]);
  for (let i = 0; i < 3; i++) {
    h.replies.push(ok([take(1)]));
    await h.fire();
  }
  assert.deepEqual(h.gone, [U(9)]);
  h.replies.push(ok([take(1)]));
  await h.fire();
  assert.deepEqual(h.calls.at(-1), [U(1)]);
  p.stop();
});

test("один запрос за раз: wake() во время ответа — повтор сразу после", async () => {
  const h = harness();
  const p = P.createTakePoller(h.deps);
  h.store.set(U(1), take(1));
  p.setOpen([U(1)]);
  let release;
  h.replies.push(() => new Promise((r) => (release = () => r(ok([take(1)])))));
  const t = h.timers.shift();
  t.fn();
  await new Promise((r) => setImmediate(r));
  assert.equal(p.inspect().inFlight, true);
  p.wake();
  p.wake();
  assert.equal(h.calls.length, 1, "второй запрос не наслаивается");
  release();
  await new Promise((r) => setImmediate(r));
  // Отложенный wake: следующий опрос без ожидания.
  assert.equal(h.timers.length, 1);
  assert.equal(h.timers[0].ms, 0);
  p.stop();
});

test("stop() во время запроса: ответ выбрасывается", async () => {
  const h = harness();
  const p = P.createTakePoller(h.deps);
  h.store.set(U(1), take(1));
  p.setOpen([U(1)]);
  let release;
  h.replies.push(() => new Promise((r) => (release = () => r(ok([take(1, "done")])))));
  h.timers.shift().fn();
  await new Promise((r) => setImmediate(r));
  p.stop();
  release();
  await new Promise((r) => setImmediate(r));
  assert.equal(h.items.length, 0);
  assert.equal(h.timers.length, 0);
});

test("исключение в poll считается ошибкой сети", async () => {
  const h = harness();
  const p = P.createTakePoller(h.deps);
  h.store.set(U(1), take(1));
  p.setOpen([U(1)]);
  h.replies.push(() => {
    throw new Error("boom");
  });
  await h.fire();
  assert.deepEqual(h.errors, ["network"]);
  assert.equal(h.timers[0].ms, 6000);
  p.stop();
});

test("новый дубль при медленном ритме: первый ответ через 3 с, не через 6", async () => {
  const h = harness();
  const p = P.createTakePoller(h.deps);
  h.store.set(U(1), take(1));
  p.setOpen([U(1)]);
  h.replies.push(ok([take(1)]));
  await h.fire(121_000);
  assert.equal(h.timers[0].ms, 6000, "старый дубль — медленный ритм");
  // Через секунду нажали «Повторить»: тик переносится на 3 с от сейчас.
  h.now += 1000;
  p.setOpen([U(1), U(2)]);
  assert.equal(h.timers.length, 1);
  assert.equal(h.timers[0].ms, 3000);
  // Медленный тик и так скоро (через 1 с) — его не отодвигаем.
  h.replies.push(ok([take(1), take(2)]));
  await h.fire(121_000);
  assert.equal(h.timers[0].ms, 6000);
  h.now += 5000;
  p.setOpen([U(1), U(2), U(3)]);
  assert.equal(h.timers.length, 1);
  assert.equal(h.timers[0].ms, 6000, "до старого тика 1 с — не переносим");
  p.stop();
});

test("новый дубль во время отступа после ошибок: отступ не сокращаем", async () => {
  const h = harness();
  const p = P.createTakePoller(h.deps);
  h.store.set(U(1), take(1));
  p.setOpen([U(1)]);
  h.replies.push(fail("network"), fail("network"));
  await h.fire();
  await h.fire();
  assert.equal(h.timers[0].ms, 12000);
  p.setOpen([U(1), U(2)]);
  assert.equal(h.timers.length, 1);
  assert.equal(h.timers[0].ms, 12000);
  p.stop();
});
