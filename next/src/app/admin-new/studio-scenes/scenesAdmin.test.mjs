// Админка, сцены мультстудии: разбор ответов, фильтры, порядок, проверка форм и ролика превью (scenesAdmin.ts).
// Запуск (Node 22.6+):  node --experimental-strip-types --test src/app/admin-new/studio-scenes/scenesAdmin.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  DEFAULT_LIMITS,
  NO_FILTERS,
  afterPoll,
  buildingIds,
  chars,
  createBody,
  errorText,
  filterScenes,
  filtersActive,
  fmtMb,
  formFromScene,
  formFromSection,
  groupScenes,
  matchesScene,
  missingLangs,
  newSceneForm,
  newSectionForm,
  parseList,
  parsePublished,
  parseScene,
  parseSection,
  pollEach,
  pollList,
  previewFileError,
  previewLabel,
  previewPath,
  previewSecondsError,
  publishScenePath,
  rebuildPath,
  replaceScene,
  sceneChanges,
  sceneFromParams,
  sceneLink,
  scenePath,
  sceneStats,
  sceneWarnings,
  scenesAfterSection,
  publishNote,
  savedNote,
  sectionChanges,
  sectionCounts,
  sectionCreateBody,
  sectionOption,
  sectionPath,
  sectionWith,
  stateLabel,
  typedSort,
  validateScene,
  validateSection,
} from "./scenesAdmin.ts";

// Строки в том виде, как их собирает core/cartoon/panel.py (scene_row, section_row).
const sceneRow = (over = {}) => ({
  id: 7,
  slug: "rooftop-run",
  title: "Бег по крышам",
  title_en: "Rooftop run",
  title_kg: "",
  subtitle: "Герой бежит по крышам",
  subtitle_en: "",
  subtitle_kg: "",
  section_id: 2,
  audience: "kids",
  is_pick: false,
  sort_order: 20,
  is_active: true,
  aspect_ratio: "16:9",
  duration: 5,
  scene_prompt: "The character runs across rooftops at sunset",
  motion_prompt: "camera tracks alongside",
  state: "live",
  preview: {
    state: "ready",
    notes: [],
    video: "/media/cartoon/previews/a.mp4",
    clip: "/media/cartoon/previews/clips/a.mp4",
    poster: "/media/cartoon/posters/a.jpg",
    thumb: "/media/cartoon/posters/thumbs/a.jpg",
  },
  credits: 149,
  used_in: 0,
  can_delete: true,
  created_at: "2026-10-14T10:00:00+06:00",
  ...over,
});

const sectionRow = (over = {}) => ({
  id: 2,
  slug: "adventures",
  title: "Приключения",
  title_en: "Adventures",
  title_kg: "Укмуштуу окуялар",
  emoji: "🗺️",
  sort_order: 10,
  is_active: true,
  scenes: 3,
  published: 2,
  ...over,
});

const scene = (over = {}) => parseScene(sceneRow(over));
const section = (over = {}) => parseSection(sectionRow(over));
const L = DEFAULT_LIMITS;
const ASPECTS = ["16:9", "9:16", "1:1"];

test("пути: всё под manage/studio/, ссылка на сцену — с ?scene=", () => {
  assert.equal(scenePath(7), "manage/studio/scenes/7/");
  assert.equal(previewPath(7), "manage/studio/scenes/7/preview/");
  assert.equal(rebuildPath(7), "manage/studio/scenes/7/preview/rebuild/");
  assert.equal(sectionPath(3), "manage/studio/sections/3/");
  assert.equal(publishScenePath(41), "manage/studio/works/scene/41/publish-scene/");
  assert.equal(sceneLink(9), "/admin-new/studio-scenes?scene=9");
  assert.equal(sceneFromParams(new URLSearchParams("scene=9")), 9);
  assert.equal(sceneFromParams(new URLSearchParams("scene=0")), null);
  assert.equal(sceneFromParams(new URLSearchParams("scene=abc")), null);
  assert.equal(sceneFromParams(new URLSearchParams("")), null);
  assert.equal(sceneFromParams(null), null);
});

