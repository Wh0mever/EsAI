// Мультстудия, нижний док: «примагничивание», цены строк и карточек, «Итого», черновик гостя.
// Запуск (Node 22.6+):  node --experimental-strip-types --test src/components/studio/*.test.mjs
import "../../lib/vstudio/nodeTsHooks.mjs";
import { test } from "node:test";
import assert from "node:assert/strict";

const dl = await import("./dockLogic.ts");
const sd = await import("../../lib/studioDraft.ts");

// Ответ GET cartoon/models/ из CONTRACT_C §3.1: markup 40 %, кадр Nano Banana 7 кр.
const table = (rows) => Object.fromEntries(Object.entries(rows).map(([r, cells]) => [r, cells]));
const MINI = {
  id: "bytedance/seedance-2.0-mini",
  name: "Seedance 2.0 Mini",
  short: "Seedance Mini",
  badge: "",
  locked: false,
  eta_s: 150,
  caps: {
    durations: [4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15],
    resolutions: ["480p", "720p"],
    aspect_ratios: ["16:9", "9:16", "1:1"],
    audio: true,
    seed: false,
    negative: false,
    frames: ["first_frame", "last_frame"],
    refs: { image: 0 },
    frames_with_refs: "soft_pin",
    ref_forces_duration: null,
    prompt: { soft_words: 150, hard_chars: 6000, lang: "en" },
    rejects_real_faces: true,
    min_ref_px: 300,
  },
  defaults: { duration: 5, resolution: "480p", aspect_ratio: "16:9" },
  frame_credits: 7,
  price: {
    table: table({ "480p": { 4: 29, 5: 35, 10: 61, 15: 88 }, "720p": { 4: 56, 5: 68, 10: 128, 15: 189 } }),
    by_aspect: {
      "16:9": table({ "480p": { 4: 29, 5: 35, 10: 61, 15: 88 }, "720p": { 4: 56, 5: 68, 10: 128, 15: 189 } }),
      "9:16": table({ "480p": { 4: 29, 5: 35, 10: 61, 15: 88 }, "720p": { 4: 56, 5: 68, 10: 128, 15: 189 } }),
      "1:1": table({ "480p": { 5: 23, 10: 39 }, "720p": { 5: 42, 10: 77 } }),
    },
  },
  price_from: 29,
};
const S20 = {
  ...MINI,
  id: "bytedance/seedance-2.0",
  name: "Seedance 2.0",
  short: "Seedance 2.0",
  caps: { ...MINI.caps, resolutions: ["480p", "720p", "1080p", "4K"] },
  price: {
    table: table({ "720p": { 5: 129, 10: 249, 15: 370 }, "1080p": { 5: 300 } }),
    by_aspect: {
      "16:9": table({ "720p": { 5: 129, 10: 249, 15: 370 }, "1080p": { 5: 300 } }),
      "1:1": table({ "720p": { 5: 76 } }),
    },
  },
  price_from: 129,
};
const S25 = {
  ...MINI,
  id: "bytedance/seedance-2.5",
  name: "Seedance 2.5",
  short: "Seedance 2.5",
  caps: { ...MINI.caps, durations: Array.from({ length: 27 }, (_, i) => i + 4), resolutions: ["480p", "720p"] },
  price: { table: table({ "720p": { 5: 193, 30: 999 } }), by_aspect: { "16:9": table({ "720p": { 5: 193, 30: 999 } }) } },
};
// Цены нет (markup без себестоимости): ни ключа price, ни «от».
const FAST_OFF = { ...MINI, id: "bytedance/seedance-2.0-fast", short: "Seedance Fast", price: undefined, price_from: null, price_unavailable: true };
const MODELS = [MINI, FAST_OFF, S20, S25];
const RESP = {
  aspect_ratio: "16:9",
  aspects: ["16:9", "9:16", "1:1"],
  models: MODELS,
  defaults: { video_model: MINI.id, resolution: "480p", duration: 5, source: "settings" },
  frame_credits: 7,
};

test("clampDuration: ближайшая, при равенстве — короче (как pricing.clamp_duration)", () => {
  assert.equal(dl.clampDuration([4, 6, 8], 5), 4);
  assert.equal(dl.clampDuration([4, 6, 8], 7), 6);
  assert.equal(dl.clampDuration([4, 5, 15], 20), 15);
  assert.equal(dl.clampDuration([4, 5, 15], 1), 4);
  assert.equal(dl.clampDuration([10], 5), 10);
  assert.equal(dl.clampDuration([], 7), 7);
  // Пусто — длительность кода (5 с), как на сервере.
  assert.equal(dl.clampDuration([4, 5, 6], null), 5);
});

