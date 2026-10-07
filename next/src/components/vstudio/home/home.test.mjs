// Первый экран видеостудии: сценарии (home/templates.ts) и сборка витрины (home/showreelData.ts).
// Запуск (Node 22.6+):  node --experimental-strip-types --test src/components/vstudio/home/*.test.mjs
import "../../../lib/vstudio/nodeTsHooks.mjs";
import { test } from "node:test";
import assert from "node:assert/strict";

const T = await import("./templates.ts");
const S = await import("./showreelData.ts");

/* ---------- сценарии ---------- */

test("сценарии: 8 жанров, один постер-картинка, у каждого подпись и заготовка", () => {
  assert.deepEqual(
    T.VS_TEMPLATES.map((t) => t.id),
    ["film", "product", "ugc", "clip", "anime", "photo", "poster", "logo"],
  );
  assert.deepEqual(T.VS_TEMPLATES.filter((t) => t.kind === "image").map((t) => t.id), ["poster"]);
  for (const t of T.VS_TEMPLATES) {
    assert.ok(t.label && t.label.length <= 24, t.id);
    // Заготовка короткая: одна сцена, с запасом до «мягкого» предела моделей.
    assert.ok(t.prompt.split(/\s+/).length < 40, t.id);
    assert.match(t.aspect, /^(auto|\d+:\d+)$/, t.id);
  }
  assert.equal(T.VS_TEMPLATES.find((t) => t.id === "photo").aspect, "auto");
  // Места для своего — в квадратных скобках, у фото и логотипа тоже.
  const prompt = (id) => T.VS_TEMPLATES.find((t) => t.id === id).prompt;
  assert.match(prompt("film"), /\[кто\]/);
  assert.match(prompt("photo"), /^\[ваше фото\]/);
  assert.match(prompt("logo"), /\[ваш логотип\]/);
});

test("сценарии: в заготовке нет @ — ни в коде, ни в одном переводе", async () => {
  // Текст с @ на конце редактор принимает за начатую отметку и сам открывает
  // список материалов поверх запроса. Переводы проверяем тоже: русский сверяет
  // с кодом check:i18n, английский и киргизский не сверяет никто.
  const { readFile } = await import("node:fs/promises");
  for (const t of T.VS_TEMPLATES) assert.ok(!t.prompt.includes("@"), t.id);
  for (const lang of ["ru", "en", "kg"]) {
    const file = new URL(`../../../locales/${lang}/vstudio.json`, import.meta.url);
    const tpl = JSON.parse(await readFile(file, "utf8")).home.tpl;
    for (const t of T.VS_TEMPLATES) assert.ok(!tpl[t.id].prompt.includes("@"), `${lang}: ${t.id}`);
  }
});

/* ---------- витрина ---------- */

const showcase = (over = {}) => ({
  id: 12,
  title: "Ночной город",
  category: "film",
  kind: "video",
  model: { id: "bytedance/seedance-2.0", name: "Seedance 2.0" },
  aspect_ratio: "16:9",
  duration_s: 5,
  width: 1280,
  height: 720,
  video_url: "/media/vstudio/a.mp4",
  image_url: null,
  poster_url: "/media/vstudio/a.jpg",
  prompt: "Ночной город под дождём",
  params: { duration: 5, resolution: "720p", aspect_ratio: "16:9" },
  ...over,
});

const preset = (n, over = {}) => ({
  id: n,
  slug: `scene-${n}`,
  title: `Сцена ${n}`,
  subtitle: "Герой идёт по лесу",
  preview_video: `/media/cartoon/previews/clips/${n}.mp4`,
  preview_poster: `/media/cartoon/posters/thumbs/${n}.jpg`,
  duration: 5,
  aspect_ratio: "16:9",
  credits: 40,
  category: "tales",
  audience: "kids",
  is_pick: false,
  ...over,
});

