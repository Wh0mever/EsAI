// Видеостудия, композер: чистая логика (composer/composerLogic.ts) — кнопка
// «Создать» во всех состояниях §9.6, исправления из fix через настоящий
// редьюсер, подсказки, счётчик длины, «похоже на сценарий», когда
// пересчитывать цену. Плюс сверка ключей текстов (composerText.ts).
// Запуск (Node 22.6+):  node --experimental-strip-types --test src/components/vstudio/composer/*.test.mjs
import "../../../lib/vstudio/nodeTsHooks.mjs";
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

globalThis.window = {
  sessionStorage: { getItem: () => null, setItem() {}, removeItem() {} },
  location: { origin: "https://esai.test", pathname: "/video-studio", search: "", hash: "", protocol: "https:", replace() {} },
};

const L = await import("./composerLogic.ts");
const T = await import("./composerText.ts");
const S = await import("../store.ts");
const api = await import("../../../lib/vstudio/api.ts");

const U = (n) => n.toString(16).padStart(32, "0");

function asset(n, over = {}) {
  return {
    uid: U(n),
    kind: "image",
    source: "upload",
    status: "ready",
    url: `/media/vstudio/1/${U(n)}.jpg`,
    thumb_url: `/media/vstudio/1/${U(n)}_t.jpg`,
    width: 1024,
    height: 1024,
    duration_s: null,
    label: "",
    flags: {},
    error_code: null,
    created_at: "2026-09-24T10:00:00Z",
    ...over,
  };
}

function item(n, over = {}) {
  const a = asset(n);
  return {
    lid: `l${n}`,
    assetUid: a.uid,
    slot: "reference",
    role: "",
    included: true,
    status: "ready",
    progress: 100,
    preview: a.thumb_url,
    asset: a,
    ...over,
  };
}

const noFrames = { first_frame: null, last_frame: null };

function quote(over = {}) {
  return {
    credits: 164,
    breakdown: [],
    balance: { balance: 1200, reserved: 120, available: 1080, after: 916 },
    mode: "r2v",
    effective: {},
    labels: {},
    serialized_prompt: "",
    errors: [],
    warnings: [],
    meter: { chars: 10, words: 2, soft_words: 150, hard_chars: 6000, level: "ok" },
    dropped: [],
    eta_s: 120,
    ...over,
  };
}

const issue = (code, params = {}, extra = {}) => ({ code, params, message: "", ...extra });

/* ---------- материалы ---------- */

test("summarize: референсы и кадры считаются только включённые и с uid; загрузки и упавшие — отдельно", () => {
  const c = {
    tray: [
      item(1),
      item(2, { included: false }),
      item(3, { status: "uploading", assetUid: undefined }),
      item(4, { status: "failed", assetUid: undefined }),
      item(5, { status: "pending" }),
    ],
    frames: { first_frame: item(6, { slot: "first_frame" }), last_frame: item(7, { slot: "last_frame", status: "processing" }) },
  };
  const s = L.summarize(c);
  assert.equal(s.refs, 2);
  assert.equal(s.frames, 1);
  assert.equal(s.uploading, 2);
  assert.equal(s.failedUploads, 1);
  assert.equal(s.pending?.lid, "l5");
  assert.equal(s.total, 7);
});

test("nextRefNumber: номер новой картинки — после включённых референсов (дубли uid не считаются)", () => {
  assert.equal(L.nextRefNumber([]), 1);
  assert.equal(L.nextRefNumber([item(1), item(2, { included: false }), item(3)]), 3);
  assert.equal(L.nextRefNumber([item(1), { ...item(1), lid: "dup" }]), 2);
  assert.equal(L.nextRefNumber([item(1, { assetUid: undefined, status: "uploading" })]), 1);
});

test("trayItemFromAsset: статус чипа по ассету, стабильный lid", () => {
  const ready = L.trayItemFromAsset(asset(1), "reference");
  assert.equal(ready.lid, `lib:reference:${U(1)}`);
  assert.equal(ready.status, "ready");
  assert.equal(ready.preview, asset(1).thumb_url);
  const pending = L.trayItemFromAsset(asset(2, { status: "pending", url: null, thumb_url: null }), "reference", "gen");
  assert.equal(pending.status, "pending");
  assert.equal(pending.lid, `gen:reference:${U(2)}`);
  const failed = L.trayItemFromAsset(asset(3, { status: "failed", error_code: "image_sensitive" }), "first_frame");
  assert.equal(failed.errorCode, "image_sensitive");
  assert.equal(failed.slot, "first_frame");
});

