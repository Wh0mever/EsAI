// Видеостудия: мок-сервер фикстур (lib/vstudio/fixtures.ts). Он — тренажёр
// для FE-1…FE-5, поэтому должен держать контракт §8 и денежные правила §5:
// резерв при запуске, списание ровно один раз и только за результат.
// Запуск (Node 22.6+):  node --experimental-strip-types --test src/lib/vstudio/fixtures.test.mjs
import "./nodeTsHooks.mjs";
import { test } from "node:test";
import assert from "node:assert/strict";

const fx = await import("./fixtures.ts");
const { OPEN_TAKE_STATUSES } = await import("./types.ts");

let clock = Date.parse("2026-09-24T10:00:00.000Z");
const now = () => clock;
const tick = (ms) => (clock += ms);
const mk = (opts = {}) => fx.createMockBackend({ now, latencyMs: 0, ...opts });

const get = (m, url) => m.fetch(url, "GET");
const post = (m, url, body = {}) => m.fetch(url, "POST", body);
const doc = (...nodes) => ({ v: 1, blocks: [nodes] });
const text = (v) => ({ t: "text", v });
const ref = (asset) => ({ t: "ref", asset });
let crid = 0;
const newCrid = () => (++crid).toString(16).padStart(32, "e");

async function uploads(m) {
  const r = await get(m, "vstudio/assets/?source=upload");
  // Сид: «Двор» 1280×853, «Героиня» 853×1280, «Мало» 240×240.
  const byW = Object.fromEntries(r.data.items.map((a) => [`${a.width}x${a.height}`, a]));
  return { yard: byW["1280x853"], hero: byW["853x1280"], tiny: byW["240x240"] };
}

function videoBody(extra = {}) {
  return {
    project: null,
    kind: "video",
    model: "bytedance/seedance-2.0",
    prompt_doc: doc(text("Кошка идёт по крыше")),
    inputs: [],
    params: { duration: 5, resolution: "720p", aspect_ratio: "16:9", generate_audio: true },
    ...extra,
  };
}

async function quoteOf(m, body) {
  const r = await post(m, "vstudio/quote/", body);
  assert.equal(r.status, 200, JSON.stringify(r.data));
  return r.data;
}

async function run(m, body, origin) {
  const q = await quoteOf(m, body);
  return post(m, "vstudio/shots/", { ...body, quoted_credits: q.credits, client_request_id: newCrid(), ...(origin ? { origin } : {}) });
}

async function takeOf(m, uid) {
  const r = await get(m, `vstudio/takes/?ids=${uid}`);
  return r.data.items[0];
}

test("models/: форма ModelJSON §8.3 и цены из таблицы", async () => {
  const m = mk();
  const r = await get(m, "vstudio/models/");
  assert.equal(r.status, 200);
  assert.equal(r.data.mode, "on");
  assert.equal(r.data.available, true);
  assert.equal(r.data.video.length, 4);
  assert.equal(r.data.image.length, 2);
  const sd = r.data.video[0];
  assert.deepEqual(Object.keys(sd).sort(), ["badge", "caps", "defaults", "eta_s", "id", "locked", "name", "price", "price_from"].sort());
  assert.deepEqual(
    Object.keys(sd.caps).sort(),
    [
      "aspect_ratios", "audio", "durations", "frames", "frames_with_refs", "min_ref_px", "negative", "prompt",
      "ref_forces_duration", "refs", "rejects_real_faces", "resolutions", "seed",
    ].sort(),
  );
  assert.equal(sd.price.table["720p"]["10"], 150);
  assert.ok(sd.price.by_aspect["21:9"]["720p"]["10"] > 150);
  assert.equal(sd.price_from, Math.min(...Object.values(sd.price.table).flatMap((row) => Object.values(row))));
  // Референсы включены только у Seedance (решение 1: остальные — до живой пробы).
  for (const v of r.data.video) assert.equal(v.caps.refs.image > 0, v.id.startsWith("bytedance/seedance"), v.id);
  const nb = r.data.image.find((x) => x.id === "google/gemini-2.5-flash-image");
  assert.equal(nb.per_image, 6);
  assert.equal(nb.caps.refs.image, 3);
});

test("флаг VSTUDIO_MODE: off и staff закрывают всё, кроме models/", async () => {
  const off = mk({ mode: "off" });
  assert.equal((await get(off, "vstudio/models/")).data.available, false);
  const q = await post(off, "vstudio/quote/", videoBody());
  assert.equal(q.status, 403);
  assert.equal(q.data.error_code, "vstudio_disabled");

  const staffOnly = mk({ mode: "staff", staff: false });
  assert.equal((await get(staffOnly, "vstudio/models/")).data.available, false);
  assert.equal((await get(staffOnly, "vstudio/projects/")).data.error_code, "vstudio_disabled");

  const staff = mk({ mode: "staff", staff: true });
  assert.equal((await get(staff, "vstudio/models/")).data.available, true);
  assert.equal((await get(staff, "vstudio/projects/")).status, 200);
});