test("работа видеостудии → карточка: модель, запрос и параметры на месте", () => {
  const [item] = S.studioItems({ items: [showcase()] });
  assert.deepEqual(item, {
    id: "vs:12",
    source: "vstudio",
    kind: "video",
    title: "Ночной город",
    subtitle: "Seedance 2.0",
    category: "film",
    video: "/media/vstudio/a.mp4",
    poster: "/media/vstudio/a.jpg",
    aspect: "16:9",
    duration: 5,
    href: null,
    modelId: "bytedance/seedance-2.0",
    prompt: "Ночной город под дождём",
    params: { duration: 5, resolution: "720p", aspect_ratio: "16:9" },
    pick: false,
  });
});

test("работа без показа запроса и картинка: prompt/params пустые, постер — сама картинка", () => {
  const [hidden, image] = S.studioItems({
    items: [
      showcase({ id: 1, prompt: undefined, params: undefined }),
      showcase({ id: 2, kind: "image", video_url: null, poster_url: null, image_url: "/media/vstudio/p.png", duration_s: null, prompt: "  ", params: {} }),
    ],
  });
  assert.equal(hidden.prompt, null);
  assert.equal(hidden.params, null);
  assert.equal(image.kind, "image");
  assert.equal(image.video, null);
  assert.equal(image.poster, "/media/vstudio/p.png");
  assert.equal(image.duration, null);
  assert.equal(image.prompt, null);
  assert.equal(image.params, null);
});

test("кривой ответ витрины не роняет первый экран", () => {
  for (const bad of [null, undefined, "", 42, [], {}, { items: null }, { items: "x" }, { items: [null, 1, "a", []] }]) {
    assert.deepEqual(S.studioItems(bad), []);
  }
  const items = S.studioItems({
    items: [
      showcase({ id: 1 }),
      showcase({ id: 1 }), // повтор id
      showcase({ id: 2, video_url: "", poster_url: null }), // показать нечего
      showcase({ id: null }),
      showcase({ id: 3, model: null, category: "", aspect_ratio: null, duration_s: "5", params: { duration: -1, resolution: 720 } }),
    ],
  });
  assert.deepEqual(items.map((i) => i.id), ["vs:1", "vs:3"]);
  const loose = items[1];
  assert.equal(loose.modelId, null);
  assert.equal(loose.subtitle, "");
  assert.equal(loose.category, "other");
  assert.equal(loose.aspect, "16:9");
  assert.equal(loose.duration, null);
  assert.equal(loose.params, null);
});

test("сцена мультстудии → карточка-ссылка в /studio; без кадра не берём", () => {
  const { items, titles } = S.cartoonItems({
    categories: [{ slug: "tales", title: "Сказки", emoji: "🧚" }, { slug: "", title: "Без адреса" }, { slug: "x" }],
    presets: [
      preset(1, { is_pick: true }),
      preset(2, { preview_poster: "" }),
      preset(3, { preview_video: "", preview_poster: "" }),
      preset(4, { slug: "scene-1" }), // повтор slug
      preset(5, { slug: "", category: null }),
      "мусор",
    ],
    popular: [],
  });
  assert.deepEqual(items.map((i) => i.id), ["ct:scene-1", "ct:scene-2", "ct:5"]);
  assert.deepEqual(items[0], {
    id: "ct:scene-1",
    source: "cartoon",
    kind: "video",
    title: "Сцена 1",
    subtitle: "Герой идёт по лесу",
    category: "tales",
    video: "/media/cartoon/previews/clips/1.mp4",
    poster: "/media/cartoon/posters/thumbs/1.jpg",
    aspect: "16:9",
    duration: 5,
    href: "/studio",
    modelId: null,
    prompt: null,
    params: null,
    pick: true,
  });
  assert.equal(items[1].poster, null);
  assert.equal(items[2].category, "");
  assert.deepEqual([...titles], [["tales", "Сказки"]]);
  for (const bad of [null, "x", [], { presets: {} }]) assert.deepEqual(S.cartoonItems(bad).items, []);
});