test("parseScene: строка сервера → сцена панели", () => {
  const s = scene();
  assert.equal(s.id, 7);
  assert.equal(s.titleEn, "Rooftop run");
  assert.equal(s.sectionId, 2);
  assert.equal(s.audience, "kids");
  assert.equal(s.published, true);
  assert.equal(s.sort, 20);
  assert.equal(s.state, "live");
  assert.equal(s.preview.state, "ready");
  assert.equal(s.preview.clip, "/media/cartoon/previews/clips/a.mp4");
  assert.equal(s.credits, 149);
  assert.equal(s.canDelete, true);
});

test("parseScene: чужие и битые поля не роняют страницу", () => {
  assert.equal(parseScene(null), null);
  assert.equal(parseScene({ title: "без id" }), null);
  assert.equal(parseScene({ id: "7" }), null);
  const s = parseScene({ id: 3, is_active: "true", audience: "teens", section_id: "2", preview: { video: "", state: "??" } });
  assert.equal(s.published, false, "строка \"true\" — не публикация");
  assert.equal(s.audience, "adults");
  assert.equal(s.sectionId, null);
  assert.equal(s.state, "unpublished");
  assert.equal(s.preview.state, "none");
  assert.equal(s.preview.video, null);
  assert.equal(s.canDelete, false, "без явного can_delete удалить не обещаем");
  assert.equal(s.duration, 5);
  // Ролик есть, а состояние незнакомое — копий, значит, нет.
  assert.equal(parseScene({ id: 4, preview: { video: "/a.mp4" } }).preview.state, "partial");
  assert.equal(parseScene({ id: 5, is_active: true }).state, "live");
});

test("parseList: сцены, разделы, справочники; повторы по id выкидываются", () => {
  const list = parseList({
    count: 3,
    results: [sceneRow(), sceneRow(), sceneRow({ id: 8 }), { nope: 1 }],
    sections: [sectionRow(), sectionRow(), sectionRow({ id: 5, is_active: false })],
    audiences: [
      { key: "kids", label: "Детям" },
      { key: "adults", label: "Взрослым" },
    ],
    aspects: ["16:9", "9:16", "1:1"],
    limits: { title_max: 100, preview_max_bytes: 1000, duration_default: 5 },
  });
  assert.deepEqual(
    list.scenes.map((s) => s.id),
    [7, 8],
  );
  assert.deepEqual(
    list.sections.map((s) => s.id),
    [2, 5],
  );
  assert.equal(list.sections[1].visible, false);
  assert.equal(list.audiences[0].label, "Детям");
  assert.equal(list.limits.titleMax, 100);
  assert.equal(list.limits.previewMaxBytes, 1000);
  assert.equal(list.limits.subtitleMax, L.subtitleMax, "чего сервер не назвал — свои границы");
});

test("parseList: ответ не панели — null; без справочников — запасные", () => {
  assert.equal(parseList(null), null);
  assert.equal(parseList("<html>502</html>"), null);
  assert.equal(parseList({ detail: "Учётные данные не были предоставлены." }), null);
  const bare = parseList({ results: [] });
  assert.deepEqual(
    bare.audiences.map((a) => a.key),
    ["kids", "adults"],
  );
  assert.deepEqual(bare.aspects, ASPECTS);
  assert.deepEqual(bare.limits, L);
  // Незнакомая аудитория — список целиком свой: её сервер не примет.
  assert.deepEqual(
    parseList({ results: [], audiences: [{ key: "teens", label: "Подросткам" }] }).audiences.map((a) => a.key),
    ["kids", "adults"],
  );
  // Противоречивые границы длительности — свои.
  const odd = parseList({ results: [], limits: { duration_min: 10, duration_max: 4 } }).limits;
  assert.equal(odd.durationMin, L.durationMin);
  assert.equal(odd.durationMax, L.durationMax);
});

test("parsePublished: новая сцена из «Работ» и повторный клик", () => {
  const first = parsePublished({ created: true, preset: sceneRow({ id: 30, is_active: false, state: "unpublished" }) });
  assert.equal(first.created, true);
  assert.equal(first.scene.id, 30);
  assert.equal(first.scene.published, false);
  assert.equal(parsePublished({ created: false, preset: sceneRow({ id: 30 }) }).created, false);
  assert.equal(parsePublished({ created: true }), null);
  assert.equal(parsePublished(null), null);
});