test("quote t2v: цена, баланс, счётчик", async () => {
  const m = mk({ balance: 1200 });
  const q = await quoteOf(m, videoBody());
  assert.equal(q.mode, "t2v");
  assert.equal(q.credits, 75);
  assert.deepEqual(q.breakdown, [{ key: "price.video", params: { s: 5, res: "720p", ar: "16:9" }, credits: 75 }]);
  assert.deepEqual(q.balance, { balance: 1200, reserved: 0, available: 1200, after: 1125 });
  assert.deepEqual(q.errors, []);
  assert.deepEqual(q.effective, { duration: 5, resolution: "720p", generate_audio: true, aspect_ratio: "16:9" });
  assert.equal(q.meter.level, "ok");
  assert.equal(q.meter.soft_words, 150);
  assert.equal(q.eta_s, 150);
});

test("пример §4.6: два фото, роль, 164 кр, текст для модели", async () => {
  const m = mk();
  const { hero, yard } = await uploads(m);
  const body = videoBody({
    prompt_doc: doc(ref(hero.uid), text(" медленно идёт по старому двору "), ref(yard.uid), text(", камера плавно наезжает, тёплый закатный свет")),
    inputs: [
      { asset: hero.uid, slot: "reference", position: 0, role: "героиня", included: true },
      { asset: yard.uid, slot: "reference", position: 1, included: true },
    ],
    params: { duration: 10, resolution: "720p", aspect_ratio: "9:16", generate_audio: true },
  });
  const q = await quoteOf(m, body);
  assert.equal(q.mode, "r2v");
  assert.equal(q.credits, 164);
  assert.deepEqual(q.breakdown.map((l) => [l.key, l.credits]), [["price.video", 150], ["price.refs", 14]]);
  assert.deepEqual(q.labels, { [hero.uid]: "Image 1", [yard.uid]: "Image 2" });
  assert.equal(
    q.serialized_prompt,
    "Image 1 is героиня.\nImage 1 медленно идёт по старому двору Image 2, камера плавно наезжает, тёплый закатный свет",
  );
  // Фото из загрузок у Seedance — предупреждение до оплаты.
  assert.ok(q.warnings.some((w) => w.code === "faces_risk"));
  assert.ok(q.warnings.some((w) => w.code === "lang_hint"));
});

test("выключенный материал не учитывается и не оплачивается", async () => {
  const m = mk();
  const { hero, yard } = await uploads(m);
  const q = await quoteOf(
    m,
    videoBody({
      prompt_doc: doc(ref(hero.uid), text(" идёт")),
      inputs: [
        { asset: hero.uid, slot: "reference", position: 0, included: true },
        { asset: yard.uid, slot: "reference", position: 1, included: false },
      ],
    }),
  );
  assert.equal(q.credits, 75 + 7);
  assert.deepEqual(q.labels, { [hero.uid]: "Image 1" });
  assert.deepEqual(q.dropped, [{ asset: yard.uid, slot: "reference", reason: "excluded_by_user" }]);
  const excluded = q.warnings.find((w) => w.code === "input_excluded");
  assert.deepEqual(excluded.params, { asset: yard.uid, slot: "reference", n: null });
  assert.equal(excluded.message, "Выключенное фото не учитывается и не оплачивается.");
});