test("clampResolution: то же без регистра, иначе ближайшее по высоте, при равенстве — ниже", () => {
  assert.equal(dl.clampResolution(["480p", "720p", "1080p", "4K"], "4k"), "4K");
  assert.equal(dl.clampResolution(["480p", "720p"], "1080p"), "720p");
  assert.equal(dl.clampResolution(["480p", "720p"], "4K"), "720p");
  assert.equal(dl.clampResolution(["480p", "1080p"], "900p"), "1080p");
  assert.equal(dl.clampResolution(["480p", "1080p"], "768p"), "480p");
  // 600p — посередине между 480p и 720p: берём ниже (дешевле).
  assert.equal(dl.clampResolution(["480p", "720p"], "600p"), "480p");
  assert.equal(dl.clampResolution(["480p", "720p"], "2k"), "720p");
  assert.equal(dl.clampResolution(["720p"], ""), "720p");
  assert.equal(dl.resHeight("1k"), 1080);
  assert.equal(dl.resHeight("abc"), 0);
});

test("switchModel: значения остаются, если модель их умеет; иначе ближайшие и сообщение", () => {
  const cur = { video_model: S20.id, resolution: "1080p", duration: 10 };
  const res = dl.switchModel(MODELS, cur, MINI.id);
  assert.deepEqual(res.settings, { video_model: MINI.id, resolution: "720p", duration: 10 });
  assert.deepEqual(res.notices, [
    { key: "studio_ui.dock_clamp_resolution", params: { model: "Seedance Mini", from: "1080p", to: "720p" } },
  ]);
  assert.equal(dl.fillDock(res.notices[0].key, res.notices[0].params), "Seedance Mini не снимает в 1080p — выбрано 720p");

  // 2.5 снимает до 30 с, Mini — до 15: 20 с превращаются в 15 с.
  const long = dl.switchModel(MODELS, { video_model: S25.id, resolution: "720p", duration: 20 }, MINI.id);
  assert.deepEqual(long.settings, { video_model: MINI.id, resolution: "720p", duration: 15 });
  assert.equal(dl.fillDock(long.notices[0].key, long.notices[0].params), "Seedance Mini не снимает 20 с — выбрано 15 с");

  // Без прежних значений — значения модели по умолчанию, без сообщений.
  const fresh = dl.switchModel(MODELS, null, S20.id);
  assert.deepEqual(fresh.settings, { video_model: S20.id, resolution: "480p", duration: 5 });
  assert.deepEqual(fresh.notices, []);

  // Регистр качества не повод для сообщения.
  const k4 = dl.switchModel(MODELS, { video_model: MINI.id, resolution: "4k", duration: 5 }, S20.id);
  assert.equal(k4.settings.resolution, "4K");
  assert.deepEqual(k4.notices, []);

  assert.equal(dl.switchModel(MODELS, cur, "nope/model"), null);
});

test("withResolution / withDuration: только то, что модель умеет", () => {
  const cur = { video_model: MINI.id, resolution: "480p", duration: 5 };
  assert.deepEqual(dl.withResolution(MODELS, cur, "720P"), { ...cur, resolution: "720p" });
  assert.equal(dl.withResolution(MODELS, cur, "1080p"), null);
  assert.deepEqual(dl.withDuration(MODELS, cur, 12), { ...cur, duration: 12 });
  assert.equal(dl.withDuration(MODELS, cur, 20), null);
  assert.deepEqual(dl.dockBody({ ...cur, extra: 1 }), cur);
  assert.ok(dl.sameDock(cur, { ...cur }));
  assert.ok(!dl.sameDock(cur, { ...cur, duration: 6 }));
  assert.ok(dl.sameDock(null, undefined));
});

test("sanitizeDock: черновик под нынешний список моделей", () => {
  const dock = { video_model: S20.id, resolution: "1080p", duration: 20 };
  assert.deepEqual(dl.sanitizeDock(dock, MODELS), { video_model: S20.id, resolution: "1080p", duration: 15 });
  assert.deepEqual(dl.sanitizeDock({ ...dock, video_model: MINI.id }, MODELS), { video_model: MINI.id, resolution: "720p", duration: 15 });
  // Модель выключили — значения по умолчанию.
  assert.equal(dl.sanitizeDock({ ...dock, video_model: "gone/model" }, MODELS), null);
  // Список ещё не пришёл — как есть.
  assert.deepEqual(dl.sanitizeDock(dock, null), dock);
  assert.equal(dl.sanitizeDock(null, MODELS), null);
});

test("tablePrice: сцена = кадр + видео по формату; с готовым кадром — только видео", () => {
  // PLAN §4.3: Mini 480p 5 с 16:9 = 35, с кадром из запаса — 28; квадрат дешевле.
  assert.equal(dl.tablePrice(MINI, { resolution: "480p", duration: 5, aspect: "16:9" }), 35);
  assert.equal(dl.tablePrice(MINI, { resolution: "480p", duration: 5, aspect: "16:9", keyframeReady: true }), 28);
  assert.equal(dl.tablePrice(MINI, { resolution: "480p", duration: 5, aspect: "1:1" }), 23);
  assert.equal(dl.tablePrice(MINI, { resolution: "720P", duration: 10, aspect: "9:16" }), 128);
  assert.equal(dl.tablePrice(S20, { resolution: "720p", duration: 5, aspect: "16:9" }), 129);
  // Нет клетки или нет цены — null, а не «0 кр».
  assert.equal(dl.tablePrice(MINI, { resolution: "1080p", duration: 5, aspect: "16:9" }), null);
  assert.equal(dl.tablePrice(FAST_OFF, { resolution: "480p", duration: 5, aspect: "16:9" }), null);
  assert.equal(dl.tablePrice(null, { resolution: "480p", duration: 5, aspect: "16:9" }), null);
});