test("errorText: текст сервера; сеть, 413 и лимит — своими словами", () => {
  assert.equal(errorText({ status: 409, data: { detail: "Сцену уже взяли" } }, "Не удалось"), "Сцену уже взяли");
  assert.equal(errorText({ status: 500, data: "<html>" }, "Не удалось"), "Не удалось (HTTP 500)");
  assert.match(errorText({ status: 0 }, "x"), /Нет связи/);
  assert.match(errorText({ status: 413, data: "<html>413</html>" }, "x"), /больше, чем пропускает сервер/);
  assert.match(errorText({ status: 429, data: { detail: "Request was throttled" } }, "x"), /Слишком много/);
});

/* ---------------------------------------------------------------- фильтры */

const library = () => [
  scene({ id: 1, section_id: 2, audience: "kids", is_active: true, is_pick: true, title: "Полёт над городом" }),
  scene({ id: 2, section_id: 2, audience: "adults", is_active: false, title: "Погоня" }),
  scene({ id: 3, section_id: null, audience: "kids", is_active: true, title: "Сон", title_kg: "Түш" }),
  scene({ id: 4, section_id: 5, audience: "adults", is_active: true, slug: "night-race", title: "Гонка" }),
];

test("фильтры: раздел, без раздела, аудитория, публикация, «Выбор EsAI»", () => {
  const all = library();
  const ids = (f) => filterScenes(all, { ...NO_FILTERS, ...f }).map((s) => s.id);
  assert.deepEqual(ids({}), [1, 2, 3, 4]);
  assert.deepEqual(ids({ section: 2 }), [1, 2]);
  assert.deepEqual(ids({ section: "none" }), [3]);
  assert.deepEqual(ids({ audience: "kids" }), [1, 3]);
  assert.deepEqual(ids({ published: "yes" }), [1, 3, 4]);
  assert.deepEqual(ids({ published: "no" }), [2]);
  assert.deepEqual(ids({ pick: "yes" }), [1]);
  assert.deepEqual(ids({ pick: "no" }), [2, 3, 4]);
  assert.deepEqual(ids({ section: 2, audience: "adults", published: "no" }), [2]);
});

test("поиск: названия на трёх языках, подпись, код, промпт — без регистра", () => {
  const all = library();
  const ids = (q) => filterScenes(all, { ...NO_FILTERS, q }).map((s) => s.id);
  assert.deepEqual(ids("ПОГОНЯ"), [2]);
  assert.deepEqual(ids("  түш "), [3]);
  assert.deepEqual(ids("night-RACE"), [4]);
  assert.deepEqual(ids("rooftops"), [1, 2, 3, 4], "промпт сцены тоже ищется");
  assert.deepEqual(ids("крышам"), [1, 2, 3, 4], "и подпись");
  assert.deepEqual(ids("нет такого"), []);
  assert.equal(matchesScene(all[0], { ...NO_FILTERS, q: "   " }), true);
});

test("filtersActive: что-то выбрано — можно сбросить", () => {
  assert.equal(filtersActive(NO_FILTERS), false);
  assert.equal(filtersActive({ ...NO_FILTERS, q: "  " }), false);
  assert.equal(filtersActive({ ...NO_FILTERS, q: "лес" }), true);
  assert.equal(filtersActive({ ...NO_FILTERS, section: "none" }), true);
  assert.equal(filtersActive({ ...NO_FILTERS, pick: "no" }), true);
});

test("groupScenes: порядок библиотеки — раздел, затем порядок сцены; «Без раздела» в конце", () => {
  const sections = [section({ id: 5, sort_order: 5, title: "Космос" }), section({ id: 2, sort_order: 10 })];
  const scenes = [
    scene({ id: 9, section_id: 2, sort_order: 30 }),
    scene({ id: 3, section_id: null, sort_order: 10 }),
    scene({ id: 8, section_id: 2, sort_order: 10 }),
    scene({ id: 6, section_id: 2, sort_order: 10 }),
    scene({ id: 4, section_id: 5, sort_order: 50 }),
    scene({ id: 11, section_id: 99, sort_order: 1 }),
  ];
  const groups = groupScenes(scenes, sections);
  assert.deepEqual(
    groups.map((g) => g.section?.id ?? null),
    [5, 2, null],
  );
  assert.deepEqual(
    groups[1].scenes.map((s) => s.id),
    [6, 8, 9],
    "при равном порядке — старшая выше",
  );
  // Раздел, которого нет в списке, — сцена всё равно видна, среди «Без раздела».
  assert.deepEqual(
    groups[2].scenes.map((s) => s.id),
    [11, 3],
  );
  assert.deepEqual(groupScenes([], sections), [], "пустые разделы не выводятся");
});