test("кадры и референсы: soft_pin у Seedance, конфликт у Veo, никогда оба поля сразу", async () => {
  const m = mk();
  const { hero, yard } = await uploads(m);
  const first = { asset: yard.uid, slot: "first_frame", position: 0, included: true };
  const refIn = { asset: hero.uid, slot: "reference", position: 0, included: true };

  const pin = await quoteOf(m, videoBody({ prompt_doc: doc(ref(hero.uid), text(" идёт")), inputs: [refIn, first] }));
  assert.equal(pin.mode, "r2v_pin");
  const soft = pin.warnings.find((w) => w.code === "frame_soft_pin");
  assert.equal(soft.params.k, 2);
  assert.match(pin.serialized_prompt, /^Image 2 is the first frame of the video\./);
  assert.equal(pin.credits, 75 + 14);

  const withLast = await quoteOf(
    m,
    videoBody({ inputs: [refIn, first, { asset: hero.uid, slot: "last_frame", position: 0, included: true }] }),
  );
  assert.ok(withLast.errors.some((e) => e.code === "last_frame_with_refs"));

  const veo = await quoteOf(
    m,
    videoBody({ model: "google/veo-3.1-fast", params: { duration: 8, resolution: "720p", aspect_ratio: "16:9" }, inputs: [refIn, first] }),
  );
  const conflict = veo.errors.find((e) => e.code === "frames_refs_conflict");
  assert.deepEqual(conflict.fixes, [
    { action: "use_frames_only", assets: [hero.uid] },
    { action: "use_refs_only", assets: [yard.uid] },
  ]);
  assert.deepEqual(conflict.fix, conflict.fixes[0]);
  const noRefs = veo.errors.find((e) => e.code === "refs_not_supported");
  assert.ok(noRefs);

  const veoRefOnly = await quoteOf(
    m,
    videoBody({ model: "google/veo-3.1-fast", params: { duration: 8, resolution: "720p" }, inputs: [refIn] }),
  );
  assert.deepEqual(veoRefOnly.errors.find((e) => e.code === "refs_not_supported").fix, { action: "move_to_first_frame", asset: hero.uid });

  // Тело «Что ушло модели» ни в одном режиме не несёт frame_images и input_references вместе.
  const combos = [[], [first], [refIn], [refIn, first], [first, { asset: hero.uid, slot: "last_frame", position: 0, included: true }]];
  let accepted = 0;
  for (const inputs of combos) {
    const r = await run(m, videoBody({ prompt_doc: doc(text("Кошка")), inputs }));
    if (r.status !== 202) continue;
    accepted++;
    const t = await get(m, `vstudio/takes/${r.data.take.uid}/`);
    const b = t.data.request_body;
    assert.ok(!(b.frame_images && b.input_references), JSON.stringify(b));
    tick(60_000); // закрыть дубль, чтобы не упереться в лимит открытых
    await get(m, `vstudio/takes/?ids=${r.data.take.uid}`);
  }
  // t2v, i2v, r2v, r2v_pin, flf2v — все пять запускаются.
  assert.equal(accepted, combos.length);
});

test("лимиты модели: слишком много фото, маленькое фото, чужой параметр", async () => {
  const m = mk();
  const { hero, yard, tiny } = await uploads(m);
  const lib = await get(m, "vstudio/assets/");
  const four = lib.data.items.filter((a) => a.status === "ready").slice(0, 4);
  assert.equal(four.length, 4);
  const nb = await quoteOf(m, {
    project: null,
    kind: "image",
    model: "google/gemini-2.5-flash-image",
    prompt_doc: doc(text("Коллаж")),
    inputs: four.map((a, i) => ({ asset: a.uid, slot: "reference", position: i, included: true })),
    params: { aspect_ratio: "1:1" },
  });
  const tooMany = nb.errors.find((e) => e.code === "too_many_refs");
  assert.deepEqual(tooMany.params, { max: 3, n: 4, model: "Nano Banana" });
  assert.deepEqual(tooMany.fix, { action: "exclude_inputs", assets: [four[3].uid] });
  assert.equal(nb.credits, 6);

  const small = await quoteOf(m, videoBody({ inputs: [{ asset: tiny.uid, slot: "reference", position: 0, included: true }] }));
  const tooSmall = small.errors.find((e) => e.code === "ref_too_small");
  assert.deepEqual(tooSmall.params, { asset: tiny.uid, slot: "reference", n: 1, model: "Seedance 2.0", min: 300 });
  assert.equal(tooSmall.message, "@Image 1 слишком маленькое для Seedance 2.0: нужно от 300 px по короткой стороне.");
  assert.deepEqual(tooSmall.fix, { action: "exclude_inputs", assets: [tiny.uid] });
  const smallFrame = await quoteOf(m, videoBody({ inputs: [{ asset: tiny.uid, slot: "first_frame", position: 0, included: true }] }));
  assert.match(smallFrame.errors.find((e) => e.code === "ref_too_small").message, /^@Первый кадр слишком маленький/);

  const bad = await quoteOf(m, videoBody({ params: { duration: 7, resolution: "720p" } }));
  const inv = bad.errors.find((e) => e.code === "invalid_param");
  assert.equal(inv.params.field, "duration");
  assert.equal(inv.message, "Seedance 2.0 не поддерживает длительность = 7. Доступно: 4, 5, 6, 8, 10, 12, 15.");
  assert.deepEqual(inv.params.allowed, [4, 5, 6, 8, 10, 12, 15]);
  assert.equal(bad.credits, null);

  // Veo с референсами снимает только 8 с — но референсы у Veo выключены, так что это блок, а не молчаливая подгонка.
  const veo = await quoteOf(
    m,
    videoBody({ model: "google/veo-3.1-fast", params: { duration: 4, resolution: "720p" }, inputs: [{ asset: yard.uid, slot: "reference", position: 0, included: true }, { asset: hero.uid, slot: "reference", position: 1, included: true }] }),
  );
  assert.ok(veo.errors.some((e) => e.code === "refs_not_supported"));
});

