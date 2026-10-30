// Голос героя на карточке сцены: состояния, окно голоса, цена, отказы.
// Запуск (Node 22.6+):  node --experimental-strip-types --test src/components/studio/lineVoice.test.mjs
import "../../lib/vstudio/nodeTsHooks.mjs";
import { test } from "node:test";
import assert from "node:assert/strict";

const lv = await import("./lineVoice.ts");

const BELLA = { voice_id: "bella", voice_name: "Bella - Professional, Bright, Warm", track_id: 7, credits: 5, start_sec: 0.6, stale: false };
const HERO = { character: { id: 3 } };
const PINNED = { 3: { voice_id: "adam", voice_name: "Adam - Dominant, Firm" } };

test("shortVoiceName: имя без описания; странные значения не роняют карточку", () => {
  assert.equal(lv.shortVoiceName("Bella - Professional, Bright, Warm"), "Bella");
  assert.equal(lv.shortVoiceName("Bella"), "Bella");
  assert.equal(lv.shortVoiceName(""), "");
  assert.equal(lv.shortVoiceName(null), "");
});

test("heroVoiceOf: ключ — id героя строкой; героя или голоса нет — null", () => {
  assert.equal(lv.heroVoiceOf(PINNED, HERO).voice_id, "adam");
  assert.equal(lv.heroVoiceOf(PINNED, { character: { id: 4 } }), null);
  assert.equal(lv.heroVoiceOf(PINNED, { character: null }), null);
  assert.equal(lv.heroVoiceOf(undefined, HERO), null);
});

test("нет реплики — ничего, сколько бы ни стоил голос", () => {
  for (const dialogue of ["", "   ", undefined]) {
    assert.deepEqual(lv.lineVoiceView({ status: "ready", dialogue, line_voice: null, line_voice_price: null }), { kind: "none" });
  }
});

test("голос есть: Голос: Имя · Сменить · Вернуть голос модели", () => {
  const view = lv.lineVoiceView({ status: "ready", dialogue: "Ура!", line_voice: BELLA, line_voice_price: 5, ...HERO }, PINNED);
  assert.deepEqual(view, {
    kind: "voice",
    voice: { id: "bella", name: "Bella" },
    canChange: true,
    dubPrice: null,
    canRestore: true,
    stale: false,
  });
});

test("голос есть, режим выключен: сменить нельзя (сервер откажет), вернуть голос модели можно", () => {
  const view = lv.lineVoiceView({ status: "ready", dialogue: "Ура!", line_voice: BELLA, line_voice_price: null });
  assert.equal(view.canChange, false);
  assert.equal(view.canRestore, true);
});

test("дорожка важнее решения режиссёра: озвучено вручную, а пересъёмка решила «описание»", () => {
  const view = lv.lineVoiceView({ status: "ready", dialogue: "Ура!", dialogue_is_speech: false, line_voice: BELLA, line_voice_price: null });
  assert.equal(view.kind, "voice");
  assert.equal(view.voice.name, "Bella");
  assert.equal(view.canChange, false);
});

test("реплику поправили после озвучки: цена новой озвучки и возврат, без строки голоса", () => {
  const view = lv.lineVoiceView({ status: "ready", dialogue: "Новые слова", line_voice: { ...BELLA, stale: true }, line_voice_price: 5 });
  assert.deepEqual(view, { kind: "voice", voice: null, canChange: false, dubPrice: 5, canRestore: true, stale: true });
});

test("реплику стёрли, а дорожка осталась: только вернуть голос модели, иначе старые слова звучат без выхода", () => {
  const view = lv.lineVoiceView({ status: "ready", dialogue: "", line_voice: { ...BELLA, stale: true }, line_voice_price: null });
  assert.deepEqual(view, { kind: "voice", voice: null, canChange: false, dubPrice: null, canRestore: true, stale: true });
});

test("устаревшая дорожка у не готовой сцены: озвучивать нельзя (scene_not_ready), вернуть — можно", () => {
  const view = lv.lineVoiceView({ status: "failed", dialogue: "Новые слова", line_voice: { ...BELLA, stale: true }, line_voice_price: 5 });
  assert.equal(view.dubPrice, null);
  assert.equal(view.canRestore, true);
});

test("описание: подсказка, денег и кнопок нет", () => {
  const view = lv.lineVoiceView({ status: "ready", dialogue: "Он ищет маму", dialogue_is_speech: false, line_voice: null, line_voice_price: null });
  assert.deepEqual(view, { kind: "description" });
});

test("готовая сцена без голоса: кнопка с ценой; голоса героя ещё нет — подберём сами", () => {
  const view = lv.lineVoiceView({ status: "ready", dialogue: "Ура!", dialogue_is_speech: true, line_voice: null, line_voice_price: 5, ...HERO });
  assert.deepEqual(view, { kind: "voice", voice: null, canChange: true, dubPrice: 5, canRestore: false, stale: false });
});

