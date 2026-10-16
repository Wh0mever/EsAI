// Админка, «Модели»: разбор строк и каталога, правка строки, пересчёт тарифов текста и картинок в чате (modelsAdmin.ts).
// Запуск (Node 22.6+):  node --experimental-strip-types --test src/app/admin-new/models/modelsAdmin.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  addBody,
  addProblem,
  applicable,
  applyBody,
  appliedCount,
  catalogUrl,
  coefText,
  defaultPicked,
  errorText,
  existingId,
  flagViews,
  formFromModel,
  isFluxModel,
  keepPicked,
  kindOf,
  legacyStudioText,
  matchesModel,
  modeOf,
  parseAdded,
  parseCatalog,
  parseModel,
  parseModels,
  parseRecompute,
  previewFromRefusal,
  RECOMPUTE_COPY,
  recomputeUrl,
  replaceModel,
  rowChanges,
  tariffIgnored,
  tariffUnit,
  touchesPrice,
} from "./modelsAdmin.ts";

// Строки GET models/ из CONTRACT_A_admin.md §2.
const SEEDANCE = {
  id: 1,
  name: "Seedance 2.0",
  openrouter_id: "bytedance/seedance-2.0",
  description: "",
  markup_coefficient: 0,
  category: "video",
  recommended: true,
  free_tier: false,
  supports_vision: false,
  is_active: true,
  sort_order: 10,
  cartoon_stage: "video",
  vstudio_enabled: true,
  vstudio_overrides: {},
  markup_pct: null,
  unit_cost_usd: null,
  ref_cost_usd: null,
  pricing: {
    kind: "video",
    shape: { seconds: 5, resolution: "720p", aspect: "16:9" },
    cost_usd: "0.7623",
    legacy: 145,
    markup: 122,
    active: 145,
    mode: "legacy",
    flags: [],
    markup_source: "global",
    effective_markup_pct: "40",
    text: null,
  },
  cost_sample: "$0,76 · 5 с 720p",
  price_sample: "145 кр · 5 с 720p",
  price_sample_other: "при наценке: 122 кр",
  vstudio_supported: true,
};

const FLEX = {
  ...SEEDANCE,
  id: 7,
  name: "FLUX Flex",
  openrouter_id: "black-forest-labs/flux.2-flex",
  markup_coefficient: 12,
  category: "image",
  cartoon_stage: "",
  vstudio_enabled: false,
  markup_pct: 60,
  unit_cost_usd: 0.06,
  ref_cost_usd: 0.06,
  sort_order: 20,
  pricing: { ...SEEDANCE.pricing, kind: "image", mode: "markup", markup_source: "model", effective_markup_pct: "60" },
};

const GPT = {
  ...SEEDANCE,
  id: 9,
  name: "GPT-4o",
  openrouter_id: "openai/gpt-4o",
  markup_coefficient: 17,
  category: "chat",
  is_active: false,
  sort_order: 5,
  pricing: null,
  cost_sample: null,
  vstudio_supported: false,
};

test("parseModel: поля и вычисляемые колонки", () => {
  const m = parseModel(SEEDANCE);
  assert.ok(m);
  assert.equal(m.openrouterId, "bytedance/seedance-2.0");
  assert.equal(m.markupCoefficient, 0);
  assert.equal(m.vstudioEnabled, true);
  assert.equal(m.vstudioSupported, true);
  assert.equal(m.markupPct, null);
  assert.equal(m.pricing?.kind, "video");
  assert.equal(m.pricing?.legacy, 145);
  assert.equal(m.pricing?.markupSource, "global");
  assert.equal(m.costSample, "$0,76 · 5 с 720p");
  assert.equal(m.priceSampleOther, "при наценке: 122 кр");
  // DRF может отдать Decimal строкой — это тоже число.
  assert.equal(parseModel({ ...FLEX, markup_coefficient: "12.000", unit_cost_usd: "0.039" })?.unitCostUsd, 0.039);
  assert.equal(parseModel({ name: "без id" }), null);
  assert.equal(parseModel(GPT)?.pricing, null);
});

test("parseModels: не список → null, мусор выкидывается", () => {
  assert.equal(parseModels({ detail: "x" }), null);
  assert.deepEqual(
    parseModels([SEEDANCE, null, { id: "x" }]).map((m) => m.id),
    [1],
  );
});