test("длинный промпт: мягкий лимит — предупреждение, жёсткий — блок, текст не режется", async () => {
  const m = mk();
  const long = Array.from({ length: 200 }, (_, i) => `word${i}`).join(" ");
  const soft = await quoteOf(m, videoBody({ prompt_doc: doc(text(long)) }));
  assert.equal(soft.meter.level, "soft");
  assert.equal(soft.meter.words, 200);
  const w = soft.warnings.find((x) => x.code === "prompt_long");
  assert.deepEqual(w.fix, { action: "condense" });
  assert.deepEqual(soft.errors, []);

  const huge = "а".repeat(2600);
  const hard = await quoteOf(
    m,
    videoBody({ model: "google/veo-3.1-fast", params: { duration: 8, resolution: "720p" }, prompt_doc: doc(text(huge)) }),
  );
  assert.equal(hard.meter.level, "hard");
  assert.equal(hard.meter.chars, 2600);
  assert.equal(hard.serialized_prompt.length, 2600);
  assert.deepEqual(hard.errors.find((e) => e.code === "prompt_too_long").params, { model: "Veo 3.1 Fast", chars: 2600, hard: 2500 });

  const script = ["Сцена 1. Девушка выходит из дома.", "Затем она идёт по улице.", "Сцена 2. 00:15 она садится в такси."]
    .join("\n")
    .padEnd(1600, " и ещё детали");
  const s = await quoteOf(m, videoBody({ prompt_doc: docFromLines(script) }));
  assert.ok(s.warnings.some((x) => x.code === "looks_like_script"));

  const empty = await quoteOf(m, videoBody({ prompt_doc: doc(text("   ")) }));
  assert.ok(empty.errors.some((e) => e.code === "prompt_empty"));
});

function docFromLines(s) {
  return { v: 1, blocks: s.split("\n").map((l) => [text(l)]) };
}

test("гость: цену видит без баланса, запускать и загружать не может", async () => {
  const m = mk({ guest: true });
  const q = await quoteOf(m, videoBody());
  assert.equal(q.balance, null);
  assert.equal(q.credits, 75);
  const withInputs = await post(m, "vstudio/quote/", videoBody({ inputs: [{ asset: "a".repeat(32), slot: "reference", position: 0, included: true }] }));
  assert.equal(withInputs.status, 401);
  assert.equal((await post(m, "vstudio/shots/", { ...videoBody(), quoted_credits: 75, client_request_id: newCrid() })).status, 401);
  assert.equal((await get(m, "vstudio/projects/")).status, 401);
  const up = await m.upload(new Blob([new Uint8Array(10)], { type: "image/jpeg" }), { project: null });
  assert.equal(up.status, 401);
});

test("запуск видео: резерв → статусы по времени → списание ровно один раз", async () => {
  const m = mk({ balance: 1000, seed: false });
  const body = videoBody();
  const r = await run(m, body);
  assert.equal(r.status, 202);
  const { project, shot, take, balance } = r.data;
  assert.match(project.uid, /^[0-9a-f]{32}$/);
  assert.equal(project.title, "Кошка идёт по крыше");
  assert.equal(project.open_takes, 1);
  assert.equal(shot.prompt_text, "Кошка идёт по крыше");
  assert.equal(shot.takes.length, 1);
  assert.equal(take.status, "queued");
  assert.equal(take.charge_state, "reserved");
  assert.deepEqual(take.credits, { quoted: 75, reserved: 75, charged: 0 });
  assert.deepEqual(balance, { balance: 1000, reserved: 75, available: 925 });
  assert.equal(r.data.asset, null);

  const seen = [];
  for (let i = 0; i < 20; i++) {
    const t = await takeOf(m, take.uid);
    if (seen.at(-1) !== t.status) seen.push(t.status);
    // Правило CheckConstraint: открытый — в резерве, закрытый — нет.
    assert.equal(OPEN_TAKE_STATUSES.includes(t.status), t.charge_state === "reserved", t.status);
    tick(1000);
  }
  assert.deepEqual(seen, ["queued", "submitting", "running", "saving", "done"]);
  const done = await takeOf(m, take.uid);
  assert.equal(done.charge_state, "charged");
  assert.equal(done.credits.charged, 75);
  assert.equal(done.result.kind, "video");
  assert.equal(done.result.url, fx.FIXTURE_VIDEO_URL);
  assert.ok(done.submitted_at && done.finished_at);
  // Повторные опросы не списывают второй раз.
  await takeOf(m, take.uid);
  await takeOf(m, take.uid);
  assert.equal(m.inspect().balance, 925);
  assert.equal(m.inspect().reserved, 0);
  const p = await get(m, `vstudio/projects/${project.uid}/`);
  assert.equal(p.data.open_takes, 0);
  assert.equal(p.data.thumb_url, done.result.thumb_url);
});