test("hasAssetIn / lidsForAssets: по слотам", () => {
  const c = { tray: [item(1), item(2)], frames: { first_frame: item(3, { slot: "first_frame", lid: "f" }), last_frame: null } };
  assert.equal(L.hasAssetIn(c, U(1)), true);
  assert.equal(L.hasAssetIn(c, U(3), "reference"), false);
  assert.equal(L.hasAssetIn(c, U(3), "first_frame"), true);
  assert.equal(L.hasAssetIn(c, U(3), "last_frame"), false);
  assert.deepEqual(L.lidsForAssets(c, [U(1), U(3)]), ["l1", "f"]);
  assert.deepEqual(L.lidsForAssets(c, [U(1), U(3)], "frames"), ["f"]);
  assert.deepEqual(L.lidsForAssets(c, [U(1), U(3)], "reference"), ["l1"]);
});

test("countOpen: только открытые дубли нужного вида", () => {
  const t = (kind, status) => ({ kind, status });
  const takes = [t("video", "running"), t("video", "queued"), t("video", "done"), t("image", "running"), t("video", "lost")];
  assert.equal(L.countOpen(takes, "video"), 2);
  assert.equal(L.countOpen(takes, "image"), 1);
});

/* ---------- исправления через настоящий редьюсер ---------- */

function stateWith(composer) {
  const s = S.createInitialState();
  return { ...s, composer: { ...s.composer, ...composer } };
}

function apply(state, plan) {
  assert.equal(plan.kind, "actions");
  return plan.actions.reduce(S.reducer, state);
}

test("fix use_frames_only: референсы гаснут (не удаляются), кадры остаются", () => {
  let st = stateWith({ tray: [item(1), item(2)], frames: { first_frame: item(3, { slot: "first_frame", lid: "f" }), last_frame: null } });
  st = apply(st, L.planFix({ action: "use_frames_only" }, st.composer));
  assert.deepEqual(st.composer.tray.map((i) => i.included), [false, false]);
  assert.equal(st.composer.tray.length, 2, "выключенное не удаляется");
  assert.equal(st.composer.frames.first_frame.included, true);
});

test("fix use_refs_only: кадры гаснут; с assets — только перечисленные", () => {
  let st = stateWith({
    tray: [item(1)],
    frames: { first_frame: item(3, { slot: "first_frame", lid: "f" }), last_frame: item(4, { slot: "last_frame", lid: "g" }) },
  });
  st = apply(st, L.planFix({ action: "use_refs_only", assets: [U(4)] }, st.composer));
  assert.equal(st.composer.frames.first_frame.included, true);
  assert.equal(st.composer.frames.last_frame.included, false);
  assert.equal(st.composer.tray[0].included, true);
});

test("fix exclude_inputs, move_to_first_frame, set_param", () => {
  let st = stateWith({ tray: [item(1), item(2), item(3)], frames: noFrames, params: { aspect_ratio: "16:9" } });
  st = apply(st, L.planFix({ action: "exclude_inputs", assets: [U(2), U(3)] }, st.composer));
  assert.deepEqual(st.composer.tray.map((i) => i.included), [true, false, false]);

  st = apply(st, L.planFix({ action: "move_to_first_frame", asset: U(1) }, st.composer));
  assert.equal(st.composer.frames.first_frame.assetUid, U(1));
  assert.deepEqual(st.composer.tray.map((i) => i.assetUid), [U(2), U(3)]);

  st = apply(st, L.planFix({ action: "set_param", field: "aspect_ratio", value: "9:16" }, st.composer));
  assert.equal(st.composer.params.aspect_ratio, "9:16");
});