test("kindOf, modeOf, порядок, поиск", () => {
  assert.equal(kindOf("video"), "video");
  assert.equal(kindOf("image"), "image");
  assert.equal(kindOf("coding"), "text");
  const list = parseModels([SEEDANCE, FLEX, GPT]);
  assert.equal(modeOf(list), "legacy");
  assert.equal(modeOf([parseModel(GPT)]), null);
  const sorted = replaceModel(list, { ...list[2], sortOrder: 15 });
  assert.deepEqual(
    sorted.map((m) => m.id),
    [1, 9, 7],
  );
  assert.deepEqual(
    replaceModel(list, { ...list[0], id: 99, sortOrder: 1 }).map((m) => m.id)[0],
    99,
  );
  assert.equal(matchesModel(list[0], "SEEDANCE"), true);
  assert.equal(matchesModel(list[0], "bytedance/"), true);
  assert.equal(matchesModel(list[0], "flux"), false);
  assert.equal(matchesModel(list[0], "  "), true);
});

test("errorText: detail-словарь сериализатора и строка", () => {
  assert.equal(
    errorText({ status: 400, data: { detail: { markup_pct: ["Наценка: не больше 2 знаков после запятой"] } } }, "x"),
    "Наценка: не больше 2 знаков после запятой",
  );
  assert.equal(
    errorText({ status: 400, data: { detail: { a: ["Один"], b: "Два", c: ["Один"] } } }, "x"),
    "Один Два",
  );
  assert.equal(errorText({ status: 409, data: { detail: "Модель уже есть.", model_id: 13 } }, "x"), "Модель уже есть.");
  assert.equal(errorText({ status: 502, data: null }, "Не удалось"), "Не удалось (HTTP 502)");
  assert.match(errorText({ status: 0 }, "x"), /Нет связи/);
});

test("rowChanges: нетронутая строка — пустое тело", () => {
  for (const raw of [SEEDANCE, FLEX, GPT]) {
    const m = parseModel(raw);
    assert.deepEqual(rowChanges(m, formFromModel(m)), { body: {}, error: null });
  }
  assert.equal(formFromModel(parseModel(FLEX)).unitCost, "0,06");
});

test("rowChanges: числа с запятой, пусто — null, только изменённое", () => {
  const m = parseModel(FLEX);
  const f = { ...formFromModel(m), coefficient: "12,0", markupPct: "", unitCost: "0,039", refCost: "0.06" };
  assert.deepEqual(rowChanges(m, f).body, { markup_pct: null, unit_cost_usd: "0.039" });
  const toggles = { ...formFromModel(m), isActive: false, vstudioEnabled: true, category: "image" };
  assert.deepEqual(rowChanges(m, toggles).body, { is_active: false, vstudio_enabled: true });
  const s = parseModel(SEEDANCE);
  assert.deepEqual(rowChanges(s, { ...formFromModel(s), markupPct: "35,5", coefficient: "1" }).body, {
    markup_coefficient: 1,
    markup_pct: "35.5",
  });
});

test("rowChanges: ошибки — тело не уходит", () => {
  const m = parseModel(FLEX);
  const base = formFromModel(m);
  assert.equal(rowChanges(m, { ...base, coefficient: "" }).error, "Тариф: число от 0 до 999,999");
  assert.equal(rowChanges(m, { ...base, coefficient: "1,2345" }).error, "Тариф: не больше 3 знаков после запятой");
  assert.equal(rowChanges(m, { ...base, markupPct: "1001" }).error, "Наценка: от 0 до 1000 %; пусто — общая наценка");
  assert.equal(rowChanges(m, { ...base, markupPct: "10,555" }).error, "Наценка: не больше 2 знаков после запятой");
  assert.match(rowChanges(m, { ...base, unitCost: "-1" }).error, /^Себестоимость картинки/);
  assert.equal(
    rowChanges(m, { ...base, refCost: "0,0000001" }).error,
    "Себестоимость входного фото: не больше 6 знаков после запятой",
  );
});

test("rowChanges: себестоимость картинки не уходит у не-картинок", () => {
  const s = parseModel(SEEDANCE);
  const f = { ...formFromModel(s), unitCost: "0,5" };
  assert.deepEqual(rowChanges(s, f).body, {});
  const m = parseModel(FLEX);
  const moved = { ...formFromModel(m), category: "chat", unitCost: "1" };
  assert.deepEqual(rowChanges(m, moved).body, { category: "chat" });
});