test("повтор client_request_id: тот же дубль, второго резерва нет", async () => {
  const m = mk({ seed: false });
  const body = videoBody();
  const q = await quoteOf(m, body);
  const id = newCrid();
  const a = await post(m, "vstudio/shots/", { ...body, quoted_credits: q.credits, client_request_id: id });
  const b = await post(m, "vstudio/shots/", { ...body, quoted_credits: q.credits, client_request_id: id });
  assert.equal(a.status, 202);
  assert.equal(b.status, 200);
  assert.equal(b.data.take.uid, a.data.take.uid);
  assert.equal(m.inspect().reserved, q.credits);
  assert.equal(m.inspect().takes, 1);
});

test("отказы запуска: цена, лимит открытых, баланс, премиум, блок", async () => {
  const m = mk({ balance: 200, seed: false });
  const body = videoBody();
  const changed = await post(m, "vstudio/shots/", { ...body, quoted_credits: 74, client_request_id: newCrid() });
  assert.equal(changed.status, 409);
  assert.equal(changed.data.error_code, "price_changed");
  assert.equal(changed.data.credits, 75);
  assert.equal(changed.data.breakdown[0].credits, 75);

  assert.equal((await run(m, body)).status, 202);
  assert.equal((await run(m, body)).status, 202);
  const third = await run(m, body);
  assert.equal(third.status, 409);
  assert.deepEqual([third.data.error_code, third.data.limit, third.data.kind], ["too_many_open", 2, "video"]);

  const poor = mk({ balance: 100, seed: false });
  assert.equal((await run(poor, body)).status, 202);
  const r402 = await run(poor, body);
  assert.equal(r402.status, 402);
  assert.equal(r402.data.error_code, "insufficient_balance");
  assert.equal(r402.data.balance_tokens, 25);
  assert.equal(r402.data.required_estimate, 75);
  assert.equal(r402.data.reserved_credits, 75);
  assert.match(r402.data.error, /кредитов/);

  const kling = videoBody({ model: "kwaivgi/kling-v3.0-std", params: { duration: 5, resolution: "720p" } });
  const locked = await post(mk({ seed: false }), "vstudio/shots/", { ...kling, quoted_credits: 50, client_request_id: newCrid() });
  assert.equal(locked.status, 403);
  assert.equal(locked.data.error_code, "premium_locked");

  const blocked = await post(mk({ seed: false }), "vstudio/shots/", {
    ...videoBody({ prompt_doc: doc(text("")) }),
    quoted_credits: 75,
    client_request_id: newCrid(),
  });
  assert.equal(blocked.status, 422);
  assert.equal(blocked.data.error_code, "blocked");
  assert.equal(blocked.data.errors[0].code, "prompt_empty");
});

test("отмена: только из queued; после отправки — 409", async () => {
  const m = mk({ seed: false, balance: 500 });
  const a = await run(m, videoBody());
  const c = await post(m, `vstudio/takes/${a.data.take.uid}/cancel/`);
  assert.equal(c.status, 200);
  assert.equal(c.data.status, "canceled");
  assert.equal(c.data.charge_state, "released");
  assert.equal(m.inspect().reserved, 0);

  const b = await run(m, videoBody());
  tick(2000);
  const late = await post(m, `vstudio/takes/${b.data.take.uid}/cancel/`);
  assert.equal(late.status, 409);
  assert.equal(late.data.error_code, "already_submitted");
});

test("неудача и потеря: кредиты не списаны, виноватое фото подсвечено", async () => {
  const m = mk({ balance: 500 });
  const { hero } = await uploads(m);
  const fail = await run(
    m,
    videoBody({
      prompt_doc: doc(ref(hero.uid), text(" #fail")),
      inputs: [{ asset: hero.uid, slot: "reference", position: 0, included: true }],
    }),
  );
  const lost = await run(m, videoBody({ prompt_doc: doc(text("Кошка #lost")) }));
  tick(60_000);
  // Третий запуск — после закрытия первых двух: открытых видео может быть только два.
  const unsaved = await run(m, videoBody({ prompt_doc: doc(text("Кошка #lost_save")) }));
  tick(60_000);
  const f = await takeOf(m, fail.data.take.uid);
  assert.equal(f.status, "failed");
  assert.equal(f.charge_state, "released");
  assert.equal(f.credits.charged, 0);
  assert.deepEqual([f.error.code, f.error.input], ["image_real_person", hero.uid]);
  assert.match(f.error.message, /реальных людей/);
  const l = await takeOf(m, lost.data.take.uid);
  assert.equal(l.status, "lost");
  assert.equal(l.error.code, "submit_unknown");
  // lost бывает и с другой причиной: ролик снят, но не сохранён.
  const u = await takeOf(m, unsaved.data.take.uid);
  assert.deepEqual([u.status, u.error.code, u.charge_state], ["lost", "save_failed", "released"]);
  assert.match(u.error.message, /^Ролик снят, но сохранить его не удалось/);
  assert.equal(m.inspect().balance, 500);
});