test("replaceScene, buildingIds, sceneStats", () => {
  const all = library();
  const saved = { ...all[1], published: true, state: "no_preview" };
  const next = replaceScene(all, saved);
  assert.equal(next[1].state, "no_preview");
  assert.equal(next.length, 4);
  assert.equal(replaceScene(all, { ...saved, id: 50 }).length, 5);
  const building = replaceScene(all, { ...all[2], preview: { ...all[2].preview, state: "building" } });
  assert.deepEqual(buildingIds(building), [3]);
  const stats = sceneStats([...next, { ...all[0], id: 60, state: "section_hidden" }]);
  assert.deepEqual(stats, { total: 5, live: 3, stuck: 2, unpublished: 0 });
});

test("опрос сборки: удалённая в другом окне сцена уходит из списка, а не «собирается» вечно", () => {
  const building = (id) => scene({ id, preview: { ...sceneRow().preview, state: "building" } });
  const all = [building(1), building(2), scene({ id: 3 })];
  const ready = sceneRow({ id: 1 });
  const answers = [
    { ok: true, status: 200, data: ready },
    { ok: false, status: 404, data: { detail: "Сцена не найдена" } },
  ];
  const result = pollEach([1, 2], answers);
  assert.deepEqual(result.gone, [2]);
  assert.deepEqual(result.fresh.map((s) => s.id), [1]);
  const next = afterPoll(all, result);
  assert.deepEqual(next.map((s) => [s.id, s.preview.state]), [[1, "ready"], [3, "ready"]]);
  assert.deepEqual(buildingIds(next), [], "опрашивать больше некого");

  // Лимит или сеть — не удаление: строка ждёт следующего опроса.
  const limited = pollEach([1, 2], [{ ok: false, status: 429 }, { ok: false, status: 0 }]);
  assert.deepEqual(limited, { fresh: [], gone: [] });
  assert.equal(afterPoll(all, limited).length, 3);

  // Опрос всем списком: чего в нём нет — удалено.
  const listed = pollList([1, 2], { scenes: [scene({ id: 1 }), scene({ id: 3 })] });
  assert.deepEqual(listed.gone, [2]);
  assert.deepEqual(listed.fresh.map((s) => s.id), [1]);
});

test("sectionWith: порядок раздела — сразу, откат — тем же путём, чужие разделы не трогаются", () => {
  const all = [section({ id: 2, sort_order: 10 }), section({ id: 4, sort_order: 20 })];
  const moved = sectionWith(all, 4, { sort: 5 });
  assert.deepEqual(moved.map((s) => [s.id, s.sort]), [[2, 10], [4, 5]]);
  assert.equal(moved[0], all[0]);
  assert.deepEqual(sectionWith(moved, 4, { sort: 20 }), all);
});

test("scenesAfterSection: скрытый раздел прячет свои опубликованные сцены с превью", () => {
  const all = [
    scene({ id: 1, section_id: 2, state: "live" }),
    scene({ id: 2, section_id: 2, is_active: false, state: "unpublished" }),
    scene({ id: 3, section_id: 2, state: "no_preview" }),
    scene({ id: 4, section_id: 5, state: "live" }),
  ];
  const hidden = scenesAfterSection(all, section({ id: 2, is_active: false }));
  assert.deepEqual(
    hidden.map((s) => s.state),
    ["section_hidden", "unpublished", "no_preview", "live"],
  );
  const shown = scenesAfterSection(hidden, section({ id: 2, is_active: true }));
  assert.deepEqual(
    shown.map((s) => s.state),
    ["live", "unpublished", "no_preview", "live"],
  );
  assert.equal(shown[3], hidden[3], "чужие сцены не пересоздаются");
});