test("modelsForAspect: таблица и «от N» — формата мультфильма", () => {
  const sq = dl.modelsForAspect(MODELS, "1:1");
  const mini = sq.find((m) => m.id === MINI.id);
  assert.deepEqual(mini.price.table, MINI.price.by_aspect["1:1"]);
  assert.equal(mini.price_from, 23);
  // Модель без цены остаётся как есть.
  assert.equal(sq.find((m) => m.id === FAST_OFF.id), FAST_OFF);
  // Исходный список не трогаем.
  assert.equal(MINI.price_from, 29);
});

test("значения по умолчанию: явные только из настроек админки", () => {
  assert.deepEqual(dl.explicitDefaults(RESP), { video_model: MINI.id, resolution: "480p", duration: 5 });
  const preset = { ...RESP, defaults: { video_model: S20.id, resolution: "720p", duration: 5, source: "preset" } };
  assert.equal(dl.explicitDefaults(preset), null);
  assert.deepEqual(dl.displayDefaults(preset), { video_model: S20.id, resolution: "720p", duration: 5 });
  const empty = { ...RESP, defaults: { video_model: null, resolution: null, duration: null, source: "preset" } };
  assert.deepEqual(dl.displayDefaults(empty), { video_model: MINI.id, resolution: "480p", duration: 5 });
  assert.equal(dl.displayDefaults(null), null);
  assert.equal(dl.completeDock({ video_model: MINI.id, resolution: "", duration: 5 }), null);
});

test("adjustedNotices: ответ сервера — сообщениями дока, номер сцены по ленте", () => {
  const notes = dl.adjustedNotices(
    [
      { field: "resolution", from: "1080p", to: "720p", message: "…" },
      { field: "duration", scene: 12, from: 20, to: 15 },
      { field: "duration", from: 3, to: 4 },
      { field: "other", from: 1, to: 2 },
    ],
    "Seedance Mini",
    (id) => (id === 12 ? 2 : null),
  );
  assert.deepEqual(
    notes.map((n) => dl.fillDock(n.key, n.params)),
    [
      "Seedance Mini не снимает в 1080p — выбрано 720p",
      "Сцена 3: 20 с не снять — выбрано 15 с",
      "Seedance Mini не снимает 3 с — выбрано 4 с",
    ],
  );
  assert.deepEqual(dl.adjustedNotices(undefined, "x", () => 0), []);
});

test("clampSceneDurations: свои длительности черновика под новую модель", () => {
  const { scenes, notices } = dl.clampSceneDurations([{ duration: 20 }, {}, { duration: 10 }], MINI.caps.durations);
  assert.deepEqual(scenes, [{ duration: 15 }, {}, { duration: 10 }]);
  assert.deepEqual(notices.map((n) => dl.fillDock(n.key, n.params)), ["Сцена 1: 20 с не снять — выбрано 15 с"]);
});

test("presetsQuery: мультфильм, явные настройки гостя или как раньше", () => {
  const p = dl.presetsQuery({ lang: "ru", aspect: "9:16", projectId: 7, saved: { video_model: MINI.id, resolution: "480p", duration: 5 } });
  assert.equal(p.query, "lang=ru&aspect_ratio=9%3A16&project=7");
  const p2 = dl.presetsQuery({ lang: "ru", aspect: "9:16", projectId: 7, saved: { video_model: MINI.id, resolution: "720p", duration: 5 } });
  assert.notEqual(p.key, p2.key);

  const g = dl.presetsQuery({ lang: "en", aspect: "16:9", explicit: { video_model: MINI.id, resolution: "480p", duration: 5 } });
  assert.equal(g.query, "lang=en&aspect_ratio=16%3A9&video_model=bytedance%2Fseedance-2.0-mini&resolution=480p&duration=5");

  const n = dl.presetsQuery({ lang: "kg", aspect: "1:1" });
  assert.equal(n.query, "lang=kg&aspect_ratio=1%3A1");
  // Ключ меняется с форматом и языком.
  assert.notEqual(n.key, dl.presetsQuery({ lang: "kg", aspect: "16:9" }).key);
  assert.notEqual(n.key, dl.presetsQuery({ lang: "ru", aspect: "1:1" }).key);
});

test("cardEstimate: видео из таблицы + кадр этой сцены", () => {
  const dock = { video_model: MINI.id, resolution: "480p", duration: 5 };
  assert.deepEqual(dl.cardEstimate(MINI, dock, "16:9", 7, 7), { credits: 35, duration: 5 });
  // У сцены другой художник кадра (4 кр): 28 видео + 4.
  assert.deepEqual(dl.cardEstimate(MINI, dock, "16:9", 4, 7), { credits: 32, duration: 5 });
  assert.deepEqual(dl.cardEstimate(MINI, dock, "1:1", 7, 7), { credits: 23, duration: 5 });
  assert.equal(dl.cardEstimate(MINI, null, "16:9", 7), null);
  assert.equal(dl.cardEstimate(S20, dock, "16:9", 7), null);
  assert.equal(dl.cardEstimate(FAST_OFF, { ...dock, video_model: FAST_OFF.id }, "16:9", 7), null);
});