test("картинка для лотка: ассет pending сразу, потом ready и в библиотеке", async () => {
  const m = mk({ seed: false, balance: 100 });
  const body = {
    project: null,
    kind: "image",
    model: "google/gemini-2.5-flash-image",
    prompt_doc: doc(text("Рыжий кот")),
    inputs: [],
    params: { aspect_ratio: "1:1" },
  };
  const r = await run(m, body, "tray");
  assert.equal(r.status, 202);
  assert.equal(r.data.shot.origin, "tray");
  assert.equal(r.data.asset.status, "pending");
  assert.equal(r.data.asset.url, null);
  assert.equal(r.data.take.result.uid, r.data.asset.uid);
  // Пока создаётся — упоминание блокирует запуск видео с этим фото.
  const waiting = await quoteOf(
    m,
    videoBody({ prompt_doc: doc(ref(r.data.asset.uid)), inputs: [{ asset: r.data.asset.uid, slot: "reference", position: 0, included: true }] }),
  );
  const notReady = waiting.errors.find((e) => e.code === "asset_not_ready");
  assert.deepEqual(notReady.params, { asset: r.data.asset.uid, slot: "reference", n: 1 });
  assert.equal(notReady.message, "@Image 1 ещё создаётся — подождите несколько секунд.");
  tick(10_000);
  const t = await takeOf(m, r.data.take.uid);
  assert.equal(t.status, "done");
  assert.equal(t.result.status, "ready");
  assert.ok(t.result.url);
  assert.equal(m.inspect().balance, 94);
  const lib = await get(m, "vstudio/assets/?kind=image&source=generated_image");
  assert.equal(lib.data.items[0].uid, r.data.asset.uid);
});

test("повтор кадра: quote({shot}) и retry/", async () => {
  const m = mk({ seed: false, balance: 1000 });
  const a = await run(m, videoBody());
  tick(60_000);
  await takeOf(m, a.data.take.uid);
  const q = await quoteOf(m, { shot: a.data.shot.uid });
  assert.equal(q.credits, 75);
  const r = await post(m, `vstudio/shots/${a.data.shot.uid}/retry/`, { quoted_credits: q.credits, client_request_id: newCrid() });
  assert.equal(r.status, 202);
  assert.equal(r.data.take.status, "queued");
  assert.equal(r.data.balance.reserved, 75);
  const shots = await get(m, `vstudio/projects/${a.data.project.uid}/shots/`);
  assert.equal(shots.data.items[0].takes.length, 2);
  const wrong = await post(m, `vstudio/shots/${a.data.shot.uid}/retry/`, { quoted_credits: 1, client_request_id: newCrid() });
  assert.equal(wrong.data.error_code, "price_changed");
  assert.equal((await post(m, `vstudio/shots/${"f".repeat(32)}/retry/`, { quoted_credits: 1, client_request_id: newCrid() })).status, 404);
});

test("активные и полный дубль: project_uid, serialized_prompt, request_body", async () => {
  const m = mk({ seed: false });
  const a = await run(m, videoBody());
  const act = await get(m, "vstudio/takes/active/");
  assert.equal(act.data.items.length, 1);
  assert.equal(act.data.items[0].project_uid, a.data.project.uid);
  const full = await get(m, `vstudio/takes/${a.data.take.uid}/`);
  assert.equal(full.data.serialized_prompt, "Кошка идёт по крыше");
  assert.equal(full.data.request_body.model, "bytedance/seedance-2.0");
  assert.equal(full.data.request_body.duration, 5);
  assert.equal((await get(m, `vstudio/takes/${"f".repeat(32)}/`)).data.error_code, "take_not_found");
});