test("метки: состояние сцены и превью", () => {
  assert.equal(stateLabel({ state: "live" }).tone, "accent");
  assert.equal(stateLabel({ state: "unpublished" }).label, "Не опубликована");
  assert.match(stateLabel({ state: "no_preview" }).title, /загрузите ролик/);
  assert.match(stateLabel({ state: "section_hidden" }).title, /раздел скрыт/);
  assert.equal(previewLabel({ state: "ready", notes: [] }), null);
  assert.equal(previewLabel({ state: "building", notes: [] }).tone, "wait");
  assert.equal(
    previewLabel({ state: "partial", notes: ["Обложка не сделалась", "Лёгкая копия не сделалась"] }).title,
    "Обложка не сделалась. Лёгкая копия не сделалась",
  );
  assert.match(previewLabel({ state: "partial", notes: [] }).title, /Пересобрать/);
  assert.equal(previewLabel({ state: "none", notes: [] }).label, "Без ролика");
});

test("missingLangs: без перевода названия или подписи сайт покажет русский", () => {
  assert.deepEqual(missingLangs(scene()), ["EN", "KG"], "EN-подписи нет, KG нет ничего");
  assert.deepEqual(
    missingLangs(scene({ subtitle_en: "Runs", title_kg: "Чатырлар", subtitle_kg: "Чуркайт" })),
    [],
  );
  assert.deepEqual(missingLangs(scene({ subtitle: "", title_kg: "Чатырлар" })), [], "без подписи переводить её не нужно");
  assert.deepEqual(missingLangs(section()), []);
  assert.deepEqual(missingLangs(section({ title_kg: "" })), ["KG"]);
});

/* ---------------------------------------------------------------- форма сцены */

const filled = (over = {}) => ({
  ...newSceneForm(L),
  title: "Полёт",
  scenePrompt: "The character flies over the forest",
  ...over,
});

test("newSceneForm: не опубликована, 5 с, 16:9; раздел и аудитория — из фильтров", () => {
  const form = newSceneForm(L);
  assert.equal(form.published, false);
  assert.equal(form.duration, "5");
  assert.equal(form.aspect, "16:9");
  assert.equal(form.sort, "");
  assert.equal(form.sectionId, null);
  assert.equal(form.audience, "adults");
  const narrowed = newSceneForm(L, { ...NO_FILTERS, section: 2, audience: "kids" });
  assert.equal(narrowed.sectionId, 2);
  assert.equal(narrowed.audience, "kids");
  assert.equal(newSceneForm(L, { ...NO_FILTERS, section: "none" }).sectionId, null);
});

test("validateScene: обязательные поля и границы — тексты как у сервера", () => {
  assert.equal(validateScene(filled(), L, ASPECTS, true), null);
  assert.equal(validateScene(filled({ title: "   " }), L, ASPECTS, true), "Название обязательно");
  assert.match(validateScene(filled({ scenePrompt: " " }), L, ASPECTS, true), /^Промпт сцены обязателен/);
  assert.equal(validateScene(filled({ title: "я".repeat(121) }), L, ASPECTS, true), "Название длиннее 120 символов");
  // Пробелы сервер схлопывает — длину считаем после этого.
  assert.equal(validateScene(filled({ title: `${"я".repeat(60)}     ${"я".repeat(59)}` }), L, ASPECTS, true), null);
  assert.equal(validateScene(filled({ subtitleKg: "ы".repeat(161) }), L, ASPECTS, true), "Подпись (KG) длиннее 160 символов");
  assert.match(validateScene(filled({ scenePrompt: "a".repeat(2001) }), L, ASPECTS, true), /длиннее 2000/);
  assert.match(validateScene(filled({ motionPrompt: "a".repeat(1001) }), L, ASPECTS, true), /движения длиннее 1000/);
  assert.equal(validateScene(filled({ aspect: "4:3" }), L, ASPECTS, true), "Пропорции: 16:9, 9:16, 1:1");
  for (const duration of ["1", "16", "5.5", "", "пять"]) {
    assert.match(validateScene(filled({ duration }), L, ASPECTS, true), /^Длительность — целое число секунд от 2 до 15/);
  }
  assert.equal(validateScene(filled({ duration: " 15 " }), L, ASPECTS, true), null);
});