test("guestRowPrice: карточка, таблица, своя длительность и готовый кадр", () => {
  const base = { model: MINI, resolution: "480p", duration: 5, aspect: "16:9", custom: false, ownDuration: false, keyframe: false, frameCredits: 7 };
  // Витрина посчитана под эти настройки — её число и берём.
  assert.deepEqual(dl.guestRowPrice({ ...base, cardCredits: 36 }), { full: 36, render: 36 });
  // С кадром из запаса — только видео.
  assert.deepEqual(dl.guestRowPrice({ ...base, cardCredits: 36, keyframe: true }), { full: 36, render: 29 });
  // Витрина ещё не пересчитана — таблица.
  assert.deepEqual(dl.guestRowPrice({ ...base }), { full: 35, render: 35 });
  // Своя длительность — только таблица (карточка посчитана под длительность дока).
  assert.deepEqual(dl.guestRowPrice({ ...base, duration: 10, ownDuration: true, cardCredits: 35 }), { full: 61, render: 61 });
  // Своя сцена — по таблице «типичной сцены».
  assert.deepEqual(dl.guestRowPrice({ ...base, custom: true, frameCredits: undefined, frameFallback: 7 }), { full: 35, render: 35 });
  // Цены нет — null, «Снять» выключено.
  assert.deepEqual(dl.guestRowPrice({ ...base, model: FAST_OFF, custom: true }), { full: null, render: null });
  assert.deepEqual(dl.guestRowPrice({ ...base, cardCredits: null }), { full: null, render: null });
  // Модель не умеет такую длительность, а карточка есть — карточка.
  assert.deepEqual(dl.guestRowPrice({ ...base, duration: 30, cardCredits: undefined }), { full: null, render: null });
});

test("timelineTotal: сумма строк к съёмке; без цены хоть у одной — итога нет", () => {
  const scenes = [
    { status: "draft", render_credits: 35 },
    { status: "failed", render_credits: 28 },
    { status: "ready", render_credits: 28 },
    { status: "video", render_credits: 35 },
  ];
  assert.deepEqual(dl.timelineTotal(scenes), { credits: 63, count: 2 });
  assert.deepEqual(dl.timelineTotal([...scenes, { status: "draft", render_credits: null }]), { credits: null, count: 3 });
  assert.deepEqual(dl.timelineTotal([{ status: "draft", render_credits: 35, price_unavailable: true }]), { credits: null, count: 1 });
  assert.deepEqual(dl.timelineTotal([{ status: "ready", render_credits: 35 }]), { credits: 0, count: 0 });
  assert.deepEqual(dl.toShoot(scenes).length, 2);
});

test("durationChoices и подписи", () => {
  assert.deepEqual(dl.durationChoices([4, 5, 6], 5), [4, 5, 6]);
  assert.deepEqual(dl.durationChoices([4, 5, 6], 20), [4, 5, 6, 20]);
  assert.deepEqual(dl.durationChoices(null, null), []);
  assert.equal(dl.configLabel({ model_name: "Seedance Mini", resolution: "480p" }), "Seedance Mini · 480p");
  assert.equal(dl.configLabel(null), "");
  assert.equal(dl.compactModelLabel("Seedance Mini"), "Mini");
  assert.equal(dl.compactModelLabel("Seedance 2.0"), "2.0");
  assert.equal(dl.compactModelLabel("Veo 3"), "Veo 3");
  assert.equal(dl.modelLabel(MINI), "Seedance Mini");
  assert.equal(dl.modelLabel({ name: "X" }), "X");
});