test("карусель: работы студии, затем выбор редакции — не больше 12", () => {
  const studio = S.studioItems({ items: Array.from({ length: 3 }, (_, i) => showcase({ id: i + 1 })) });
  const cartoon = S.cartoonItems({ presets: Array.from({ length: 30 }, (_, i) => preset(i + 1, { is_pick: i % 2 === 0 })) }).items;
  const view = S.buildShowreel(studio, cartoon);
  assert.equal(view.reel.length, S.REEL_SIZE);
  assert.deepEqual(view.reel.slice(0, 3).map((i) => i.id), ["vs:1", "vs:2", "vs:3"]);
  assert.ok(view.reel.slice(3).every((i) => i.source === "cartoon" && i.pick));
  assert.equal(view.all.length, 33);
  assert.deepEqual(view.all.slice(0, 3), studio);
  assert.equal(view.hasStudio, true);

  const many = S.studioItems({ items: Array.from({ length: 20 }, (_, i) => showcase({ id: i + 1 })) });
  const full = S.buildShowreel(many, cartoon);
  assert.equal(full.reel.length, 12);
  assert.ok(full.reel.every((i) => i.source === "vstudio"));
});

test("карусель: отмеченных сцен хватает — обычные не добавляются", () => {
  const cartoon = S.cartoonItems({ presets: Array.from({ length: 20 }, (_, i) => preset(i + 1, { is_pick: i < 6 })) }).items;
  const view = S.buildShowreel([], cartoon);
  assert.equal(view.reel.length, 6);
  assert.ok(view.reel.every((i) => i.pick));
  assert.equal(view.hasStudio, false);
});

test("карусель: отмеченных мало — добираем до пяти, сначала из других разделов и только с постером", () => {
  const cartoon = S.cartoonItems({
    presets: [
      preset(1, { is_pick: true, category: "tales" }),
      preset(2, { category: "tales" }),
      preset(3, { category: "tales" }),
      preset(4, { category: "space", preview_poster: "" }),
      preset(5, { category: "space" }),
      preset(6, { category: "sea" }),
      preset(7, { category: "sea" }),
    ],
  }).items;
  const view = S.buildShowreel([], cartoon);
  assert.deepEqual(view.reel.map((i) => i.id), ["ct:scene-1", "ct:scene-5", "ct:scene-6", "ct:scene-2", "ct:scene-3"]);
  assert.equal(new Set(view.reel.map((i) => i.id)).size, S.REEL_MIN);

  // Сцен всего три — карусель из трёх, без повторов и без падения.
  const few = S.buildShowreel([], cartoon.slice(0, 3));
  assert.equal(few.reel.length, 3);
  assert.deepEqual(S.buildShowreel([], []), S.EMPTY_SHOWREEL);
});

test("разделы: только с названием, от самых полных, порядок сервера при равенстве", () => {
  const { items, titles } = S.cartoonItems({
    categories: [
      { slug: "tales", title: "Сказки" },
      { slug: "space", title: "Космос" },
      { slug: "sea", title: "Море" },
    ],
    presets: [
      preset(1, { category: "tales" }),
      preset(2, { category: "space" }),
      preset(3, { category: "space" }),
      preset(4, { category: "sea" }),
      preset(5, { category: "ghost" }), // раздела нет в списке — вкладки не будет
      preset(6, { category: "" }),
    ],
  });
  assert.deepEqual(S.buildShowreel([], items, titles).categories, [
    { slug: "space", title: "Космос", count: 2 },
    { slug: "tales", title: "Сказки", count: 1 },
    { slug: "sea", title: "Море", count: 1 },
  ]);
  assert.deepEqual(S.buildShowreel([], items).categories, []);
});

/* ---------- «Снять похожее» на настоящем редьюсере ---------- */

const A = await import("./applyItem.ts");
const Store = await import("../store.ts");
const { FIXTURE_MODELS } = await import("@/lib/vstudio/fixtures");
const Sync = await import("../settings/useRunSettingsSync.ts");
const { plainText } = await import("@/lib/vstudio/promptDoc");

const SEEDANCE = "bytedance/seedance-2.0";
const VEO = "google/veo-3.1-fast";
const KLING_LOCKED = "kwaivgi/kling-v3.0-std";
const FLUX = "black-forest-labs/flux.2-flex";