test("validateScene: порядок — пустой только у новой сцены; код — только при создании", () => {
  assert.equal(validateScene(filled({ sort: "" }), L, ASPECTS, true), null);
  assert.equal(validateScene(filled({ sort: "" }), L, ASPECTS, false), "Порядок — целое число от 0 до 100000");
  assert.equal(validateScene(filled({ sort: "-5" }), L, ASPECTS, true), "Порядок — целое число от 0 до 100000");
  assert.equal(validateScene(filled({ sort: "100001" }), L, ASPECTS, false), "Порядок — целое число от 0 до 100000");
  assert.equal(validateScene(filled({ sort: "0" }), L, ASPECTS, false), null);
  assert.equal(validateScene(filled({ slug: "night-flight-2" }), L, ASPECTS, true), null);
  for (const slug of ["Night", "ночь", "a--b", "-a", "a_b"]) {
    assert.match(validateScene(filled({ slug }), L, ASPECTS, true), /^Код — латиница/, slug);
  }
  // У готовой сцены код не правится — и не проверяется.
  assert.equal(validateScene(filled({ slug: "Old_Code", sort: "10" }), L, ASPECTS, false), null);
});

test("sceneWarnings: без character и с русскими буквами — предупредить, но не мешать", () => {
  assert.deepEqual(sceneWarnings({ scenePrompt: "The character waves", motionPrompt: "" }), []);
  assert.deepEqual(sceneWarnings({ scenePrompt: "Two characters dance", motionPrompt: "" }), []);
  assert.deepEqual(sceneWarnings({ scenePrompt: "", motionPrompt: "" }), []);
  const [hero] = sceneWarnings({ scenePrompt: "A fox in the forest", motionPrompt: "" });
  assert.match(hero, /нет слова character/);
  const both = sceneWarnings({ scenePrompt: "Герой летит", motionPrompt: "" });
  assert.equal(both.length, 2);
  assert.match(sceneWarnings({ scenePrompt: "The character runs", motionPrompt: "камера едет" })[0], /русские буквы/);
});

test("createBody: настоящие числа и флаги, пустой порядок и код не отправляются", () => {
  const body = createBody(
    filled({ title: "  Полёт   над  лесом ", sectionId: 2, pick: true, duration: "7", motionPrompt: "  pan left " }),
    L,
  );
  assert.deepEqual(body, {
    title: "Полёт над лесом",
    title_en: "",
    title_kg: "",
    subtitle: "",
    subtitle_en: "",
    subtitle_kg: "",
    section_id: 2,
    audience: "adults",
    is_pick: true,
    is_active: false,
    aspect_ratio: "16:9",
    duration: 7,
    scene_prompt: "The character flies over the forest",
    motion_prompt: "pan left",
  });
  const withSort = createBody(filled({ sort: "40", slug: " forest-flight " }), L);
  assert.equal(withSort.sort_order, 40);
  assert.equal(withSort.slug, "forest-flight");
});

test("sceneChanges: только поменявшееся; без правок — пустое тело", () => {
  const s = scene();
  assert.deepEqual(sceneChanges(s, formFromScene(s), L), {});
  // Лишние пробелы — не правка: сервер всё равно их уберёт.
  assert.deepEqual(sceneChanges(s, { ...formFromScene(s), title: "  Бег  по крышам " }, L), {});
  assert.deepEqual(
    sceneChanges(s, { ...formFromScene(s), published: false, sectionId: null, sort: "5", titleKg: "Чатырлар" }, L),
    { title_kg: "Чатырлар", section_id: null, is_active: false, sort_order: 5 },
  );
  assert.deepEqual(sceneChanges(s, { ...formFromScene(s), duration: "10", audience: "adults" }, L), {
    audience: "adults",
    duration: 10,
  });
});

/* ---------------------------------------------------------------- ролик превью */

test("previewFileError: MP4, не пустой, не больше потолка", () => {
  const ok = { name: "Scene.MP4", size: 5 * 1024 * 1024 };
  assert.equal(previewFileError(ok, L), null);
  assert.match(previewFileError({ name: "scene.mov", size: 100 }, L), /^Это не MP4/);
  assert.match(previewFileError({ name: "scene.mp4.exe", size: 100 }, L), /^Это не MP4/);
  assert.match(previewFileError({ name: "scene.mp4", size: 0 }, L), /пустой/);
  assert.equal(previewFileError({ name: "a.mp4", size: L.previewMaxBytes }, L), null);
  // Чуть больше потолка — и вес показан больше потолка, а не равным ему.
  assert.equal(
    previewFileError({ name: "a.mp4", size: L.previewMaxBytes + 1 }, L),
    "Ролик весит 24,1 МБ — больше 24 МБ. Сожмите или укоротите его",
  );
  assert.match(previewFileError({ name: "a.mp4", size: 30 * 1024 * 1024 }, L), /весит 30 МБ/);
  assert.equal(fmtMb(5 * 1024 * 1024), "5 МБ");
  assert.equal(fmtMb(1.25 * 1024 * 1024), "1,3 МБ");
});