test("готовая сцена без голоса: голос героя закреплён — он и в строке", () => {
  const view = lv.lineVoiceView({ status: "ready", dialogue: "Ура!", line_voice: null, line_voice_price: 5, ...HERO }, PINNED);
  assert.deepEqual(view.voice, { id: "adam", name: "Adam" });
  assert.equal(view.dubPrice, 5);
});

test("цены нет при реплике — ничего нового (режим off, staff не для него, нет ключа)", () => {
  for (const line_voice_price of [null, undefined]) {
    assert.deepEqual(lv.lineVoiceView({ status: "ready", dialogue: "Ура!", line_voice: null, line_voice_price, ...HERO }), { kind: "none" });
  }
});

test("черновик и ошибка: голос выбирается заранее, кнопки озвучки нет (сервер ответил бы scene_not_ready)", () => {
  for (const status of ["draft", "failed"]) {
    const view = lv.lineVoiceView({ status, dialogue: "Ура!", line_voice: null, line_voice_price: 5, ...HERO }, PINNED);
    assert.equal(view.dubPrice, null);
    assert.equal(view.canChange, true);
    assert.equal(view.voice.name, "Adam");
  }
  assert.deepEqual(lv.lineVoiceView({ status: "draft", dialogue: "Ура!", line_voice: null, line_voice_price: 5, character: null }), { kind: "none" });
});

test("снимающаяся сцена: ничего", () => {
  for (const status of ["new", "keyframe", "video"]) {
    assert.deepEqual(lv.lineVoiceView({ status, dialogue: "Ура!", line_voice: null, line_voice_price: null, ...HERO }), { kind: "none" });
  }
});

test("гость: новых полей у сцены нет — ничего", () => {
  assert.deepEqual(lv.lineVoiceView({ status: "draft", dialogue: "Ура!", ...HERO }), { kind: "none" });
});

test("окно голоса: готовая сцена озвучивается, до съёмки голос только закрепляется", () => {
  assert.equal(lv.voiceDialogMode({ status: "ready" }), "dub");
  assert.equal(lv.voiceDialogMode({ status: "draft" }), "pin");
  assert.equal(lv.voiceDialogMode({ status: "failed" }), "pin");
});

test("окно голоса: отмечен тот, что звучит, иначе голос героя, иначе ничего", () => {
  assert.equal(lv.pickedVoice({ status: "ready", line_voice: BELLA, ...HERO }, PINNED), "bella");
  assert.equal(lv.pickedVoice({ status: "ready", line_voice: null, ...HERO }, PINNED), "adam");
  assert.equal(lv.pickedVoice({ status: "ready", line_voice: null, ...HERO }, {}), "");
});

test("окно голоса: тот же голос ничего не меняет — кнопка не платная и не жмётся", () => {
  const voiced = { status: "ready", line_voice: BELLA, ...HERO };
  assert.equal(lv.voiceChoiceIsNew(voiced, PINNED, ""), false);
  assert.equal(lv.voiceChoiceIsNew(voiced, PINNED, "bella"), false);
  assert.equal(lv.voiceChoiceIsNew(voiced, PINNED, "adam"), true);
  // Слова устарели — переозвучка тем же голосом имеет смысл.
  assert.equal(lv.voiceChoiceIsNew({ ...voiced, line_voice: { ...BELLA, stale: true } }, PINNED, "bella"), true);
  // Голоса ещё нет — озвучить можно и голосом героя.
  assert.equal(lv.voiceChoiceIsNew({ status: "ready", line_voice: null, ...HERO }, PINNED, "adam"), true);
  const draft = { status: "draft", line_voice: null, ...HERO };
  assert.equal(lv.voiceChoiceIsNew(draft, PINNED, "adam"), false);
  assert.equal(lv.voiceChoiceIsNew(draft, PINNED, "bella"), true);
});

test("linePrice: как audio.voice_price — минимум 5 кр до 250 знаков, дальше по тарифу", () => {
  const prices = { voice_per_1k: 20, voice_min: 5 };
  assert.equal(lv.linePrice("Ура!", prices), 5);
  assert.equal(lv.linePrice("а".repeat(250), prices), 5);
  assert.equal(lv.linePrice("а".repeat(251), prices), 6);
  assert.equal(lv.linePrice("   ", prices), 0);
  assert.equal(lv.linePrice("Ура!", null), 0);
});