/** Стор с моделями и выбранной Seedance 2.0; apply прогоняет действия через редьюсер. */
function studio(setup = []) {
  Sync.resetRunSettingsSync();
  let state = Store.reducer(Store.createInitialState(), { type: "models/loaded", payload: FIXTURE_MODELS });
  const log = [];
  const dispatch = (action) => {
    log.push(action.type);
    state = Store.reducer(state, action);
  };
  dispatch({ type: "composer/model", model: SEEDANCE });
  for (const action of setup) dispatch(action);
  log.length = 0;
  return {
    log,
    get composer() {
      return state.composer;
    },
    apply: (item) => A.applyReelItem(item, state, dispatch),
    // Как в StudioHome: что применилось и что об этом сказать — по состоянию до нажатия.
    use: (item) => {
      const models = state.models;
      const outcome = A.applyReelItem(item, state, dispatch);
      return [outcome, A.applyNotice(item, models, outcome)];
    },
  };
}

const work = (over = {}) =>
  S.studioItems({
    items: [
      showcase({
        model: { id: VEO, name: "Veo 3.1 Fast" },
        prompt: "Ночной город под дождём",
        params: { duration: 8, resolution: "1080P", aspect_ratio: "9:16" },
        ...over,
      }),
    ],
  })[0];

test("снять похожее: модель, её параметры и текст — в пустую панель", () => {
  const s = studio();
  assert.equal(s.apply(work()), "filled");
  assert.equal(s.composer.kind, "video");
  assert.equal(s.composer.model, VEO);
  assert.equal(s.composer.params.duration, 8);
  assert.equal(s.composer.params.resolution, "1080p", "регистр — как у модели");
  assert.equal(s.composer.params.aspect_ratio, "9:16");
  assert.equal(plainText(s.composer.doc), "Ночной город под дождём");
});

test("снять похожее: чужие значения, которых модель не умеет, не подставляются", () => {
  const s = studio();
  // Veo не снимает 5 секунд и 21:9 — остаются её собственные значения, а не ошибка invalid_param.
  s.apply(work({ params: { duration: 5, resolution: "4k", aspect_ratio: "21:9" } }));
  assert.equal(s.composer.model, VEO);
  assert.ok([4, 6, 8].includes(s.composer.params.duration));
  assert.ok(["720p", "1080p"].includes(s.composer.params.resolution));
  assert.ok(["16:9", "9:16", "auto"].includes(s.composer.params.aspect_ratio));
});

test("снять похожее: свой текст человека не затирается — исход kept", () => {
  const s = studio([{ type: "composer/doc", doc: { v: 1, blocks: [[{ t: "text", v: "мой сценарий" }]] } }]);
  assert.equal(s.apply(work()), "kept");
  assert.equal(s.composer.model, VEO);
  assert.equal(plainText(s.composer.doc), "мой сценарий");
  assert.ok(!s.log.includes("composer/doc"));
});

test("работа без запроса: выбирается только модель — исход set", () => {
  const s = studio();
  assert.equal(s.apply(work({ prompt: null, params: null })), "set");
  assert.equal(s.composer.model, VEO);
  assert.equal(plainText(s.composer.doc), "");
});

test("картинка из витрины при выбранном видео: вид и модель переключаются", () => {
  const s = studio();
  const poster = work({ kind: "image", video_url: null, image_url: "/media/vstudio/p.png", poster_url: null, model: { id: FLUX, name: "FLUX.2 Flex" }, params: { aspect_ratio: "3:4" } });
  assert.equal(s.apply(poster), "filled");
  assert.equal(s.composer.kind, "image");
  assert.equal(s.composer.model, FLUX);
  assert.equal(s.composer.params.aspect_ratio, "3:4");
  assert.equal(s.composer.params.duration, undefined, "у картинки нет длительности");
  // И обратно к видео — той же дорогой.
  assert.equal(s.apply(work({ prompt: null })), "set");
  assert.equal(s.composer.kind, "video");
  assert.equal(s.composer.model, VEO);
});