test("previewSecondsError: от 1 до 20 секунд; неизвестная длительность — решит сервер", () => {
  assert.equal(previewSecondsError(5, L), null);
  assert.equal(previewSecondsError(1, L), null);
  assert.equal(previewSecondsError(20, L), null);
  assert.equal(previewSecondsError(null, L), null);
  assert.equal(previewSecondsError(Number.NaN, L), null);
  assert.equal(previewSecondsError(20.04, L), "Ролик длится 20 с — нужно от 1 до 20 секунд");
  assert.equal(previewSecondsError(0.4, L), "Ролик длится 0,4 с — нужно от 1 до 20 секунд");
  assert.match(previewSecondsError(45.26, L), /длится 45,3 с/);
});

/* ---------------------------------------------------------------- разделы */

test("parseSection: строка раздела; скрытый — только при явном false", () => {
  const s = section();
  assert.equal(s.title, "Приключения");
  assert.equal(s.emoji, "🗺️");
  assert.equal(s.visible, true);
  assert.equal(s.scenes, 3);
  assert.equal(s.published, 2);
  assert.equal(parseSection({ id: 1, title: "Лес" }).visible, true);
  assert.equal(parseSection({ id: 1, is_active: false }).visible, false);
  assert.equal(parseSection({ title: "без id" }), null);
});

test("validateSection: название обязательно, значок — до 8 символов, считая как сервер", () => {
  const form = { ...newSectionForm(), title: "Космос", emoji: "🚀" };
  assert.equal(validateSection(form, L, true), null);
  assert.equal(validateSection({ ...form, title: " " }, L, true), "Название раздела обязательно");
  assert.equal(validateSection({ ...form, titleEn: "s".repeat(81) }, L, true), "Название раздела (EN) длиннее 80 символов");
  // Сервер считает символы, а не UTF-16: 8 эмодзи — это 8, а не 16.
  assert.equal(chars("🚀🚀"), 2);
  assert.equal(validateSection({ ...form, emoji: "🚀".repeat(8) }, L, true), null);
  assert.equal(validateSection({ ...form, emoji: "🚀".repeat(9) }, L, true), "Значок длиннее 8 символов");
  assert.equal(validateSection({ ...form, emoji: "🚀 🚀 🚀 🚀 🚀 🚀 🚀 🚀" }, L, true), null, "пробелы сервер убирает");
  assert.equal(validateSection({ ...form, sort: "" }, L, false), "Порядок — целое число от 0 до 100000");
  assert.equal(validateSection({ ...form, sort: "" }, L, true), null);
});

test("тела раздела: новый — целиком, правка — только поменявшееся", () => {
  assert.deepEqual(sectionCreateBody({ ...newSectionForm(), title: " Космос ", emoji: " 🚀 ", sort: "" }, L), {
    title: "Космос",
    title_en: "",
    title_kg: "",
    emoji: "🚀",
    is_active: true,
  });
  assert.equal(sectionCreateBody({ ...newSectionForm(), title: "Космос", sort: "30" }, L).sort_order, 30);
  const s = section();
  assert.deepEqual(sectionChanges(s, formFromSection(s), L), {});
  assert.deepEqual(sectionChanges(s, { ...formFromSection(s), visible: false, sort: "15" }, L), {
    is_active: false,
    sort_order: 15,
  });
});

test("typedSort: только целое от 0 до sortMax", () => {
  assert.equal(typedSort("0", L), 0);
  assert.equal(typedSort(" 40 ", L), 40);
  assert.equal(typedSort("100000", L), 100000);
  assert.equal(typedSort("100001", L), null);
  assert.equal(typedSort("-1", L), null);
  assert.equal(typedSort("1e3", L), null);
  assert.equal(typedSort("", L), null);
});