test("тексты дока: подстановки на месте, без хвостов", () => {
  for (const key of Object.keys(dl.DOCK_RU)) {
    const text = dl.fillDock(key, { n: 1, model: "M", from: 1, to: 2, credits: 3, count: 4, config: "C" });
    assert.ok(!/\{\{/.test(text), `${key}: ${text}`);
  }
});

/* ------------------------------------------------------------------ */
/* Черновик гостя                                                      */
/* ------------------------------------------------------------------ */

function withStorage(fn) {
  const store = new Map();
  const prev = globalThis.window;
  globalThis.window = {
    localStorage: {
      getItem: (k) => (store.has(k) ? store.get(k) : null),
      setItem: (k, v) => store.set(k, String(v)),
      removeItem: (k) => store.delete(k),
    },
  };
  try {
    return fn(store);
  } finally {
    globalThis.window = prev;
  }
}

test("черновик гостя хранит настройки дока, формат, реплики и длительности сцен", () => {
  withStorage(() => {
    const draft = {
      ...sd.emptyDraft(3),
      aspect_ratio: "9:16",
      video_model: MINI.id,
      resolution: "720p",
      duration: 10,
      scenes: [
        { key: "a", preset_id: 5, character_id: 3, dialogue: "Привет!", duration: 12 },
        { key: "b", preset_id: 0, character_id: null, custom_text: "Лис бежит" },
      ],
    };
    sd.saveDraft(draft);
    const back = sd.loadDraft();
    assert.equal(back.aspect_ratio, "9:16");
    assert.equal(back.video_model, MINI.id);
    assert.equal(back.resolution, "720p");
    assert.equal(back.duration, 10);
    assert.equal(back.scenes[0].dialogue, "Привет!");
    assert.equal(back.scenes[0].duration, 12);
    assert.equal(back.scenes[1].duration, undefined);
    assert.equal(back.scenes[1].custom_text, "Лис бежит");
    assert.deepEqual(sd.draftDock(back), { video_model: MINI.id, resolution: "720p", duration: 10 });
  });
});

test("черновик гостя: мусор в настройках не ломает ленту", () => {
  withStorage((store) => {
    store.set(
      "esai.studio.draft.v1",
      JSON.stringify({
        id: "d1",
        character_id: 2,
        aspect_ratio: "4:3",
        video_model: 42,
        resolution: "очень длинное качество",
        duration: 999,
        scenes: [{ key: "a", preset_id: 5, duration: "x", dialogue: 7 }],
        updated_at: Date.now(),
      }),
    );
    const back = sd.loadDraft();
    assert.equal(back.aspect_ratio, undefined);
    assert.equal(back.video_model, undefined);
    assert.equal(back.resolution, undefined);
    assert.equal(back.duration, undefined);
    assert.equal(back.scenes.length, 1);
    assert.equal(back.scenes[0].duration, undefined);
    assert.equal(back.scenes[0].dialogue, undefined);
    assert.equal(sd.draftDock(back), null);
  });
});

test("черновик гостя: тело переноса после входа несёт настройки только если их выбрали", () => {
  const draft = {
    ...sd.emptyDraft(3),
    scenes: [
      { key: "a", preset_id: 5, character_id: 3, duration: 12 },
      { key: "b", preset_id: 0, character_id: 3, custom_text: "Лис бежит", dialogue: "Ура" },
    ],
  };
  const plain = sd.importBody(draft);
  assert.equal("video_model" in plain, false);
  assert.equal(plain.aspect_ratio, "16:9");
  assert.deepEqual(plain.scenes, [
    { preset_id: 5, character_id: 3, duration: 12 },
    { preset_id: 0, character_id: 3, custom_text: "Лис бежит", dialogue: "Ура" },
  ]);
  const chosen = sd.importBody({ ...draft, aspect_ratio: "1:1", video_model: MINI.id, resolution: "480p", duration: 5 });
  assert.equal(chosen.aspect_ratio, "1:1");
  assert.equal(chosen.video_model, MINI.id);
  assert.equal(chosen.resolution, "480p");
  assert.equal(chosen.duration, 5);
});

test("«Снять» шлёт цену с кнопки; отказ 409 price_changed узнаётся и называет новую цену", () => {
  // Цена строки — то, что видел человек: её и сверяет сервер.
  assert.deepEqual(dl.quoteBody(35), { quoted_credits: 35 });
  assert.deepEqual(dl.quoteBody(0), { quoted_credits: 0 });
  // Цены нет или она странная — тело как раньше, без цены.
  for (const bad of [null, undefined, -1, 1.5, Number.NaN, Number.POSITIVE_INFINITY]) {
    assert.deepEqual(dl.quoteBody(bad), {}, String(bad));
  }
  const refusal = {
    detail: "Цена изменилась: теперь 905 кр. Проверьте и нажмите «Снять» ещё раз.",
    error_code: "price_changed",
    credits: 905,
    quoted: 35,
  };
  assert.deepEqual(dl.priceChanged(409, refusal), { credits: 905 });
  assert.deepEqual(dl.priceChanged(409, { ...refusal, credits: "905" }), { credits: null });
  // Другие отказы — не «цена изменилась»: 402 ведёт в окно покупки, 409 без кода — обычная ошибка.
  assert.equal(dl.priceChanged(402, { ...refusal, required: 905 }), null);
  assert.equal(dl.priceChanged(409, { detail: "x" }), null);
  assert.equal(dl.priceChanged(409, null), null);
  assert.equal(dl.priceChanged(409, "price_changed"), null);
  assert.equal(dl.priceChanged(200, refusal), null);
  // Текст на сайте — тот же, что у сервера (ru — defaultValue ключа).
  assert.equal(dl.fillDock("studio_ui.scene_price_changed", { credits: 905 }), refusal.detail);
});

test("«Снять» у уже снятой сцены: 409 already_shot узнаётся; ↻ шлёт состояние строки", () => {
  const refusal = {
    detail: "Сцена уже снята — переснять можно кнопкой «Переснять»",
    error: "Сцена уже снята — переснять можно кнопкой «Переснять»",
    error_code: "already_shot",
    scene: { id: 1, status: "ready" },
  };
  assert.equal(dl.alreadyShot(409, refusal), true);
  // Другие отказы — не «уже снята».
  assert.equal(dl.alreadyShot(409, { ...refusal, error_code: "price_changed" }), false);
  assert.equal(dl.alreadyShot(400, refusal), false);
  assert.equal(dl.alreadyShot(409, null), false);
  assert.equal(dl.alreadyShot(409, "already_shot"), false);
  assert.equal(dl.priceChanged(409, refusal), null);
  // Текст на сайте — тот же, что у сервера.
  assert.equal(dl.fillDock("studio_ui.scene_already_shot"), refusal.detail);

  // ↻ у строки «ошибка»: сервер не заменит ролик, если сцену с тех пор пересняли.
  assert.deepEqual(dl.retryBody(28, "failed"), { retry: true, quoted_credits: 28, expect_status: "failed" });
  // У готовой строки человек уже подтвердил пересъёмку.
  assert.deepEqual(dl.retryBody(35, "ready"), { retry: true, quoted_credits: 35, expect_status: "ready" });
  // Цены нет — без неё, как раньше; непонятное состояние сервер не получает.
  assert.deepEqual(dl.retryBody(null, "failed"), { retry: true, expect_status: "failed" });
  assert.deepEqual(dl.retryBody(28, "video"), { retry: true, quoted_credits: 28 });
});

// ------------------------------------------------------------ C_POLISH ---

test("Касание дока у мультфильма без своих настроек шлёт только тронутое (длительности сцен не пинятся)", () => {
  const next = { video_model: "bytedance/seedance-2.0-mini", resolution: "480p", duration: 5 };
  const empty = { video_model: null, resolution: null, duration: null };
  // Качество: модель — та, что в доке (без неё качество не имеет смысла); длительность не уходит.
  assert.deepEqual(dl.dockPatch(empty, next, "resolution"), { video_model: next.video_model, resolution: "480p" });
  // Модель: только модель — качество и длительность сцен остаются как в библиотеке.
  assert.deepEqual(dl.dockPatch(empty, next, "video_model"), { video_model: next.video_model });
  // Длительность человек выбрал сам — её и шлём (для сцен без своей).
  assert.deepEqual(dl.dockPatch(empty, next, "duration"), { video_model: next.video_model, duration: 5 });
  assert.deepEqual(dl.dockPatch(null, next, "duration"), { video_model: next.video_model, duration: 5 });
  // Свои настройки у мультфильма уже есть: подогнанные к новой модели значения едут вместе с ней.
  const own = { video_model: "bytedance/seedance-2.0", resolution: "1080p", duration: 15 };
  assert.deepEqual(dl.dockPatch(own, { ...next, resolution: "720p", duration: 15 }, "video_model"),
    { video_model: next.video_model, resolution: "720p", duration: 15 });
  assert.deepEqual(dl.dockPatch(own, { ...own, resolution: "720p" }, "resolution"),
    { resolution: "720p", duration: 15 });
  // Своя только модель: качество и длительность по-прежнему пустые.
  assert.deepEqual(dl.dockPatch({ ...empty, video_model: own.video_model }, { ...own, resolution: "720p" }, "resolution"),
    { resolution: "720p" });
});

test("Отказ сервера: по-русски — его текст, на en/kg — свой по error_code", () => {
  const body = { detail: "Seedance Mini снимает от 4 до 15 секунд", error_code: "unsupported_duration" };
  assert.deepEqual(dl.refusalText("ru", body, "studio_ui.dock_save_failed"),
    { key: "studio_ui.dock_save_failed", detail: body.detail });
  assert.deepEqual(dl.refusalText("en", body, "studio_ui.dock_save_failed"), { key: "studio_ui.dock_err_value" });
  assert.deepEqual(dl.refusalText("kg", { error_code: "model_unavailable" }, "studio_ui.dock_save_failed"),
    { key: "studio_ui.dock_err_model" });
  assert.deepEqual(dl.refusalText("en", { error_code: "caps_unavailable" }, "studio_ui.dock_save_failed"),
    { key: "studio_ui.dock_err_caps" });
  assert.deepEqual(dl.refusalText("en", { error_code: "scene_busy" }, "studio_ui.scene_save_failed"),
    { key: "studio_ui.scene_err_busy" });
  // Незнакомый код, пустой ответ, сбой сети — общий текст.
  assert.deepEqual(dl.refusalText("en", { detail: "boom" }, "studio_ui.scene_save_failed"), { key: "studio_ui.scene_save_failed" });
  assert.deepEqual(dl.refusalText("ru", null, "studio_ui.dock_save_failed"), { key: "studio_ui.dock_save_failed" });
  assert.deepEqual(dl.refusalText("ru", "<html>", "studio_ui.dock_save_failed"), { key: "studio_ui.dock_save_failed" });
});

test("Вопрос о пересъёмке ради длительности называет модель и качество, если они другие", () => {
  const was = { video_model: "bytedance/seedance-2.0", model_name: "Seedance 2.0", resolution: "720p" };
  const now = { video_model: "bytedance/seedance-2.0-mini", model_name: "Seedance Mini", resolution: "480p" };
  const q = dl.reshootDurationQuestion({ shot: was, next: now, from: 5, to: 10, credits: 54 });
  assert.equal(q.key, "studio_ui.scene_reshoot_duration_cfg");
  assert.equal(dl.fillDock(q.key, q.params),
    "Сцена снята на 5 с (Seedance 2.0 · 720p). Чтобы она стала 10 с, её нужно переснять — новая съёмка: " +
      "Seedance Mini · 480p за 54 кр, нынешний ролик заменится. Переснять?");
  // Только качество другое — тоже называем.
  assert.equal(dl.reshootDurationQuestion({ shot: was, next: { ...was, resolution: "1080p" }, from: 5, to: 10, credits: 9 }).key,
    "studio_ui.scene_reshoot_duration_cfg");
  // То же самое — короткий вопрос, с ценой и тоже о том, что ролик заменится.
  const same = dl.reshootDurationQuestion({ shot: now, next: now, from: 5, to: 10, credits: 54 });
  assert.equal(same.key, "studio_ui.scene_reshoot_duration");
  assert.match(dl.fillDock(same.key, same.params), /54 кр, нынешний ролик заменится/);
  // Чем снята — неизвестно: короткий вопрос, а не выдуманное «было».
  assert.equal(dl.reshootDurationQuestion({ shot: null, next: now, from: 5, to: 10, credits: 54 }).key,
    "studio_ui.scene_reshoot_duration");
});

test("Вопрос о пересъёмке ради длительности называет и смену формата после съёмки", () => {
  const was = { video_model: "bytedance/seedance-2.0-mini", model_name: "Seedance Mini", resolution: "480p", aspect_ratio: "16:9" };
  const q = dl.reshootDurationQuestion({ shot: was, next: { ...was, aspect_ratio: "9:16" }, from: 5, to: 10, credits: 61 });
  assert.equal(q.key, "studio_ui.scene_reshoot_duration_fmt");
  assert.equal(dl.fillDock(q.key, q.params),
    "Сцена снята на 5 с (Seedance Mini · 480p, формат 16:9). Чтобы она стала 10 с, её нужно переснять — новая съёмка: " +
      "Seedance Mini · 480p в формате 9:16 за 61 кр, нынешний ролик заменится. Переснять?");
  // Формат сменился и модель тоже — один вопрос называет всё.
  const both = dl.reshootDurationQuestion({
    shot: { ...was, video_model: "bytedance/seedance-2.0", model_name: "Seedance 2.0", resolution: "720p" },
    next: { ...was, aspect_ratio: "1:1" }, from: 5, to: 10, credits: 39,
  });
  assert.equal(both.key, "studio_ui.scene_reshoot_duration_fmt");
  assert.match(dl.fillDock(both.key, both.params), /\(Seedance 2\.0 · 720p, формат 16:9\).*Seedance Mini · 480p в формате 1:1/);
  // Формат тот же (или у снимка его нет) — прежние варианты.
  assert.equal(dl.reshootDurationQuestion({ shot: was, next: was, from: 5, to: 10, credits: 61 }).key,
    "studio_ui.scene_reshoot_duration");
  const noAspect = { video_model: was.video_model, model_name: was.model_name, resolution: was.resolution };
  assert.equal(dl.reshootDurationQuestion({ shot: noAspect, next: { ...was, aspect_ratio: "9:16" }, from: 5, to: 10, credits: 61 }).key,
    "studio_ui.scene_reshoot_duration");
});

test("Отказы съёмки: известные коды — своим текстом на en/kg, незнакомый — текст сервера (keepDetail)", () => {
  const cases = {
    price_unavailable: "studio_ui.scene_err_price",
    invalid_quote: "studio_ui.scene_err_quote",
    invalid_expect_status: "studio_ui.scene_err_stale",
    scene_changed: "studio_ui.scene_err_changed",
    already_shot: "studio_ui.scene_already_shot",
  };
  for (const [code, key] of Object.entries(cases)) {
    const body = { detail: "Русский текст сервера", error_code: code };
    assert.deepEqual(dl.refusalText("en", body, "studio_ui.scene_save_failed", true), { key });
    assert.deepEqual(dl.refusalText("kg", body, "studio_ui.scene_save_failed"), { key });
    // По-русски — по-прежнему точный текст сервера.
    assert.deepEqual(dl.refusalText("ru", body, "studio_ui.scene_save_failed", true),
      { key: "studio_ui.scene_save_failed", detail: "Русский текст сервера" });
  }
  // Кода нет («опишите сцену по-другому»): keepDetail — текст сервера, без него — общий.
  const rejected = { detail: "Опишите сцену по-другому", rejected: true };
  assert.deepEqual(dl.refusalText("en", rejected, "studio_ui.err_tryon", true),
    { key: "studio_ui.err_tryon", detail: "Опишите сцену по-другому" });
  assert.deepEqual(dl.refusalText("en", rejected, "studio_ui.err_tryon"), { key: "studio_ui.err_tryon" });
  // Ни кода, ни текста (сбой сети) — общий текст.
  assert.deepEqual(dl.refusalText("kg", null, "studio_ui.err_tryon", true), { key: "studio_ui.err_tryon" });
});

test("«Цена изменилась» уходит, когда цену строки перечитали и она другая", () => {
  const notes = {
    1: { text: "теперь 54", tone: "error", price: 54 },
    2: { text: "теперь 40", tone: "error", price: 40 },
    3: { text: "не сохранилось", tone: "error" },
    4: { text: "теперь 61 (за другую длительность)", tone: "error", price: null },
    5: { text: "уже снята", tone: "info" },
    6: { text: "теперь 70", tone: "error", price: 70 },
  };
  const scenes = [
    { id: 1, render_credits: 54, preset: { credits: 61 } }, // та же цена — сообщение верно
    { id: 2, render_credits: 35, preset: { credits: 42 } }, // док сменили — цена другая
    { id: 3, render_credits: 10 },
    { id: 4, render_credits: 28 },
    { id: 5, render_credits: 28 },
    // строки 6 больше нет (удалили)
  ];
  // Опрос: уходят 2 и 6; без числа (4) остаётся — его снимет только правка дока.
  assert.deepEqual(Object.keys(dl.settlePriceNotes(notes, scenes, false)), ["1", "3", "4", "5"]);
  // Сохранили док или формат: уходит и сообщение без числа.
  assert.deepEqual(Object.keys(dl.settlePriceNotes(notes, scenes, true)), ["1", "3", "5"]);
  // Цена без render_credits — по карточке; ничего не ушло — тот же объект (без лишней перерисовки).
  const kept = { 1: { text: "теперь 61", tone: "error", price: 61 } };
  assert.equal(dl.settlePriceNotes(kept, [{ id: 1, preset: { credits: 61 } }], true), kept);
});

test("Тексты дока лежат в локалях: ru байт в байт, en/kg есть, подстановки те же", async () => {
  const fs = await import("node:fs");
  const read = (lang) =>
    JSON.parse(fs.readFileSync(new URL(`../../locales/${lang}/common.json`, import.meta.url), "utf8"));
  const at = (root, key) => key.split(".").reduce((node, part) => node?.[part], root);
  const ph = (s) => (String(s).match(/\{\{\w+\}\}/g) || []).sort().join();
  const locales = { ru: read("ru"), en: read("en"), kg: read("kg") };
  for (const [key, ru] of Object.entries(dl.DOCK_RU)) {
    assert.equal(at(locales.ru, key), ru, `ru ${key}`);
    for (const lang of ["en", "kg"]) {
      const value = at(locales[lang], key);
      assert.equal(typeof value, "string", `${lang} ${key}: нет перевода`);
      assert.equal(ph(value), ph(ru), `${lang} ${key}: подстановки`);
    }
  }
});

test("Реплика: 13 знаков в секунду снимка, но не меньше 40 и не больше 300 знаков сервера", () => {
  assert.equal(dl.dialogueMaxLength(5), 65);
  assert.equal(dl.dialogueMaxLength(2), 40);
  assert.equal(dl.dialogueMaxLength(23), 299);
  assert.equal(dl.dialogueMaxLength(24), 300);
  assert.equal(dl.dialogueMaxLength(30), 300);
  assert.equal(dl.dialogueMaxLength(undefined), 65);
  assert.equal(dl.dialogueMaxLength(Number.NaN), 65);
});

test("Длина ролика для звука: снятая — по съёмке, не снятая — как снимется", () => {
  // Готовая сцена снята на 5 с, док уже на 10 с: трек меряем по ролику.
  assert.equal(dl.clipSeconds({ status: "ready", shot: { duration: 5 }, config: { duration: 10 }, preset: { duration: 10 } }), 5);
  assert.equal(dl.clipSeconds({ status: "video", shot: { duration: 8 }, config: { duration: 8 }, preset: { duration: 8 } }), 8);
  // Черновик — как снимется (снимка нет или он прошлый).
  assert.equal(dl.clipSeconds({ status: "draft", shot: { duration: 5 }, config: { duration: 12 }, preset: { duration: 12 } }), 12);
  assert.equal(dl.clipSeconds({ status: "failed", shot: null, config: null, preset: { duration: 7 } }), 7);
  assert.equal(dl.clipSeconds({ status: "ready", shot: null, config: { duration: 6 }, preset: {} }), 6);
  assert.equal(dl.clipSeconds(null), 5);
});

test("Правки мультфильма уходят по одной и в порядке нажатий; сбой не рвёт очередь", async () => {
  const enqueue = dl.serialQueue();
  const log = [];
  let release;
  const first = enqueue(() => new Promise((resolve) => {
    log.push("start A");
    release = () => {
      log.push("end A");
      resolve("A");
    };
  }));
  const second = enqueue(async () => {
    log.push("start B");
    throw new Error("B failed");
  });
  const third = enqueue(async () => {
    log.push("start C");
    return "C";
  });
  await new Promise((r) => setTimeout(r, 5));
  // Пока A не вернулся, B и C не ушли.
  assert.deepEqual(log, ["start A"]);
  release();
  assert.equal(await first, "A");
  await assert.rejects(second, /B failed/);
  assert.equal(await third, "C");
  assert.deepEqual(log, ["start A", "end A", "start B", "start C"]);
});
