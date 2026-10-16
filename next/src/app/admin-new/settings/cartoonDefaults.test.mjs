// Админка, «Мультстудия: по умолчанию»: разбор ответа, смена модели, тело PATCH (cartoonDefaults.ts).
// Запуск (Node 22.6+):  node --experimental-strip-types --test src/app/admin-new/settings/cartoonDefaults.test.mjs
import "../../../lib/vstudio/nodeTsHooks.mjs";
import { test } from "node:test";
import assert from "node:assert/strict";

const cd = await import("./cartoonDefaults.ts");

const DUR_15 = [4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15];
// Ответ GET manage/defaults/ из CONTRACT_C §3.8 (c1_logs/examples.json, defaults_get).
const RAW = {
  model: "bytedance/seedance-2.0-mini",
  resolution: "480p",
  duration: 5,
  stored: { model: false, resolution: false, duration: false },
  code_defaults: { model: "bytedance/seedance-2.0-mini", resolution: "480p", duration: 5 },
  effective: { video_model: "bytedance/seedance-2.0-mini", resolution: "480p", duration: 5, source: "settings" },
  models: [
    { id: "bytedance/seedance-2.0-mini", name: "Seedance 2.0 Mini", short: "Seedance Mini", exists: true, active: true, offered: true, resolutions: ["480p", "720p"], durations: DUR_15 },
    { id: "bytedance/seedance-2.0-fast", name: "Seedance 2.0 Fast", short: "Seedance Fast", exists: true, active: false, offered: false, resolutions: ["480p", "720p"], durations: DUR_15 },
    { id: "bytedance/seedance-2.0", name: "Seedance 2.0", short: "Seedance 2.0", exists: true, active: true, offered: true, resolutions: ["480p", "720p", "1080p", "4K"], durations: DUR_15 },
    { id: "bytedance/seedance-2.5", name: "Seedance 2.5", short: "Seedance 2.5", exists: false, active: false, offered: false, resolutions: [], durations: [] },
  ],
  warnings: [],
};

test("parseDefaults: ответ сервера → карточка; мусор не роняет", () => {
  const d = cd.parseDefaults(RAW);
  assert.equal(d.model, "bytedance/seedance-2.0-mini");
  assert.equal(d.duration, 5);
  assert.equal(d.models.length, 4);
  assert.equal(d.effective.source, "settings");
  assert.ok(cd.allFromCode(d));
  assert.deepEqual(cd.draftFrom(d), { model: "bytedance/seedance-2.0-mini", resolution: "480p", duration: 5 });

  assert.equal(cd.parseDefaults(null), null);
  assert.equal(cd.parseDefaults({ model: "x", resolution: "480p", duration: "5" }), null);
  const odd = cd.parseDefaults({ ...RAW, models: [null, { id: 3 }, { id: "a", durations: [5, "6", 7.5] }], warnings: [1, "w"] });
  assert.equal(odd.models.length, 1);
  assert.deepEqual(odd.models[0].durations, [5]);
  assert.deepEqual(odd.warnings, ["w"]);
});

test("состояние модели и подписи", () => {
  const d = cd.parseDefaults(RAW);
  assert.equal(cd.modelNote(d.models[0]), "");
  assert.equal(cd.modelNote(d.models[1]), "выключена");
  assert.equal(cd.modelNote(d.models[3]), "нет в «Моделях»");
  assert.equal(cd.effectiveText(d), "Новые мультфильмы снимаются: Seedance Mini · 480p · 5 с.");
  const fallback = cd.parseDefaults({
    ...RAW,
    effective: { video_model: "bytedance/seedance-2.0", resolution: "720p", duration: 5, source: "preset" },
  });
  assert.equal(
    cd.effectiveText(fallback),
    "Новые мультфильмы снимаются как в сцене библиотеки (сейчас это Seedance 2.0 · 720p · 5 с).",
  );
});

test("списки значений: что умеет модель, а без каталога — привычные", () => {
  const d = cd.parseDefaults(RAW);
  assert.deepEqual(cd.resolutionOptions(d.models[2], "4K"), ["480p", "720p", "1080p", "4K"]);
  assert.deepEqual(cd.resolutionOptions(d.models[3], "480p"), ["480p", "720p", "1080p"]);
  assert.deepEqual(cd.resolutionOptions(d.models[0], "1080p"), ["480p", "720p", "1080p"]);
  assert.deepEqual(cd.durationOptions(d.models[0], 5), DUR_15);
  assert.deepEqual(cd.durationOptions(d.models[0], 20), [...DUR_15, 20]);
  assert.equal(cd.durationOptions(null, 5).length, 12);
});

test("pickModel: значения остаются, если модель их умеет; иначе ближайшие и строка", () => {
  const d = cd.parseDefaults(RAW);
  const from20 = { model: "bytedance/seedance-2.0", resolution: "4K", duration: 15 };
  const res = cd.pickModel(d, from20, "bytedance/seedance-2.0-mini");
  assert.deepEqual(res.draft, { model: "bytedance/seedance-2.0-mini", resolution: "720p", duration: 15 });
  assert.deepEqual(res.notes, ["Seedance Mini не снимает в 4K — выбрано 720p"]);
  // Модель без каталога — значения не трогаем (проверит сервер).
  const free = cd.pickModel(d, from20, "bytedance/seedance-2.5");
  assert.deepEqual(free.draft, { model: "bytedance/seedance-2.5", resolution: "4K", duration: 15 });
  assert.deepEqual(free.notes, []);
});

test("patchBody: только изменённое; сброс — к значениям из кода", () => {
  const saved = { model: "bytedance/seedance-2.0-mini", resolution: "480p", duration: 5 };
  assert.deepEqual(cd.patchBody(saved, saved), {});
  assert.deepEqual(cd.patchBody({ ...saved, duration: 10 }, saved), { duration: 10 });
  assert.deepEqual(cd.patchBody({ model: "m", resolution: "720p", duration: 5 }, saved), { model: "m", resolution: "720p" });
  assert.deepEqual(cd.RESET_BODY, { model: null, resolution: null, duration: null });
  assert.equal(cd.DEFAULTS_PATH, "cartoon/manage/defaults/");
});

test("errorText: текст сервера, нет связи, нет прав", () => {
  assert.equal(
    cd.errorText({ status: 400, data: { detail: "x", errors: { defaults: "Seedance Mini снимает от 4 до 15 секунд" } } }, "f"),
    "Seedance Mini снимает от 4 до 15 секунд",
  );
  assert.equal(cd.errorText({ status: 400, data: { detail: "Нечего сохранять" } }, "f"), "Нечего сохранять");
  assert.equal(cd.errorText({ status: 0 }, "f"), "Нет связи с сервером. Проверьте интернет и повторите.");
  assert.match(cd.errorText({ status: 403, data: {} }, "f"), /только сотрудники/);
  assert.equal(cd.errorText({ status: 500, data: "<html>" }, "Не сохранилось"), "Не сохранилось (HTTP 500)");
});