test("planFix: особые исправления и пустые случаи", () => {
  const c = { tray: [item(1)], frames: noFrames };
  assert.deepEqual(L.planFix({ action: "condense" }, c), { kind: "condense" });
  assert.deepEqual(L.planFix({ action: "topup" }, c), { kind: "topup" });
  assert.deepEqual(L.planFix({ action: "pick_model", model: "google/veo-3.1-fast" }, c), {
    kind: "pick_model",
    model: "google/veo-3.1-fast",
  });
  assert.deepEqual(L.planFix({ action: "pick_model" }, c), { kind: "pick_model", model: null });
  assert.deepEqual(L.planFix({ action: "exclude_inputs", assets: [U(99)] }, c), { kind: "none" });
  assert.deepEqual(L.planFix({ action: "move_to_first_frame", asset: U(99) }, c), { kind: "none" });
  assert.deepEqual(L.planFix(null, c), { kind: "none" });
});

test("fixLabelKey: у каждого действия своя подпись", () => {
  assert.equal(L.fixLabelKey({ action: "set_param", field: "aspect_ratio", value: "9:16" }), "fix.apply");
  assert.equal(L.fixLabelKey({ action: "set_param", field: "seed", value: null }), "fix.applyParam");
  assert.equal(L.fixLabelKey({ action: "use_frames_only" }), "fix.useFrames");
  assert.equal(L.fixLabelKey({ action: "move_to_first_frame", asset: U(1) }), "fix.moveToFirstFrame");
});

/* ---------- подсказки ---------- */

test("groupHints: конфликт — в плашку, сценарий — в свою, длина — к счётчику, input_excluded не дублируем", () => {
  const g = L.groupHints(
    quote({
      errors: [issue("frames_refs_conflict", { model: "Veo" }), issue("mention_not_attached", { asset: U(9) }), issue("prompt_too_long")],
      warnings: [
        issue("looks_like_script"),
        issue("prompt_long", { words: 480 }),
        issue("input_excluded", { asset: U(2), n: null }),
        issue("faces_risk", { model: "Seedance" }),
        issue("faces_risk", { model: "Seedance" }),
      ],
    }),
  );
  assert.equal(g.conflict?.code, "frames_refs_conflict");
  assert.equal(g.script?.code, "looks_like_script");
  assert.equal(g.length?.code, "prompt_too_long", "жёсткий лимит главнее мягкого");
  assert.deepEqual(
    g.list.map((h) => `${h.tone}:${h.issue.code}`),
    ["error:mention_not_attached", "error:prompt_too_long", "warning:faces_risk"],
  );
  assert.deepEqual(L.groupHints(null), { conflict: null, script: null, length: null, list: [] });
  // Пустое поле: «Опишите, что…» не кричит красным над полем (кнопка и так выключена).
  const empty = L.groupHints(quote({ errors: [issue("prompt_empty")] }), { emptyText: true });
  assert.deepEqual(empty.list, []);
  assert.equal(L.groupHints(quote({ errors: [issue("prompt_empty")] })).list.length, 1);
});

test("conflictFixes: с сервера, а без них — две кнопки своими силами", () => {
  const server = issue("frames_refs_conflict", {}, { fix: { action: "use_frames_only", assets: [U(1)] }, fixes: [{ action: "use_frames_only" }, { action: "use_refs_only" }] });
  assert.deepEqual(L.conflictFixes(server).map((f) => f.action), ["use_frames_only", "use_refs_only"]);
  assert.deepEqual(L.conflictFixes(issue("frames_refs_conflict")).map((f) => f.action), ["use_frames_only", "use_refs_only"]);
  assert.deepEqual(L.conflictFixes(issue("last_frame_with_refs")).map((f) => f.action), ["use_frames_only"]);
});

test("flaggedAssets: uid из params.asset и params.assets", () => {
  const s = L.flaggedAssets([issue("asset_failed", { asset: U(1) }), issue("faces_risk", { assets: [U(2), U(3)] }), issue("prompt_empty")]);
  assert.deepEqual([...s].sort(), [U(1), U(2), U(3)]);
});

/* ---------- счётчик длины ---------- */