test("модель под замком: ничего не меняется — исход locked", () => {
  const s = studio();
  assert.equal(s.apply(work({ model: { id: KLING_LOCKED, name: "Kling v3" } })), "locked");
  assert.deepEqual(s.log, []);
  assert.equal(s.composer.model, SEEDANCE);
});

test("модели работы уже нет: остаёмся на своей, берём подходящие параметры и текст", () => {
  const s = studio();
  assert.equal(s.apply(work({ model: { id: "retired/model", name: "Старая" }, params: { duration: 10, resolution: "480p", aspect_ratio: "1:1" } })), "filled");
  assert.equal(s.composer.model, SEEDANCE);
  assert.equal(s.composer.params.duration, 10);
  assert.equal(s.composer.params.resolution, "480p");
  assert.equal(s.composer.params.aspect_ratio, "1:1");

  // Нечего применить и нечего вписать — исход none, стор не тронут.
  const idle = studio([{ type: "composer/doc", doc: { v: 1, blocks: [[{ t: "text", v: "своё" }]] } }]);
  assert.equal(idle.apply(work({ model: null, params: null })), "none");
  assert.deepEqual(idle.log, []);
});

const RETIRED = { id: "retired/model", name: "Старая" };
const MINE = { type: "composer/doc", doc: { v: 1, blocks: [[{ t: "text", v: "мой сценарий" }]] } };

test("что сказать после нажатия: о выбранной модели — только если её правда выбрали", () => {
  // Обычные исходы: свой текст сохранён — говорим; текст лёг или выбрана модель — видно и так.
  assert.deepEqual(studio([MINE]).use(work()), ["kept", "kept"]);
  assert.deepEqual(studio().use(work()), ["filled", null]);
  assert.deepEqual(studio().use(work({ prompt: null, params: null })), ["set", null]);
  assert.deepEqual(studio().use(work({ model: { id: KLING_LOCKED, name: "Kling v3" } })), ["locked", null]);
});

test("модели работы уже нет: кнопка не молчит и не говорит, что модель выбрана", () => {
  // Запрос скрыт, кнопка — «Выбрать эту модель»: выбрать нечего, стор не тронут.
  const hidden = studio();
  assert.deepEqual(hidden.use(work({ model: RETIRED, prompt: null, params: null })), ["none", "gone"]);
  assert.deepEqual(hidden.log, []);

  // Свой текст в панели: параметры взяты, но модель и цена остались прежними.
  const mine = studio([MINE]);
  assert.deepEqual(mine.use(work({ model: RETIRED, params: { aspect_ratio: "1:1" } })), ["kept", "gone"]);
  assert.equal(mine.composer.model, SEEDANCE);
  assert.equal(mine.composer.params.aspect_ratio, "1:1");
  assert.equal(plainText(mine.composer.doc), "мой сценарий");

  // Работа другого вида: вид переключился, модель подобрал стор — не та, что на карточке.
  const image = studio();
  const poster = work({ kind: "image", video_url: null, image_url: "/media/vstudio/p.png", poster_url: null, model: RETIRED, prompt: null, params: null });
  assert.deepEqual(image.use(poster), ["set", "gone"]);
  assert.equal(image.composer.kind, "image");

  // Текст работы лёг в пустую панель — нажатие видно без подсказки.
  assert.deepEqual(studio().use(work({ model: RETIRED })), ["filled", null]);
});

test("модели ещё не пришли: о пропавшей модели судить рано", () => {
  Sync.resetRunSettingsSync();
  const state = Store.reducer(Store.createInitialState(), MINE);
  assert.equal(state.models, null);
  const outcome = A.applyReelItem(work({ prompt: null, params: null }), state, () => {});
  assert.equal(outcome, "none");
  assert.equal(A.applyNotice(work({ prompt: null, params: null }), state.models, outcome), null);
});

test("модели ещё не пришли: текст всё равно ложится, выбор не падает", () => {
  Sync.resetRunSettingsSync();
  let state = Store.createInitialState();
  const dispatch = (action) => {
    state = Store.reducer(state, action);
  };
  assert.equal(A.applyReelItem(work(), state, dispatch), "filled");
  assert.equal(plainText(state.composer.doc), "Ночной город под дождём");
});