test("touchesPrice и tariffIgnored", () => {
  assert.equal(touchesPrice({ recommended: true }), false);
  assert.equal(touchesPrice({ markup_pct: "10" }), true);
  const s = parseModel(SEEDANCE);
  assert.equal(tariffIgnored(s, formFromModel(s)), false, "legacy: тариф действует");
  const markupVideo = parseModel({ ...SEEDANCE, pricing: { ...SEEDANCE.pricing, mode: "markup" } });
  assert.equal(tariffIgnored(markupVideo, formFromModel(markupVideo)), true);
  const flex = parseModel(FLEX);
  assert.equal(tariffIgnored(flex, formFromModel(flex)), true, "картинка с себестоимостью");
  const noCost = parseModel({ ...FLEX, unit_cost_usd: null });
  assert.equal(tariffIgnored(noCost, formFromModel(noCost)), false, "картинка без себестоимости — по тарифу");
});

// Nano Banana: студии берут за картинку, чат — токены × тариф в обоих режимах (A_FIX).
const NANO = {
  ...FLEX,
  id: 8,
  name: "Nano Banana",
  openrouter_id: "google/gemini-2.5-flash-image",
  markup_coefficient: 4,
  markup_pct: null,
  unit_cost_usd: 0.039,
  ref_cost_usd: null,
  pricing: { ...FLEX.pricing, mode: "markup", markup_source: "global", effective_markup_pct: "40" },
};

test("isFluxModel — как is_flux_image_model на сервере", () => {
  assert.equal(isFluxModel("black-forest-labs/flux.2-flex"), true);
  assert.equal(isFluxModel("Black-Forest-Labs/FLUX.1-dev:free"), true);
  assert.equal(isFluxModel("acme/flux.2-pro"), true);
  assert.equal(isFluxModel("google/gemini-2.5-flash-image"), false);
  assert.equal(isFluxModel(""), false);
});

test("тариф Nano Banana действует в чате и в режиме «наценка»", () => {
  const nano = parseModel(NANO);
  const form = formFromModel(nano);
  assert.equal(tariffIgnored(nano, form), false, "в чате по токенам × тариф");
  assert.equal(tariffUnit(nano, form), "в чате — кр за 1000 токенов; в студиях — по себестоимости");
  const legacy = parseModel({ ...NANO, pricing: { ...NANO.pricing, mode: "legacy" } });
  assert.equal(tariffUnit(legacy, formFromModel(legacy)), "в чате — кр за 1000 токенов; в студиях — кр за картинку");
  const noCost = parseModel({ ...NANO, unit_cost_usd: null });
  assert.equal(tariffUnit(noCost, formFromModel(noCost)), "в чате — кр за 1000 токенов; в студиях — кр за картинку");
  // FLUX и остальные виды — прежние единицы.
  const flex = parseModel(FLEX);
  assert.equal(tariffUnit(flex, formFromModel(flex)), "кр за картинку");
  const s = parseModel(SEEDANCE);
  assert.equal(tariffUnit(s, formFromModel(s)), "кр за 1 с (720p)");
  assert.equal(tariffUnit(nano, { ...form, category: "chat" }), "кр за 1000 токенов");
  assert.deepEqual(
    flagViews(["chat_below_cost"]).map((f) => [f.label, f.tone]),
    [["в чате ниже себестоимости", "fail"]],
  );
});

const CATALOG = {
  results: [
    {
      openrouter_id: "bytedance/seedance-2.0-mini",
      name: "Seedance 2.0 Mini",
      full_name: "ByteDance: Seedance 2.0 Mini",
      kind: "video",
      category: "video",
      exists: false,
      model_id: null,
      is_active: null,
      vstudio_supported: true,
      supports_vision: false,
      description: "",
      shape: { seconds: 5, resolution: "720p", aspect: "16:9" },
      cost_usd: "0.38115",
      cost_text: "$0,38 · 5 с 720p",
      price_markup: 61,
      coefficient: null,
    },
    {
      openrouter_id: "anthropic/claude-opus",
      name: "Claude Opus",
      kind: "text",
      category: "chat",
      exists: true,
      model_id: 13,
      is_active: false,
      cost_text: "$15,00 / $75,00 за 1M",
      price_markup: 30,
      coefficient: "8.990",
    },
    { openrouter_id: "x/strange", kind: "audio" },
  ],
  count: 3,
  truncated: false,
  catalogs: { video: "ok", text: "unavailable" },
};