test("meterView: на клиенте — по лимитам модели, свежий quote главнее", () => {
  const model = { caps: { prompt: { soft_words: 5, hard_chars: 40, lang: "en" } } };
  const ok = L.meterView("кот идёт по крыше", model);
  assert.deepEqual([ok.chars, ok.words, ok.level, ok.exact], [17, 4, "ok", false]);
  const soft = L.meterView("один два три четыре пять шесть", model);
  assert.equal(soft.level, "soft");
  const hard = L.meterView("x".repeat(41), model);
  assert.equal(hard.level, "hard");
  assert.ok(hard.ratio > 1);
  const server = L.meterView("что угодно", model, { chars: 2940, words: 480, soft_words: 150, hard_chars: 6000, level: "soft" });
  assert.deepEqual([server.chars, server.words, server.level, server.exact], [2940, 480, "soft", true]);
  assert.equal(server.ratio, 1, "по мягкому лимиту полоса полна");
  // Нет модели — предел редактора.
  assert.equal(L.meterView("abc", null).hard, 20000);
});

test("looksLikeScript: >1500 символов и ≥2 признака (как compiler.script_signs)", () => {
  const filler = "Длинное описание сцены с подробностями. ".repeat(45);
  assert.ok(filler.length > 1500);
  assert.equal(L.looksLikeScript(filler), false, "просто длинный текст — не сценарий");
  assert.equal(L.looksLikeScript(filler + " затем герой уходит, потом возвращается"), false, "связки считаются один раз");
  assert.equal(L.looksLikeScript("Сцена 1. Утро\n" + filler + "\nСцена 2. Вечер"), true);
  assert.equal(L.looksLikeScript("0:05 рассвет\n" + filler + "\n0:12 полдень"), true);
  assert.equal(L.looksLikeScript("1. Кот просыпается\n2. Кот ест\n" + filler), true);
  assert.equal(L.looksLikeScript("Сцена 1\nСцена 2"), false, "короткое — не сценарий");
  assert.equal(L.scriptSigns("12:30 и 1:05, 2025:10"), 2, "таймкоды по границе цифр");
  assert.equal(L.scriptSigns("затемнение, потомок"), 0, "части слов не считаются");
  assert.equal(L.scriptSigns("Then we go. then again"), 1);
});

/* ---------- когда пересчитывать цену ---------- */

test("quoteDelay: структура и статусы — сразу, текст — с паузой, без изменений — ничего", () => {
  const base = { project: null, kind: "video", model: "m", prompt_doc: { v: 1, blocks: [[{ t: "text", v: "a" }]] }, inputs: [], params: { duration: 5 } };
  const trig = (body, extra = "") => ({ key: api.quoteKey(body), structure: L.structureKey(body), extra });
  const a = trig(base);
  assert.equal(L.quoteDelay(null, a), 0);
  assert.equal(L.quoteDelay(a, trig(base)), null);
  const text = { ...base, prompt_doc: { v: 1, blocks: [[{ t: "text", v: "ab" }]] } };
  assert.equal(L.quoteDelay(a, trig(text)), L.TEXT_QUOTE_DELAY_MS);
  const params = { ...base, params: { duration: 10 } };
  assert.equal(L.quoteDelay(a, trig(params)), 0);
  assert.equal(L.quoteDelay(a, trig(base, "x")), 0, "статус материала сменился");
  assert.equal(L.quoteDelay(a, { key: "", structure: "", extra: "" }), null);
  // prompt_text в textarea-режиме — тоже «текст».
  const pt = L.withPromptText(base, "@Image 1 идёт");
  assert.equal(pt.prompt_doc, undefined);
  assert.equal(pt.prompt_text, "@Image 1 идёт");
  assert.equal(L.structureKey(pt), L.structureKey(base));
  assert.equal(L.withPromptText(base, null), base);
});

test("statusSignature: меняется, когда «создаётся» стало готовым", () => {
  const pending = { tray: [item(1, { status: "pending" })], frames: noFrames };
  const ready = { tray: [item(1)], frames: noFrames };
  assert.notEqual(L.statusSignature(pending), L.statusSignature(ready));
  assert.equal(L.statusSignature({ tray: [item(2, { assetUid: undefined, status: "uploading" })], frames: noFrames }), "");
});

/* ---------- кнопка «Создать» (§9.6) ---------- */

const baseInput = {
  authed: true,
  model: { locked: false },
  kind: "video",
  sending: false,
  cooldown: false,
  summary: L.summarize({ tray: [], frames: noFrames }),
  fresh: quote(),
  quoteStatus: "ready",
  quoteError: null,
  lastCredits: null,
  openCount: 0,
  limitHit: null,
};
const v = (over) => L.runView({ ...baseInput, ...over });