test("история: поиск, архив, страницы проектов и ленты", async () => {
  const m = mk({ balance: 10_000 });
  const all = await get(m, "vstudio/projects/");
  assert.deepEqual(all.data.items.map((p) => p.title), ["Кошка на крыше", "Закат над Бишкеком"]);
  assert.equal(all.data.next, null);
  assert.deepEqual((await get(m, "vstudio/projects/?archived=1")).data.items.map((p) => p.title), ["Старый тест"]);
  assert.deepEqual((await get(m, "vstudio/projects/?q=%D0%B7%D0%B0%D0%BA%D0%B0%D1%82")).data.items.map((p) => p.title), ["Закат над Бишкеком"]);
  const page1 = await get(m, "vstudio/projects/?limit=1");
  assert.equal(page1.data.items.length, 1);
  const page2 = await get(m, `vstudio/projects/?limit=1&before=${encodeURIComponent(page1.data.next)}`);
  assert.equal(page2.data.items[0].title, "Закат над Бишкеком");

  const cat = all.data.items[0];
  const seeded = await get(m, `vstudio/projects/${cat.uid}/shots/`);
  assert.equal(seeded.data.items.length, 2);
  assert.equal(seeded.data.items[0].takes[0].status, "done");
  assert.equal(seeded.data.items[1].takes[0].status, "failed");
  assert.equal(seeded.data.items[0].inputs[0].label, "Image 1");
  assert.equal(seeded.data.items[0].inputs[0].role, "героиня");
  assert.match(seeded.data.items[0].prompt_text, /^@Image 1 медленно идёт/);

  for (let i = 0; i < 3; i++) {
    const r = await run(m, videoBody({ project: cat.uid, prompt_doc: doc(text(`Кадр ${i}`)) }));
    assert.equal(r.status, 202);
    tick(60_000);
    await takeOf(m, r.data.take.uid);
  }
  const newest = await get(m, `vstudio/projects/${cat.uid}/shots/?limit=2`);
  assert.deepEqual(newest.data.items.map((s) => s.prompt_text), ["Кадр 1", "Кадр 2"]);
  const older = await get(m, `vstudio/projects/${cat.uid}/shots/?limit=2&before=${newest.data.next}`);
  assert.equal(older.data.items.at(-1).prompt_text, "Кадр 0");
  const oldest = await get(m, `vstudio/projects/${cat.uid}/shots/?limit=2&before=${older.data.next}`);
  assert.equal(oldest.data.items.length, 1);
  assert.equal(oldest.data.next, null);

  const patched = await m.fetch(`vstudio/projects/${cat.uid}/`, "PATCH", { title: "Кот", settings: { kind: "image" } });
  assert.equal(patched.data.title, "Кот");
  assert.deepEqual(patched.data.settings, { kind: "image" });
  assert.equal((await m.fetch(`vstudio/projects/${cat.uid}/`, "DELETE")).status, 204);
  assert.equal((await get(m, `vstudio/projects/${cat.uid}/`)).data.is_archived, true);
  assert.equal((await get(m, `vstudio/projects/${"f".repeat(32)}/`)).data.error_code, "project_not_found");
});

test("загрузка: прогресс, типы, размер, дедупликация, отмена", async () => {
  const m = mk({ seed: false });
  const progress = [];
  const file = new File([new Uint8Array([1, 2, 3])], "кот.jpg", { type: "image/jpeg" });
  const r = await m.upload(file, { project: null, onProgress: (p, phase) => progress.push(`${phase}:${p}`) });
  assert.equal(r.status, 201);
  assert.equal(r.data.source, "upload");
  assert.equal(r.data.status, "ready");
  assert.deepEqual(progress, ["upload:0", "upload:25", "upload:50", "upload:75", "processing:100"]);
  const again = await m.upload(file, { project: null });
  assert.equal(again.status, 200);
  assert.equal(again.data.uid, r.data.uid);

  const kinds = [
    [new File([new Uint8Array(4)], "clip.mp4", { type: "video/mp4" }), 422, "video_refs_unsupported"],
    [new File([new Uint8Array(4)], "voice.mp3", { type: "audio/mpeg" }), 422, "video_refs_unsupported"],
    [new File([new Uint8Array(4)], "doc.pdf", { type: "application/pdf" }), 422, "unsupported_type"],
    [new File(["<svg/>"], "x.svg", { type: "image/svg+xml" }), 422, "unsupported_type"],
    [new File([new Uint8Array(16 * 1024 * 1024)], "big.jpg", { type: "image/jpeg" }), 413, "file_too_large"],
  ];
  for (const [f, status, code] of kinds) {
    const res = await m.upload(f, { project: null });
    assert.equal(res.status, status, f.name);
    assert.equal(res.data.error_code, code, f.name);
  }
  const heic = await m.upload(new File([new Uint8Array(5)], "IMG_0001.HEIC", { type: "" }), { project: null });
  assert.equal(heic.status, 201);
  assert.equal(heic.data.flags.heic, true);

  const ctrl = new AbortController();
  ctrl.abort();
  const aborted = await m.upload(file, { project: null, signal: ctrl.signal });
  assert.equal(aborted.status, 0);
  assert.equal(aborted.data.error_code, "aborted");
});