test("каталог: адрес, разбор, тело добавления", () => {
  assert.equal(catalogUrl("", ""), "manage/models/catalog/");
  assert.equal(catalogUrl(" seedance mini ", "video"), "manage/models/catalog/?q=seedance+mini&kind=video");
  const c = parseCatalog(CATALOG);
  assert.ok(c);
  assert.equal(c.results.length, 2, "неизвестный вид выкинут");
  assert.deepEqual(c.unavailable, ["text"]);
  const [mini, opus] = c.results;
  assert.equal(mini.priceMarkup, 61);
  assert.equal(opus.exists, true);
  assert.equal(opus.modelId, 13);
  assert.equal(opus.isActive, false);
  assert.equal(opus.coefficient, "8.990");
  assert.equal(parseCatalog({ results: "x" }), null);

  assert.deepEqual(addBody(mini, "Seedance 2.0 Mini", "video"), { openrouter_id: "bytedance/seedance-2.0-mini" });
  assert.deepEqual(addBody(mini, " Mini ", "chat"), { openrouter_id: "bytedance/seedance-2.0-mini", name: "Mini" });
  assert.deepEqual(addBody({ ...opus, exists: false }, "", "coding"), {
    openrouter_id: "anthropic/claude-opus",
    category: "coding",
  });
  assert.equal(addProblem(opus, ""), "Модель «Claude Opus» уже есть в списке.");
  assert.equal(addProblem(mini, "x".repeat(101)), "Название длиннее 100 символов.");
  assert.equal(addProblem(mini, "Mini"), null);
});

test("ответ добавления и отказ 409", () => {
  const added = parseAdded({ model: SEEDANCE, warnings: ["Модель добавлена выключенной.", 5, ""] });
  assert.equal(added?.model.id, 1);
  assert.deepEqual(added?.warnings, ["Модель добавлена выключенной."]);
  assert.equal(parseAdded({ warnings: [] }), null);
  assert.equal(existingId({ detail: "Модель уже есть.", model_id: 13 }), 13);
  assert.equal(existingId(null), null);
});

const RECOMPUTE = {
  mode: "markup",
  can_apply: true,
  apply_blocked: null,
  markup_pct: "40",
  floor_pct: "25",
  basis_line: "MASTER · 0,768 сом = $0,00878",
  tokens: 2000,
  catalog: "ok",
  rows: [
    {
      id: 9,
      name: "GPT-4o",
      openrouter_id: "openai/gpt-4o",
      category: "chat",
      is_active: true,
      old_coefficient: "17.000",
      new_coefficient: "1.224",
      old_message_credits: 34,
      new_message_credits: 3,
      delta_pct: -91.2,
      prompt_per_m: "2.5",
      completion_per_m: "10",
      price_text: "$2,50 / $10,00 за 1M",
      markup_pct: "40",
      markup_source: "global",
      status: "ok",
    },
    { id: 10, name: "DeepSeek", old_coefficient: "0.112", new_coefficient: "0.112", status: "unchanged" },
    { id: 11, name: "Нет цены", old_coefficient: "1.000", new_coefficient: null, status: "no_price" },
    { id: 12, name: "Новая", old_coefficient: "1.000", new_coefficient: "8.990", status: "ok", is_active: false },
  ],
  summary: { ok: 2, unchanged: 1, no_price: 1 },
};

test("пересчёт тарифов: разбор, отметки, тело", () => {
  assert.equal(recomputeUrl(), "manage/models/text-recompute/");
  assert.equal(recomputeUrl([12, 15]), "manage/models/text-recompute/?ids=12,15");
  const p = parseRecompute(RECOMPUTE);
  assert.ok(p);
  assert.equal(p.canApply, true);
  assert.equal(p.rows.length, 4);
  assert.deepEqual(
    p.rows.map(applicable),
    [true, false, false, true],
  );
  const picked = defaultPicked(p);
  assert.deepEqual([...picked], [9, 12]);
  picked.delete(12);
  assert.deepEqual(applyBody(p, picked), { confirm: true, items: [{ id: 9, coefficient: "1.224" }] });
  assert.equal(coefText("17.000"), "17");
  assert.equal(coefText("1.224"), "1,224");
  assert.equal(parseRecompute({ rows: "x" }), null);
});

