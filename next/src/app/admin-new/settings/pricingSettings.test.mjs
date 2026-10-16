// Админка, «Цены и наценка»: разбор ответа, черновик формы, тело PATCH/превью (pricingSettings.ts).
// Запуск (Node 22.6+):  node --experimental-strip-types --test src/app/admin-new/settings/pricingSettings.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  changeLines,
  deltaText,
  draftChanges,
  draftFrom,
  errorText,
  flagViews,
  hasErrors,
  modeSwitchExamples,
  parsePricing,
  pinDraft,
  previousMarkup,
  serverErrors,
  typedNumber,
  typedSceneCredits,
} from "./pricingSettings.ts";

// Ответ GET pricing/ из CONTRACT_A_admin.md §1 (сокращённый).
const RAW = {
  mode: "legacy",
  markup_pct: "40",
  floor_pct: "25",
  kgs_per_usd: null,
  live_kgs_per_usd: "87.4",
  rate_warning: false,
  basis: {
    package: "MASTER",
    currency: "KGS",
    price: "4990.00",
    credits: 6500,
    kgs_per_credit: "0.76769",
    credit_usd: "0.0087837",
    kgs_per_usd: "87.4",
    rate_source: "live",
  },
  basis_line: "MASTER · 0,768 сом = $0,00878",
  preview: false,
  effective_markup_pct: "40",
  defaults: { mode: "legacy", markup_pct: "40", floor_pct: "25" },
  limits: { pct_min: "0", pct_max: "1000", rate_min: "1", rate_max: "100000" },
  studio_scene_credits: 0,
  samples: [
    {
      key: "seedance_720_5",
      kind: "video",
      label: "Seedance 2.0 · 5 с 720p",
      model: { id: 1, openrouter_id: "bytedance/seedance-2.0", name: "Seedance 2.0", is_active: true },
      shape: { seconds: 5, resolution: "720p", aspect: "16:9" },
      cost_usd: "0.7623",
      cost_text: "$0,76",
      legacy: 145,
      markup: 122,
      active: 145,
      delta_pct: -15.9,
      after_recompute: null,
      flags: [],
    },
    {
      key: "gpt4o_message",
      kind: "text",
      label: "GPT-4o · сообщение 2000 токенов",
      model: { id: 9 },
      cost_text: "$0,015",
      legacy: 34,
      markup: 34,
      active: 34,
      delta_pct: 0,
      after_recompute: 3,
      flags: ["below_cost"],
    },
    {
      key: "mini_480_5",
      kind: "video",
      label: "Seedance 2.0 Mini · 5 с 480p",
      model: { id: null },
      legacy: 33,
      markup: null,
      active: 33,
      delta_pct: null,
      flags: ["not_in_db", "no_cost"],
    },
    { kind: "video", label: "без ключа — выкидываем" },
  ],
  models_without_cost: [{ id: 4, name: "Sora 2 Pro" }],
  warnings: [{ code: "no_cost", text: "Моделей без себестоимости: 1 (Sora 2 Pro)." }, { code: "x", text: "" }],
};

const saved = () => parsePricing(RAW);

test("parsePricing: поля, примеры, предупреждения", () => {
  const p = saved();
  assert.ok(p);
  assert.equal(p.mode, "legacy");
  assert.equal(p.markupPct, "40");
  assert.equal(p.kgsPerUsd, null);
  assert.equal(p.liveKgsPerUsd, "87.4");
  assert.equal(p.basis?.pkg, "MASTER");
  assert.equal(p.basis?.rateSource, "live");
  assert.equal(p.sceneCredits, 0);
  assert.equal(p.samples.length, 3, "строка без key выброшена");
  assert.deepEqual(p.samples[0], {
    key: "seedance_720_5",
    kind: "video",
    label: "Seedance 2.0 · 5 с 720p",
    modelId: 1,
    costText: "$0,76",
    legacy: 145,
    markup: 122,
    active: 145,
    deltaPct: -15.9,
    afterRecompute: null,
    flags: [],
  });
  assert.equal(p.samples[1].afterRecompute, 3);
  assert.equal(p.samples[2].markup, null);
  assert.equal(p.warnings.length, 1, "пустое предупреждение выброшено");
  assert.equal(p.withoutCost, 1);
  assert.deepEqual(p.limits, { pctMin: 0, pctMax: 1000, rateMin: 1, rateMax: 100000 });
});

test("parsePricing: не карточка → null", () => {
  assert.equal(parsePricing(null), null);
  assert.equal(parsePricing([]), null);
  assert.equal(parsePricing({ detail: "Нет прав" }), null);
  assert.equal(parsePricing({ ...RAW, mode: "other" }), null);
  assert.equal(parsePricing({ ...RAW, markup_pct: "много" }), null);
});

test("draftFrom: числа по-русски, пустой курс — живой", () => {
  const p = parsePricing({ ...RAW, markup_pct: "35.5", kgs_per_usd: "87.5" });
  assert.deepEqual(draftFrom(p), { mode: "legacy", markup: "35,5", floor: "25", rate: "87,5", pin: false });
  assert.equal(draftFrom(saved()).rate, "");
});

test("draftChanges: нетронутая форма — пустое тело", () => {
  const p = saved();
  const { body, errors } = draftChanges(draftFrom(p), p);
  assert.deepEqual(body, {});
  assert.equal(hasErrors(errors), false);
});