test("sectionCounts: всего и опубликованных с превью — по своему списку", () => {
  const counts = sectionCounts([
    scene({ id: 1, section_id: 2 }),
    scene({ id: 2, section_id: 2, is_active: false }),
    scene({ id: 3, section_id: 2, preview: { state: "none", video: "" } }),
    scene({ id: 4, section_id: 5 }),
    scene({ id: 5, section_id: null }),
  ]);
  assert.deepEqual(counts.get(2), { total: 3, published: 1 });
  assert.deepEqual(counts.get(5), { total: 1, published: 1 });
  assert.equal(counts.has(null), false);
  assert.equal(counts.get(9), undefined);
});

test("sectionOption: скрытый раздел помечен в списке выбора", () => {
  assert.equal(sectionOption(section()), "🗺️ Приключения");
  assert.equal(sectionOption(section({ is_active: false })), "🗺️ Приключения (скрыт)");
  assert.equal(sectionOption(section({ emoji: "" })), "Приключения");
});

test("publishNote и savedNote: видна ли сцена теперь и почему нет", () => {
  const title = "Полёт";
  assert.equal(publishNote({ title, state: "live" }), "В библиотеке: «Полёт».");
  assert.match(publishNote({ title, state: "unpublished" }), /^Снята с публикации/);
  assert.match(publishNote({ title, state: "no_preview" }), /загрузите ролик/);
  assert.match(publishNote({ title, state: "section_hidden" }), /раздел скрыт/);

  assert.equal(
    savedNote({ title, state: "unpublished" }, { created: true, uploaded: false }),
    "Сцена создана: «Полёт». Она не опубликована: включите «Опубликована», когда всё готово.",
  );
  assert.equal(
    savedNote({ title, state: "live" }, { created: true, uploaded: true }),
    "Сцена создана: «Полёт». Превью собирается — это пара минут. Она уже видна в библиотеке.",
  );
  assert.equal(savedNote({ title, state: "live" }, { created: false, uploaded: false }), "Сохранено: «Полёт».");
  assert.match(savedNote({ title, state: "no_preview" }, { created: false, uploaded: false }), /загрузите ролик/);
  assert.match(savedNote({ title, state: "section_hidden" }, { created: false, uploaded: true }), /раздел скрыт/);
});

/* ---------------------------------------------------------------- страница */

test("«Работы»: кнопка публикует по пути сцен и ведёт на созданную сцену", () => {
  // Контракт «Опубликовать как новую сцену» живёт в scenesAdmin.ts — страница
  // «Работ» не должна собирать адрес сама.
  const works = readFileSync(new URL("../studio-works/page.tsx", import.meta.url), "utf8");
  assert.match(works, /publishScenePath\(w\.id\)/);
  assert.match(works, /parsePublished\(res\.data\)/);
  assert.match(works, /sceneLink\(outcome\.sceneId\)/);
  assert.match(works, /can_publish_scene/);
  assert.match(works, /publish_scene_note/);
  // Сделанную раньше сцену знает сервер: после перезагрузки вместо кнопки — ссылка.
  assert.match(works, /published\[w\.id\] \?\? earlier/);
  assert.match(works, /w\.library_scene_id \? \{ sceneId: w\.library_scene_id, created: false \}/);
});

test("страница: опрос убирает удалённые сцены, порядок раздела откатывается после отказа", () => {
  const page = readFileSync(new URL("./page.tsx", import.meta.url), "utf8");
  assert.match(page, /result = pollEach\(ids, answers\)/);
  assert.match(page, /result = pollList\(ids, data\)/);
  assert.match(page, /afterPoll\(prev\.scenes, result\)/);
  assert.match(page, /sectionWith\(list, section\.id, \{ sort \}\)/);
  assert.match(page, /if \(!saved\) editSections\(\(list\) => sectionWith\(list, section\.id, \{ sort: section\.sort \}\)\)/);
});

test("страница берёт ?scene= у роутера и обёрнута в Suspense", () => {
  // Ссылка из «Работ» открывает созданную сцену. При клиентском переходе
  // window.location на первом рендере ещё старый (см. payments/filters.ts),
  // а useSearchParams без границы Suspense ломает сборку.
  const page = readFileSync(new URL("./page.tsx", import.meta.url), "utf8");
  assert.equal(/window\.location/.test(page), false);
  assert.match(page, /useSearchParams\(\)/);
  assert.match(page, /sceneFromParams\(/);
  assert.match(page, /<Suspense\b/);
});