test("пересчёт тарифов: 409 со свежим предпросмотром сохраняет отметки", () => {
  const fresh = {
    ...RECOMPUTE,
    rows: [
      { ...RECOMPUTE.rows[0], new_coefficient: "1.300" },
      { ...RECOMPUTE.rows[3], new_coefficient: null, status: "no_price" },
    ],
  };
  const refusal = { detail: "Цены изменились с момента предпросмотра…", preview: fresh };
  const p = previewFromRefusal(refusal);
  assert.ok(p);
  assert.deepEqual([...keepPicked(new Set([9, 12]), p)], [9]);
  assert.deepEqual(applyBody(p, new Set([9, 12])).items, [{ id: 9, coefficient: "1.300" }]);
  assert.equal(previewFromRefusal({ detail: "x" }), null);
  assert.equal(appliedCount({ updated: [{ id: 9 }], preview: {} }), 1);
  assert.equal(appliedCount(null), 0);
});

const CHAT_IMAGE_RECOMPUTE = {
  kind: "chat_image",
  mode: "markup",
  can_apply: true,
  apply_blocked: null,
  markup_pct: "40",
  floor_pct: "25",
  basis_line: "MASTER · 0,768 сом = $0,00878",
  tokens: 1450,
  rows: [
    {
      id: 4,
      name: "Nano Banana",
      openrouter_id: "google/gemini-2.5-flash-image",
      category: "image",
      is_active: true,
      old_coefficient: "4.000",
      new_coefficient: "4.827",
      old_message_credits: 6,
      new_message_credits: 7,
      delta_pct: 16.7,
      price_text: "$0,039 за картинку · по наценке 7 кр",
      cost_usd: "0.039",
      studio_credits: 7,
      legacy_studio_old: 4,
      legacy_studio_new: 4,
      markup_pct: "40",
      markup_source: "global",
      status: "ok",
    },
    {
      id: 5,
      name: "Nano Banana Pro",
      old_coefficient: "12.000",
      new_coefficient: "15.172",
      old_message_credits: 18,
      new_message_credits: 22,
      legacy_studio_old: 12,
      legacy_studio_new: 15,
      status: "ok",
    },
    { id: 6, name: "Nano Banana 2", old_coefficient: "6.000", new_coefficient: null, status: "no_cost" },
  ],
  summary: { ok: 2, no_cost: 1 },
};

test("тариф картинок в чате: свой адрес, разбор, строки «в студиях по-старому»", () => {
  assert.equal(recomputeUrl([], "chat_image"), "manage/models/chat-image-recompute/");
  assert.equal(recomputeUrl([6], "chat_image"), "manage/models/chat-image-recompute/?ids=6");
  const p = parseRecompute(CHAT_IMAGE_RECOMPUTE);
  assert.ok(p);
  assert.equal(p.kind, "chat_image");
  assert.equal(p.tokens, 1450);
  assert.equal(p.catalogOk, true);
  assert.deepEqual(
    p.rows.map((r) => [r.status, applicable(r)]),
    [
      ["ok", true],
      ["ok", true],
      ["no_cost", false],
    ],
  );
  assert.deepEqual(applyBody(p, defaultPicked(p)), {
    confirm: true,
    items: [
      { id: 4, coefficient: "4.827" },
      { id: 5, coefficient: "15.172" },
    ],
  });
  assert.equal(legacyStudioText(p.rows[0]), "в студиях по-старому — 4 кр, без изменений");
  assert.equal(legacyStudioText(p.rows[1]), "в студиях по-старому — 12 → 15 кр");
  assert.equal(legacyStudioText(p.rows[2]), null);
  // Без kind — тарифы текста, как раньше.
  assert.equal(parseRecompute(RECOMPUTE)?.kind, "text");
  assert.equal(parseRecompute({ kind: "chat_image", rows: [] })?.tokens, 1450);
  assert.match(RECOMPUTE_COPY.chat_image.subtitle(1450), /~1450 токенов/);
  assert.equal(RECOMPUTE_COPY.text.subtitle(2000).endsWith("за сообщение в 2000 токенов."), true);
});

test("флаг «в чате не по наценке»", () => {
  const [view] = flagViews(["chat_tariff_stale"]);
  assert.equal(view.label, "в чате не по наценке");
  assert.equal(view.tone, "wait");
  assert.match(view.title, /Пересчитать тариф картинок в чате/);
});