test("draftChanges: числа сравниваются как числа, запятая → точка", () => {
  const p = saved();
  const same = draftChanges({ ...draftFrom(p), markup: "40,00", floor: "25.0" }, p);
  assert.deepEqual(same.body, {});
  const changed = draftChanges({ ...draftFrom(p), mode: "markup", markup: "35,5", rate: "87,45" }, p);
  assert.deepEqual(changed.body, { mode: "markup", markup_pct: "35.5", kgs_per_usd: "87.45" });
});

test("draftChanges: ошибки полей как у сервера", () => {
  const p = saved();
  const bad = draftChanges({ ...draftFrom(p), markup: "abc", floor: "1001", rate: "0,5" }, p);
  assert.equal(bad.errors.markup_pct, "Наценка: нужно число от 0 до 1000.");
  assert.equal(bad.errors.floor_pct, "Нижний порог: от 0 до 1000 %.");
  assert.match(bad.errors.kgs_per_usd, /^Курс: сколько сомов за доллар/);
  assert.deepEqual(bad.body, {});
  const places = draftChanges({ ...draftFrom(p), markup: "10,123" }, p);
  assert.equal(places.errors.markup_pct, "Наценка: не больше 2 знаков после запятой.");
  assert.equal(draftChanges({ ...draftFrom(p), markup: "" }, p).errors.markup_pct, "Наценка: нужно число от 0 до 1000.");
});

test("draftChanges: курс — пусто сбрасывает закреплённый, «Закрепить текущий» шлёт pin_live_rate", () => {
  const pinned = parsePricing({ ...RAW, kgs_per_usd: "85" });
  assert.deepEqual(draftChanges({ ...draftFrom(pinned), rate: "" }, pinned).body, { kgs_per_usd: null });

  const live = saved();
  const draft = pinDraft(draftFrom(live), live);
  assert.equal(draft.rate, "87,4");
  assert.equal(draft.pin, true);
  assert.deepEqual(draftChanges(draft, live).body, { pin_live_rate: true });

  // Уже закреплён живой — менять нечего.
  const same = parsePricing({ ...RAW, kgs_per_usd: "87.4" });
  assert.deepEqual(draftChanges(pinDraft(draftFrom(same), same), same).body, {});

  // Живого курса нет — закрепить нельзя.
  const noLive = parsePricing({ ...RAW, live_kgs_per_usd: null });
  assert.equal(pinDraft(draftFrom(noLive), noLive).pin, false);
  const forced = draftChanges({ ...draftFrom(noLive), pin: true }, noLive);
  assert.equal(forced.errors.pin_live_rate, "Живой курс сейчас недоступен — введите курс вручную.");
});

test("serverErrors и errorText: отказ сервера", () => {
  const data = {
    detail: "Режим цен: legacy или markup. Наценка: от 0 до 1000 %.",
    errors: { mode: "Режим цен: legacy или markup.", markup_pct: "Наценка: от 0 до 1000 %.", junk: 1 },
  };
  assert.deepEqual(serverErrors(data), {
    mode: "Режим цен: legacy или markup.",
    markup_pct: "Наценка: от 0 до 1000 %.",
  });
  assert.deepEqual(serverErrors("строка"), {});
  assert.equal(errorText({ status: 400, data }, "x"), data.detail);
  assert.equal(errorText({ status: 500, data: "<html>" }, "Не удалось"), "Не удалось (HTTP 500)");
  assert.match(errorText({ status: 0 }, "x"), /Нет связи/);
});

test("примеры: разница, флаги, «было», окно подтверждения", () => {
  assert.equal(deltaText(-15.9), "−15,9 %");
  assert.equal(deltaText(4), "+4 %");
  assert.equal(deltaText(0), "0 %");
  assert.equal(deltaText(null), null);
  assert.deepEqual(
    flagViews(["below_cost", "new_flag"]).map((f) => f.label),
    ["ниже себестоимости", "new_flag"],
  );
  const p = saved();
  assert.equal(previousMarkup(p, "seedance_720_5"), 122);
  assert.equal(previousMarkup(p, "нет такого"), null);
  assert.deepEqual(modeSwitchExamples(p.samples, "markup"), [
    "Seedance 2.0 · 5 с 720p: 145 кр → 122 кр",
    "Seedance 2.0 Mini · 5 с 480p: 33 кр → не продаётся",
  ]);
  assert.deepEqual(modeSwitchExamples(p.samples, "legacy"), [
    "Seedance 2.0 · 5 с 720p: 122 кр → 145 кр",
    "Seedance 2.0 Mini · 5 с 480p: — → 33 кр",
  ]);
  assert.deepEqual(changeLines({ mode: "markup", markup_pct: "35.5", kgs_per_usd: null }, p), [
    "Наценка: 40 → 35,5 %",
    "Курс: брать живой",
  ]);
  assert.deepEqual(changeLines({ pin_live_rate: true }, p), ["Курс: закрепить живой 87,4 сом/$"]);
});

test("цена сцены: целое от 0 до 100000", () => {
  assert.equal(typedSceneCredits("200"), 200);
  assert.equal(typedSceneCredits(" 0 "), 0);
  assert.equal(typedSceneCredits("100001"), null);
  assert.equal(typedSceneCredits("1,5"), null);
  assert.equal(typedSceneCredits(""), null);
  assert.equal(typedNumber("1e3"), null);
  assert.equal(typedNumber("12,5"), 12.5);
});