test("runView: обычный случай — «Создать · 164 кр»", () => {
  assert.deepEqual(v({}), { kind: "run", credits: 164 });
});

test("runView: порядок причин — отправка > гость > модели > загрузка > «ждём» > упавшая загрузка > лимит > ошибки", () => {
  const busy = L.summarize({ tray: [item(1, { status: "uploading", assetUid: undefined }), item(2, { status: "pending" })], frames: noFrames });
  assert.equal(v({ sending: true, authed: false }).kind, "sending");
  assert.equal(v({ cooldown: true }).kind, "started");
  assert.equal(v({ authed: false, summary: busy }).kind, "signin");
  assert.equal(v({ model: null }).kind, "no_model");
  assert.deepEqual(v({ summary: busy }), { kind: "uploading", count: 1 });
  const waiting = v({ summary: L.summarize({ tray: [item(2, { status: "pending" })], frames: noFrames }) });
  assert.equal(waiting.kind, "waiting");
  assert.equal(waiting.item.lid, "l2");
  assert.equal(v({ summary: L.summarize({ tray: [item(3, { status: "failed", assetUid: undefined })], frames: noFrames }) }).kind, "failed_upload");
  assert.deepEqual(v({ openCount: 2 }), { kind: "limit", n: 2, of: "video" });
  assert.equal(v({ openCount: 3, kind: "image" }).kind, "run", "картинок можно 4");
  assert.deepEqual(v({ openCount: 4, kind: "image" }), { kind: "limit", n: 4, of: "image" });
  assert.deepEqual(v({ limitHit: { kind: "video", limit: 2 } }), { kind: "limit", n: 2, of: "video" }, "409 держим, даже если вкладка не видит тех дублей");
  assert.equal(v({ limitHit: { kind: "image", limit: 4 } }).kind, "run", "лимит другого вида не мешает");
  const blocked = v({ fresh: quote({ errors: [issue("too_many_refs", { max: 3, n: 4 })] }) });
  assert.equal(blocked.kind, "blocked");
  assert.equal(blocked.issue.code, "too_many_refs");
});

test("runView: цена не посчиталась, модель под замком, не хватает кредитов", () => {
  assert.deepEqual(v({ fresh: quote({ credits: null }) }), { kind: "no_price", error: null });
  assert.deepEqual(v({ model: { locked: true } }), { kind: "locked", credits: 164 });
  assert.deepEqual(v({ fresh: quote({ credits: 164, balance: { balance: 128, reserved: 0, available: 128, after: null } }) }), {
    kind: "topup",
    credits: 164,
    missing: 36,
  });
  // Гость видит цену: баланса нет — пополнять не предлагаем.
  assert.equal(v({ fresh: quote({ balance: null }) }).kind, "run");
});

test("quoteMissing: то же число, что на кнопке «Пополнить»; 0 — хватает, гость или цены нет", () => {
  const bal = (available) => ({ balance: available, reserved: 0, available, after: null });
  const short = quote({ credits: 164, balance: bal(128) });
  assert.equal(L.quoteMissing(short), 36);
  assert.equal(L.quoteMissing(short), v({ fresh: short }).missing, "кнопка и перезапрос цены после оплаты считают одинаково");
  // Модель под замком: на кнопке «замок», но по цене видно, что после покупки тарифа её надо спросить заново.
  assert.equal(v({ fresh: short, model: { locked: true } }).kind, "locked");
  assert.equal(L.quoteMissing(quote({ credits: 164, balance: bal(163.5) })), 1, "дробный остаток — вверх");
  assert.equal(L.quoteMissing(quote({ credits: 164, balance: bal(164) })), 0);
  assert.equal(v({ fresh: quote({ credits: 164, balance: bal(164) }) }).kind, "run");
  assert.equal(L.quoteMissing(quote({ credits: 164, balance: bal(500) })), 0);
  assert.equal(L.quoteMissing(quote({ balance: null })), 0);
  assert.equal(L.quoteMissing(quote({ credits: null, balance: bal(0) })), 0);
  assert.equal(L.quoteMissing(null), 0);
});