test("удалённое фото: в новом запросе — asset_not_found, в повторе старого кадра — можно", async () => {
  const m = mk();
  const cat = (await get(m, "vstudio/projects/")).data.items[0];
  const shots = (await get(m, `vstudio/projects/${cat.uid}/shots/`)).data.items;
  const heroUid = shots[0].inputs[0].asset.uid;
  assert.equal((await m.fetch(`vstudio/assets/${heroUid}/`, "DELETE")).status, 204);
  assert.ok(!(await get(m, "vstudio/assets/")).data.items.some((a) => a.uid === heroUid));
  const fresh = await quoteOf(m, videoBody({ inputs: [{ asset: heroUid, slot: "reference", position: 0, included: true }] }));
  assert.ok(fresh.errors.some((e) => e.code === "asset_not_found"));
  const retry = await quoteOf(m, { shot: shots[0].uid });
  assert.ok(!retry.errors.some((e) => e.code === "asset_not_found"));
  assert.equal((await m.fetch(`vstudio/assets/${heroUid}/`, "DELETE")).status, 404);
});

test("«Сжать с ИИ»: каждый тег ровно один раз, слов не больше мягкого лимита", async () => {
  const m = mk();
  const { hero } = await uploads(m);
  const long = Array.from({ length: 300 }, (_, i) => `слово${i}`).join(" ");
  const src = { v: 1, blocks: [[ref(hero.uid), text(` ${long}`)], [text("Камера отъезжает")]] };
  const r = await post(m, "vstudio/assist/condense/", { model: "bytedance/seedance-2.0", prompt_doc: src, inputs: [] });
  assert.equal(r.status, 200);
  const refs = r.data.prompt_doc.blocks.flat().filter((n) => n.t === "ref");
  assert.deepEqual(refs, [ref(hero.uid)]);
  assert.ok(r.data.after.words <= 150, String(r.data.after.words));
  assert.equal(r.data.before.words, 304); // 300 слов + чип «@Image 1» (2) + «Камера отъезжает» (2)
  // Текст не прилипает к чипу.
  assert.match(r.data.prompt_doc.blocks[0][1].v, /^ слово0/);

  const fail = await post(m, "vstudio/assist/condense/", { model: "bytedance/seedance-2.0", prompt_doc: doc(text("#condense_fail")), inputs: [] });
  assert.equal(fail.status, 422);
  assert.equal(fail.data.error_code, "condense_failed");
  const invalid = await post(m, "vstudio/assist/condense/", { model: "x", prompt_doc: { v: 2 }, inputs: [] });
  assert.equal(invalid.data.error_code, "prompt_doc_invalid");
});

test("последний кадр → первый: только из своего готового видео", async () => {
  const m = mk({ seed: false });
  const a = await run(m, videoBody());
  const early = await post(m, "vstudio/assets/from-take/", { take: a.data.take.uid, at: "last_frame" });
  assert.equal(early.status, 404);
  tick(60_000);
  await takeOf(m, a.data.take.uid);
  const frame = await post(m, "vstudio/assets/from-take/", { take: a.data.take.uid, at: "last_frame" });
  assert.equal(frame.status, 201);
  assert.equal(frame.data.source, "frame");
});

test("готовые объекты для вёрстки согласованы с правилами денег", () => {
  for (const s of ["queued", "submitting", "running", "saving", "done", "failed", "canceled", "lost"]) {
    const t = fx.fixtureTake(s);
    assert.equal(OPEN_TAKE_STATUSES.includes(s), t.charge_state === "reserved", s);
    assert.equal(t.credits.charged > 0, s === "done", s);
    assert.equal(t.result !== null, s === "done", s);
  }
  assert.match(fx.fixtureUid("a", 1), /^[0-9a-f]{32}$/);
  assert.equal(fx.FIXTURE_QUOTE.credits, fx.FIXTURE_QUOTE.breakdown.reduce((s, l) => s + l.credits, 0));
  assert.match(fx.placeholderImage("<Кот>", 10), /^data:image\/svg\+xml/);
  assert.ok(!decodeURIComponent(fx.placeholderImage("<Кот>", 10)).includes("<Кот>"));
});

test("один мок на вкладку: getMockBackend и resetMockBackend", () => {
  fx.resetMockBackend(null);
  const a = fx.getMockBackend();
  assert.equal(fx.getMockBackend(), a);
  const b = fx.resetMockBackend({ latencyMs: 0, seed: false });
  assert.notEqual(b, a);
  assert.equal(fx.getMockBackend(), b);
  fx.resetMockBackend(null);
});

test("чип без материала в запросе: по записи на чип, params.asset — какой красить", async () => {
  const m = mk({ seed: false });
  const ghost = "f".repeat(32);
  const q = await quoteOf(m, videoBody({ prompt_doc: doc(ref(ghost), text(" и "), ref(ghost)) }));
  const miss = q.errors.filter((e) => e.code === "mention_not_attached");
  assert.deepEqual(miss.map((e) => e.params), [{ asset: ghost }]);
});