test("guestLineCredits: голос в цене гостя, если озвучка включена и реплика есть", () => {
  const config = { line_voice: true, prices: { voice_per_1k: 20, voice_min: 5 } };
  assert.equal(lv.guestLineCredits("Ура!", config), 5);
  assert.equal(lv.guestLineCredits("", config), 0);
  // Режим staff или off: голоса в цене нет, хотя ключ есть и озвучка вообще работает.
  assert.equal(lv.guestLineCredits("Ура!", { ...config, line_voice: false }), 0);
  assert.equal(lv.guestLineCredits("Ура!", { prices: config.prices }), 0);
  assert.equal(lv.guestLineCredits("Ура!", null), 0);
});

test("lineRefusal: по-русски — текст сервера", () => {
  assert.deepEqual(lv.lineRefusal("ru", 400, { detail: "Такого голоса нет в списке" }), {
    key: "studio_ui.line_err",
    detail: "Такого голоса нет в списке",
  });
});

test("lineRefusal: en и kg — свой текст по коду, русский текст сервера не показываем", () => {
  const cases = [
    ["no_dialogue", "studio_ui.line_err_no_dialogue"],
    ["not_speech", "studio_ui.line_err_not_speech"],
    ["scene_not_ready", "studio_ui.line_err_not_ready"],
    ["line_voice_off", "studio_ui.line_err_off"],
    ["scene_busy", "studio_ui.scene_err_busy"],
  ];
  for (const [error_code, key] of cases) {
    assert.deepEqual(lv.lineRefusal("en", 400, { detail: "Русский текст", error_code }), { key });
    assert.deepEqual(lv.lineRefusal("kg", 400, { detail: "Русский текст", error_code }), { key });
  }
});

test("lineRefusal: отказы без кода — по статусу; пустой ответ не роняет", () => {
  assert.equal(lv.lineRefusal("en", 429, { detail: "Сцена уже сводится" }).key, "studio_ui.line_err_busy");
  assert.equal(lv.lineRefusal("kg", 503, { detail: "Голоса недоступны" }).key, "studio_ui.line_err_voices");
  assert.equal(lv.lineRefusal("en", 502, { detail: "Сбой" }).key, "studio_ui.line_err");
  assert.deepEqual(lv.lineRefusal("ru", 500, null), { key: "studio_ui.line_err" });
  assert.deepEqual(lv.lineRefusal("ru", 0, "<html>"), { key: "studio_ui.line_err" });
});

test("Тексты голоса есть во всех языках, en и kg — переведены, подстановки те же", async () => {
  const fs = await import("node:fs");
  const read = (lang) =>
    JSON.parse(fs.readFileSync(new URL(`../../locales/${lang}/common.json`, import.meta.url), "utf8")).studio_ui;
  const ph = (s) => (String(s).match(/\{\{\w+\}\}/g) || []).sort().join();
  const ru = read("ru");
  const keys = Object.keys(ru).filter((k) => /^(line_|hero_voice_|audio_tab_line$|audio_track_line$|dialogue_)/.test(k));
  keys.push("voiceall_own_lines", "voiceall_line_voiced", "voiceall_descriptions", "voiceall_nothing", "voiceall_unshot",
    "voiceall_nothing_unshot", "voiceall_nothing_working", "voiceall_nothing_descriptions", "voiceall_nothing_voiced");
  assert.ok(keys.length >= 30, `ключей: ${keys.length}`);
  for (const lang of ["en", "kg"]) {
    const other = read(lang);
    for (const key of keys) {
      assert.equal(typeof other[key], "string", `${lang} ${key}: нет перевода`);
      assert.equal(ph(other[key]), ph(ru[key]), `${lang} ${key}: подстановки`);
      // Счётчик знаков — без слов: в нём совпасть может, остальное — нет.
      if (key !== "dialogue_fit") assert.notEqual(other[key], ru[key], `${lang} ${key}: не переведено`);
    }
  }
  // Спека: подсказка поля слово в слово.
  assert.match(ru.dialogue_hint, /^Слова героя — прямая речь, как он скажет вслух/);
  // Всё, что может вернуть lineRefusal, лежит в локали.
  for (const body of ["no_dialogue", "not_speech", "scene_not_ready", "line_voice_off", "scene_busy", "x"]) {
    for (const status of [400, 429, 503, 502]) {
      const key = lv.lineRefusal("en", status, { error_code: body }).key.replace("studio_ui.", "");
      assert.equal(typeof ru[key], "string", key);
    }
  }
});

test("emptyPlanKey: своё объяснение по коду, неизвестный код — общее «Озвучивать нечего»", () => {
  assert.equal(lv.emptyPlanKey("unshot"), "studio_ui.voiceall_nothing_unshot");
  assert.equal(lv.emptyPlanKey("voiced"), "studio_ui.voiceall_nothing_voiced");
  assert.equal(lv.emptyPlanKey("empty"), "studio_ui.voiceall_nothing");
  assert.equal(lv.emptyPlanKey(undefined), "studio_ui.voiceall_nothing");
});