test("runView: пока цена считается — прошлая цена той же структуры, иначе скелетон; ошибка quote", () => {
  assert.deepEqual(v({ fresh: null, quoteStatus: "loading", lastCredits: 150 }), { kind: "quoting", credits: 150 });
  assert.deepEqual(v({ fresh: null, quoteStatus: "loading" }), { kind: "quoting", credits: null });
  const err = { status: 0, code: "network", message: "", data: {} };
  assert.deepEqual(v({ fresh: null, quoteStatus: "error", quoteError: err }), { kind: "no_price", error: err });
});

test("runClickable: выключенная кнопка с причиной всё равно ловит клик (показать причину)", () => {
  assert.equal(L.runClickable({ kind: "run", credits: 1 }), true);
  assert.equal(L.runClickable({ kind: "blocked", issue: issue("prompt_empty") }), true);
  assert.equal(L.runClickable({ kind: "sending" }), false);
  assert.equal(L.runClickable({ kind: "uploading", count: 1 }), false);
  assert.equal(L.runClickable({ kind: "limit", n: 2, of: "video" }), false);
  assert.equal(L.runClickable({ kind: "started" }), false);
});

test("runClickMeta: meta vstudio_run_click (§11)", () => {
  const summary = L.summarize({ tray: [item(1), item(2)], frames: { first_frame: item(3, { slot: "first_frame" }), last_frame: null } });
  assert.deepEqual(L.runClickMeta("bytedance/seedance-2.0", "video", 164, summary, "@Image 1 идёт по крыше"), {
    model: "bytedance/seedance-2.0",
    kind: "video",
    credits: 164,
    refs: 2,
    frames: 1,
    words: 5,
  });
});

test("fmtNum, moveTarget", () => {
  assert.equal(L.fmtNum(1200).replace(/\s/g, " "), "1 200");
  assert.equal(L.fmtNum(null), "");
  const tray = [item(1), item(2), item(3)];
  assert.equal(L.moveTarget(tray, "l1", -1), null);
  assert.equal(L.moveTarget(tray, "l1", 1), 1);
  assert.equal(L.moveTarget(tray, "l3", 1), null);
  assert.equal(L.moveTarget(tray, "zz", 1), null);
});

test("перестановка в лотке перенумеровывает @Image N (номер = порядок включённых)", async () => {
  const labels = await import("../../../lib/vstudio/labels.ts");
  let st = stateWith({ tray: [item(1), item(2, { included: false }), item(3)], frames: noFrames });
  assert.deepEqual(labels.trayRefNumbers(st.composer.tray), { [U(1)]: 1, [U(3)]: 2 });
  st = S.reducer(st, { type: "tray/move", lid: "l3", to: L.moveTarget(st.composer.tray, "l3", -1) });
  st = S.reducer(st, { type: "tray/move", lid: "l3", to: L.moveTarget(st.composer.tray, "l3", -1) });
  assert.deepEqual(labels.trayRefNumbers(st.composer.tray), { [U(3)]: 1, [U(1)]: 2 });
});

/* ---------- тексты ---------- */

test("composerText: каждый ключ, который зовут компоненты композера и библиотеки, есть в COMPOSER_RU", () => {
  const here = dirname(fileURLToPath(import.meta.url));
  const dirs = [here, join(here, "..", "library"), join(here, "..", "hooks")];
  const used = new Set();
  for (const dir of dirs) {
    for (const name of readdirSync(dir)) {
      if (!/\.(tsx?|ts)$/.test(name) || name.endsWith(".test.mjs")) continue;
      const src = readFileSync(join(dir, name), "utf8");
      for (const m of src.matchAll(/\bct\(\s*t{1,2}\s*,\s*"([^"]+)"/g)) used.add(m[1]);
    }
  }
  assert.ok(used.size > 40, `ключей найдено: ${used.size}`);
  const missing = [...used].filter((k) => !(k in T.COMPOSER_RU));
  assert.deepEqual(missing, []);
  for (const f of ["all", "uploads", "generated", "frames"]) assert.ok(`library.filter.${f}` in T.COMPOSER_RU);
  // Подстановки i18next — только {{x}}.
  for (const [k, v] of Object.entries(T.COMPOSER_RU)) assert.doesNotMatch(v, /(^|[^{])\{[a-z]+\}(?!\})/i, k);
  assert.equal(T.ruText("composer.run", { credits: 164 }), "Создать · 164 кр");
});
