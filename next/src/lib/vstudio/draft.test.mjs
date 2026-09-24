// Видеостудия: черновик гостя (lib/vstudio/draft.ts) — запись, чтение,
// белый список, срок жизни, недоступное хранилище.
// Запуск (Node 22.6+):  node --experimental-strip-types --test src/lib/vstudio/draft.test.mjs
import "./nodeTsHooks.mjs";
import { test } from "node:test";
import assert from "node:assert/strict";

const D = await import("./draft.ts");

function memoryStorage() {
  const m = new Map();
  return {
    map: m,
    getItem: (k) => (m.has(k) ? m.get(k) : null),
    setItem: (k, v) => m.set(k, String(v)),
    removeItem: (k) => m.delete(k),
  };
}

const doc = (...texts) => ({ v: 1, blocks: texts.map((t) => (t ? [{ t: "text", v: t }] : [])) });
const composer = (overrides = {}) => ({
  kind: "video",
  model: "bytedance/seedance-2.0",
  params: { duration: 10, aspect_ratio: "9:16", resolution: "720p", generate_audio: true },
  doc: doc("Кошка идёт по крыше"),
  ...overrides,
});

test("сохранить и поднять: текст и параметры возвращаются как были", () => {
  const storage = memoryStorage();
  assert.equal(D.saveDraft(composer(), { storage, now: () => 1000 }), true);
  const raw = JSON.parse(storage.getItem(D.DRAFT_KEY));
  assert.equal(raw.v, 1);
  assert.equal(raw.updated_at, 1000);
  const back = D.loadDraft({ storage, now: () => 2000 });
  assert.deepEqual(back, composer());
});

test("ссылки на материалы в черновик не попадают (у гостя материалов нет)", () => {
  const storage = memoryStorage();
  const withRef = {
    v: 1,
    blocks: [[{ t: "text", v: "Героиня " }, { t: "ref", asset: "a".repeat(32) }, { t: "text", v: " идёт" }], []],
  };
  D.saveDraft(composer({ doc: withRef }), { storage });
  const back = D.loadDraft({ storage });
  assert.deepEqual(back.doc, { v: 1, blocks: [[{ t: "text", v: "Героиня  идёт" }], []] });
});

test("пустой текст стирает черновик: поднимать после входа нечего", () => {
  const storage = memoryStorage();
  D.saveDraft(composer(), { storage });
  assert.equal(D.saveDraft(composer({ doc: doc("   ") }), { storage }), false);
  assert.equal(storage.getItem(D.DRAFT_KEY), null);
  assert.equal(D.loadDraft({ storage }), null);
});

test("протухший черновик (старше недели) не поднимается и стирается", () => {
  const storage = memoryStorage();
  D.saveDraft(composer(), { storage, now: () => 0 });
  assert.equal(D.loadDraft({ storage, now: () => D.DRAFT_MAX_AGE_MS + 1 }), null);
  assert.equal(storage.getItem(D.DRAFT_KEY), null);
});

test("испорченный черновик (не JSON, чужая версия, кривой документ) стирается", () => {
  for (const bad of ["{не json", JSON.stringify({ v: 2 }), JSON.stringify({ v: 1, updated_at: Date.now(), doc: { v: 1, blocks: "x" } })]) {
    const storage = memoryStorage();
    storage.setItem(D.DRAFT_KEY, bad);
    assert.equal(D.loadDraft({ storage }), null, bad);
    assert.equal(storage.getItem(D.DRAFT_KEY), null, bad);
  }
});

test("длинный текст не режется молча: больше 20 000 символов черновик не поднимается", () => {
  const storage = memoryStorage();
  const long = "а".repeat(20001);
  storage.setItem(
    D.DRAFT_KEY,
    JSON.stringify({ v: 1, updated_at: Date.now(), kind: "video", model: null, params: {}, doc: doc(long) }),
  );
  assert.equal(D.loadDraft({ storage }), null);
  // Ровно лимит — поднимается целиком.
  const ok = "б".repeat(20000);
  D.saveDraft(composer({ doc: doc(ok) }), { storage });
  assert.equal(D.loadDraft({ storage }).doc.blocks[0][0].v.length, 20000);
  // Сохранение сверх лимита не пишет обрезок — черновик стирается.
  assert.equal(D.saveDraft(composer({ doc: doc(long) }), { storage }), false);
  assert.equal(storage.getItem(D.DRAFT_KEY), null);
});

test("параметры и модель — по белому списку", () => {
  const storage = memoryStorage();
  storage.setItem(
    D.DRAFT_KEY,
    JSON.stringify({
      v: 1,
      updated_at: Date.now(),
      kind: "что-то",
      model: "<script>",
      params: {
        duration: "10",
        resolution: "720p",
        aspect_ratio: "javascript:1",
        generate_audio: "yes",
        seed: 1.5,
        negative_prompt: "x".repeat(3000),
        evil: true,
      },
      doc: doc("текст"),
    }),
  );
  const back = D.loadDraft({ storage });
  assert.equal(back.kind, "video");
  assert.equal(back.model, null);
  assert.deepEqual(back.params, { resolution: "720p" });
  assert.deepEqual(
    D.sanitizeDraftParams({ duration: 5, aspect_ratio: "auto", seed: null, negative_prompt: "без текста", generate_audio: false }),
    { duration: 5, aspect_ratio: "auto", seed: null, negative_prompt: "без текста", generate_audio: false },
  );
});

test("картинка остаётся картинкой", () => {
  const storage = memoryStorage();
  D.saveDraft(composer({ kind: "image", model: "google/gemini-2.5-flash-image", params: { aspect_ratio: "1:1" } }), { storage });
  const back = D.loadDraft({ storage });
  assert.equal(back.kind, "image");
  assert.equal(back.model, "google/gemini-2.5-flash-image");
});

test("хранилище недоступно (приватный режим) — ни одна функция не бросает", () => {
  const broken = {
    getItem() {
      throw new Error("SecurityError");
    },
    setItem() {
      throw new Error("QuotaExceededError");
    },
    removeItem() {
      throw new Error("SecurityError");
    },
  };
  assert.equal(D.loadDraft({ storage: broken }), null);
  assert.equal(D.saveDraft(composer(), { storage: broken }), false);
  assert.doesNotThrow(() => D.clearDraft({ storage: broken }));
  // Без window вовсе (node) — тоже тихо.
  assert.equal(D.loadDraft(), null);
  assert.equal(D.saveDraft(composer()), false);
});

test("docHasText и emptyDraftDoc", () => {
  assert.equal(D.docHasText(doc("", "  ")), false);
  assert.equal(D.docHasText(doc("", "кот")), true);
  assert.equal(D.docHasText(null), false);
  assert.deepEqual(D.emptyDraftDoc(), { v: 1, blocks: [[]] });
});
