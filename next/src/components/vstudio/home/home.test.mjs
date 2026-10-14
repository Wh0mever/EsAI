// Первый экран видеостудии: заготовки (home/templates.ts), сценарии карусели (home/scenarios.ts),
// её кадры (home/showreelData.ts) и «Снять похожее» (home/applyItem.ts).
// Запуск (Node 22.6+):  node --experimental-strip-types --test src/components/vstudio/home/*.test.mjs
import "../../../lib/vstudio/nodeTsHooks.mjs";
import { test } from "node:test";
import assert from "node:assert/strict";

const T = await import("./templates.ts");
const C = await import("./scenarios.ts");
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

/* ---------- сценарии карусели ---------- */

test("сценарии карусели: 12 ключей в порядке показа, «Другое» — не сценарий", () => {
  assert.deepEqual(C.SCENARIOS, ["film", "ad", "person", "car", "action", "scifi", "fashion", "music", "i2v", "anim", "real", "vertical"]);
  // Ключ — значение ShowcaseItem.category: у сервера на него 8 знаков.
  for (const key of C.SCENARIOS) assert.ok(key.length <= 8 && C.isScenario(key), key);
  for (const not of ["other", "social", "anime", "", "Film", "constructor", null, undefined, 7]) {
    assert.equal(C.isScenario(not), false, String(not));
  }
});

test("название сценария: перевод по ключу home.scenario.<ключ>, без перевода — русское", () => {
  const calls = [];
  const t = (key, options) => {
    calls.push([key, options]);
    return key === "home.scenario.ad" ? "Product ad" : options.defaultValue;
  };
  assert.equal(C.scenarioLabel(t, "ad"), "Product ad");
  assert.equal(C.scenarioLabel(t, "i2v"), "Image → Video");
  assert.equal(C.scenarioLabel(t, "other"), "Другое");
  assert.deepEqual(calls[0], ["home.scenario.ad", { ns: "vstudio", defaultValue: "Реклама товара" }]);
  // i18next без готового перевода может вернуть не строку — подпись всё равно есть.
  assert.equal(C.scenarioLabel(() => undefined, "film"), "Киносцена");

  // Незнакомый ключ и «без сценария» — пустая строка: подпись берут у самой работы.
  calls.length = 0;
  for (const none of [null, undefined, "", "social", "toString"]) assert.equal(C.scenarioLabel(t, none), "");
  assert.deepEqual(calls, []);

  const names = C.SCENARIOS.map((key) => C.scenarioLabel(t, key));
  assert.equal(new Set(names).size, 12);
  for (const name of names) assert.ok(name && name.length <= 20, name);
});

/* ---------- кадры карусели ---------- */

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
  needs_photo: false,
  start_frame_url: null,
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

/** n работ студии; over(i) — что у i-й по счёту (с нуля) своё. */
const works = (n, over = () => ({})) =>
  S.studioItems({ items: Array.from({ length: n }, (_, i) => showcase({ id: i + 1, ...over(i) })) });
/** n сцен мультстудии, первые picks — выбор редакции. */
const scenes = (n, picks = n) =>
  S.cartoonItems({ presets: Array.from({ length: n }, (_, i) => preset(i + 1, { is_pick: i < picks })) });
const ids = (items) => items.map((i) => i.id);

test("работа видеостудии → карточка: сценарий, модель, запрос и параметры на месте", () => {
  const [item] = S.studioItems({ items: [showcase()] });
  assert.deepEqual(item, {
    id: "vs:12",
    source: "vstudio",
    kind: "video",
    title: "Ночной город",
    subtitle: "Seedance 2.0",
    scenario: "film",
    category: "film",
    video: "/media/vstudio/a.mp4",
    poster: "/media/vstudio/a.jpg",
    aspect: "16:9",
    duration: 5,
    href: null,
    modelId: "bytedance/seedance-2.0",
    prompt: "Ночной город под дождём",
    params: { duration: 5, resolution: "720p", aspect_ratio: "16:9" },
    needsPhoto: false,
    startFrame: null,
    pick: false,
  });
});

test("сценарий работы: ключ из списка; старые ключи сервера переводятся; остальное — без сценария", () => {
  const scenario = (category) => S.studioItems({ items: [showcase({ category })] })[0].scenario;
  for (const key of C.SCENARIOS) assert.equal(scenario(key), key);
  // Сервер прежней версии: social и anime.
  assert.equal(scenario("social"), "vertical");
  assert.equal(scenario("anime"), "anim");
  for (const none of ["other", "", null, undefined, 3, "FILM", "cartoon", "constructor"]) {
    assert.equal(scenario(none), null, String(none));
  }
});

test("работа, снятая с фото: флаг и первый кадр; сервер прежней версии их не присылает", () => {
  const one = (over) => S.studioItems({ items: [showcase(over)] })[0];
  const i2v = one({ needs_photo: true, start_frame_url: "/media/vstudio/thumbs/f.jpg" });
  assert.equal(i2v.needsPhoto, true);
  assert.equal(i2v.startFrame, "/media/vstudio/thumbs/f.jpg");
  // Снято с фото-референсами: фото нужно, а первого кадра нет.
  const refs = one({ needs_photo: true, start_frame_url: null });
  assert.deepEqual([refs.needsPhoto, refs.startFrame], [true, null]);

  const old = one({ needs_photo: undefined, start_frame_url: undefined });
  assert.deepEqual([old.needsPhoto, old.startFrame], [false, null]);
  for (const junk of [{ needs_photo: 1 }, { needs_photo: "true" }, { start_frame_url: "" }, { start_frame_url: 5 }, { start_frame_url: "  " }]) {
    const item = one(junk);
    assert.deepEqual([item.needsPhoto, item.startFrame], [false, null], JSON.stringify(junk));
  }
  // Первый кадр есть, а флаг не дошёл — фото всё равно нужно.
  assert.equal(one({ needs_photo: undefined, start_frame_url: "/media/f.jpg" }).needsPhoto, true);
  // У картинки первого кадра не бывает.
  const image = one({ kind: "image", video_url: null, image_url: "/media/p.png", needs_photo: true, start_frame_url: "/media/f.jpg" });
  assert.deepEqual([image.needsPhoto, image.startFrame], [true, null]);
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
  assert.deepEqual(ids(items), ["vs:1", "vs:3"]);
  const loose = items[1];
  assert.equal(loose.modelId, null);
  assert.equal(loose.subtitle, "");
  assert.equal(loose.category, "other");
  assert.equal(loose.scenario, null);
  assert.equal(loose.aspect, "16:9");
  assert.equal(loose.duration, null);
  assert.equal(loose.params, null);
});

/* ---------- «Тренды» ---------- */

test("«Тренды»: свой список ответа витрины, та же карточка, что у карусели", () => {
  const payload = {
    items: [showcase({ id: 1 })],
    trends: [showcase({ id: 7, title: "Тренд", category: "other" }), showcase({ id: 8, category: "film" })],
  };
  assert.deepEqual(ids(S.studioItems(payload)), ["vs:1"], "карусель «Трендов» не видит");
  const trends = S.trendItems(payload);
  assert.deepEqual(ids(trends), ["vs:7", "vs:8"], "порядок сервера");
  assert.deepEqual(trends[1], S.studioItems({ items: [showcase({ id: 8, category: "film" })] })[0]);
  assert.equal(trends[0].scenario, null, "сценарий «Трендам» не нужен");
  assert.equal(trends[0].title, "Тренд");
});

test("«Тренды»: только ролики, не больше 24; сервер прежней версии и кривой ответ — пусто", () => {
  for (const bad of [null, undefined, "", 42, [], {}, { items: [showcase()] }, { trends: null }, { trends: "x" }, { trends: [null, 1, []] }]) {
    assert.deepEqual(S.trendItems(bad), [], JSON.stringify(bad));
  }
  const picture = showcase({ id: 2, kind: "image", video_url: null, image_url: "/media/vstudio/p.png" });
  const mixed = S.trendItems({ trends: [showcase({ id: 1 }), picture, showcase({ id: 1 }), showcase({ id: 3 })] });
  assert.deepEqual(ids(mixed), ["vs:1", "vs:3"], "картинка и повтор отброшены");

  assert.equal(S.TRENDS_MAX, 24);
  const many = S.trendItems({ trends: Array.from({ length: 30 }, (_, i) => showcase({ id: i + 1 })) });
  assert.deepEqual(ids(many), Array.from({ length: 24 }, (_, i) => `vs:${i + 1}`));
});

test("сцена мультстудии → карточка-ссылка в /studio; без кадра не берём", () => {
  const items = S.cartoonItems({
    categories: [{ slug: "tales", title: "Сказки", emoji: "🧚" }],
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
  assert.deepEqual(ids(items), ["ct:scene-1", "ct:scene-2", "ct:5"]);
  assert.deepEqual(items[0], {
    id: "ct:scene-1",
    source: "cartoon",
    kind: "video",
    title: "Сцена 1",
    subtitle: "Герой идёт по лесу",
    scenario: null,
    category: "tales",
    video: "/media/cartoon/previews/clips/1.mp4",
    poster: "/media/cartoon/posters/thumbs/1.jpg",
    aspect: "16:9",
    duration: 5,
    href: "/studio",
    modelId: null,
    prompt: null,
    params: null,
    needsPhoto: false,
    startFrame: null,
    pick: true,
  });
  assert.equal(items[1].poster, null);
  assert.equal(items[2].category, "");
  for (const bad of [null, "x", [], { presets: {} }]) assert.deepEqual(S.cartoonItems(bad), []);
});

test("карусель: роликов студии нет или меньше пяти — только сцены мультстудии", () => {
  const cartoon = scenes(30, 14);
  for (const n of [0, 3, 4]) {
    const view = S.buildShowreel(works(n), cartoon);
    assert.equal(view.source, "cartoon", `студия: ${n}`);
    assert.equal(view.reel.length, S.REEL_SIZE);
    assert.ok(view.reel.every((i) => i.source === "cartoon" && i.pick), `студия: ${n}`);
  }
});

test("карусель: пять роликов студии — только они, ни одной сцены мультстудии", () => {
  const view = S.buildShowreel(works(5), scenes(30));
  assert.equal(view.source, "vstudio");
  assert.deepEqual(ids(view.reel), ["vs:1", "vs:2", "vs:3", "vs:4", "vs:5"]);
});

test("карусель: 12 сценариев встают в порядке списка, как бы их ни прислал сервер", () => {
  const order = ["vertical", "music", "other", "film", "real", "anim", "i2v", "fashion", "scifi", "action", "car", "person", "ad"];
  const view = S.buildShowreel(works(13, (i) => ({ category: order[i] })), scenes(30));
  assert.equal(view.source, "vstudio");
  assert.deepEqual(view.reel.map((i) => i.scenario), [...C.SCENARIOS]);
  // «Другое» сценарием не считается — на него места не хватило.
  assert.ok(!ids(view.reel).includes("vs:3"));
});

test("карусель: первый ролик каждого сценария, затем остальные — как расставил владелец", () => {
  // Шесть «Киносцен», потом реклама, работа без сценария, ещё реклама и автомобиль.
  const order = ["film", "film", "film", "film", "film", "film", "ad", "other", "ad", "car"];
  const view = S.buildShowreel(works(10, (i) => ({ category: order[i] })), []);
  assert.deepEqual(ids(view.reel), ["vs:1", "vs:7", "vs:10", "vs:2", "vs:3", "vs:4", "vs:5", "vs:6", "vs:8", "vs:9"]);

  // Двадцать роликов одного сценария: первые двенадцать в порядке сервера.
  const many = S.buildShowreel(works(20), scenes(30));
  assert.equal(many.source, "vstudio");
  assert.deepEqual(ids(many.reel), Array.from({ length: 12 }, (_, i) => `vs:${i + 1}`));
});

/* ---------- размер карусели — настройка владельца ---------- */

test("размер карусели: целое от 5 до 48, всё остальное — 12", () => {
  assert.deepEqual([S.REEL_MIN, S.REEL_SIZE, S.REEL_MAX], [5, 12, 48]);
  for (const ok of [5, 6, 12, 18, 24, 36, 47, 48]) assert.equal(S.clampReelSize(ok), ok);
  // За границами — не ближайшая граница, а размер по умолчанию: такое число настройкой не было.
  for (const out of [4, 0, -12, 49, 480, Infinity, -Infinity]) assert.equal(S.clampReelSize(out), 12, String(out));
  for (const junk of [24.5, NaN, "24", "", null, undefined, true, false, [24], { size: 24 }, 24n, () => 24]) {
    assert.equal(S.clampReelSize(junk), 12, String(junk));
  }
});

test("размер карусели из ответа витрины: поле reel_size; сервер прежней версии его не присылает", () => {
  assert.equal(S.reelSizeOf({ items: [], reel_size: 24 }), 24);
  assert.equal(S.reelSizeOf({ items: [], reel_size: 48 }), 48);
  assert.equal(S.reelSizeOf({ items: [] }), 12);
  for (const bad of [{ reel_size: "24" }, { reel_size: 49 }, { reel_size: 4 }, { reel_size: null }, { reelSize: 24 }]) {
    assert.equal(S.reelSizeOf(bad), 12, JSON.stringify(bad));
  }
  for (const bad of [null, undefined, "", 24, [], [{ reel_size: 24 }]]) assert.equal(S.reelSizeOf(bad), 12, String(bad));
});

test("карусель студии режется по размеру владельца; без него — 12, как раньше", () => {
  const studio = works(48, (i) => ({ category: C.SCENARIOS[i % 12] }));
  assert.equal(studio.length, 48);
  assert.equal(S.buildShowreel(studio, scenes(30)).reel.length, 12);
  for (const size of [5, 12, 13, 24, 36, 48]) {
    const view = S.buildShowreel(studio, scenes(30), size);
    assert.equal(view.source, "vstudio", String(size));
    assert.equal(view.reel.length, size, String(size));
    assert.equal(new Set(ids(view.reel)).size, size, String(size));
  }
  // Больше, чем есть роликов, карусель не станет.
  assert.equal(S.buildShowreel(studio.slice(0, 20), [], 48).reel.length, 20);
  // Негодный размер — 12, а не «сколько дали»: тройка увела бы карусель к мультстудии.
  for (const bad of [3, 0, 49, 24.5, NaN, "24", null]) {
    const view = S.buildShowreel(studio, scenes(30), bad);
    assert.deepEqual([view.source, view.reel.length], ["vstudio", 12], String(bad));
  }
  // Тот же размер — та же карусель, что и без него: для 12 ничего не меняется.
  assert.deepEqual(S.buildShowreel(studio, scenes(30), 12), S.buildShowreel(studio, scenes(30)));
});

test("большая карусель: первый ролик каждого сценария, затем остальные в порядке владельца — и за первой дюжиной", () => {
  // Владелец расставил: две киносцены, работа без сценария, три рекламы, автомобиль, ещё «Другое» и киносцена.
  const order = ["film", "film", "other", "ad", "ad", "ad", "car", "other", "film"];
  const studio = works(order.length, (i) => ({ category: order[i] }));
  const all = S.buildShowreel(studio, [], 48);
  assert.deepEqual(ids(all.reel), ["vs:1", "vs:4", "vs:7", "vs:2", "vs:3", "vs:5", "vs:6", "vs:8", "vs:9"]);
  // Размер режет хвост, а не начало: блок «по одному на сценарий» остаётся целым.
  assert.deepEqual(ids(S.buildShowreel(studio, [], 5).reel), ["vs:1", "vs:4", "vs:7", "vs:2", "vs:3"]);

  // Сорок восемь роликов двенадцати сценариев: дюжина в порядке сценариев, остальные 36 — в порядке сервера.
  const full = works(48, (i) => ({ category: C.SCENARIOS[11 - (i % 12)] }));
  const reel = S.buildShowreel(full, scenes(30), 48).reel;
  assert.deepEqual(reel.slice(0, 12).map((i) => i.scenario), [...C.SCENARIOS]);
  assert.deepEqual(ids(reel.slice(12)), Array.from({ length: 36 }, (_, i) => `vs:${i + 13}`));
  // При размере 24 в карусель попадает ровно начало той же очереди.
  assert.deepEqual(ids(S.buildShowreel(full, scenes(30), 24).reel), ids(reel.slice(0, 24)));
});

test("размер владельца — только про ролики студии: карусель мультстудии остаётся в 12 сцен", () => {
  const cartoon = scenes(40, 30);
  // Роликов студии мало — карусель у мультстудии, и её размер прежний.
  for (const size of [5, 24, 48]) {
    const view = S.buildShowreel(works(4), cartoon, size);
    assert.equal(view.source, "cartoon", String(size));
    assert.equal(view.reel.length, 12, String(size));
  }
  // Порог «пять своих роликов» от размера не зависит.
  assert.equal(S.buildShowreel(works(5), cartoon, 48).source, "vstudio");
  assert.equal(S.buildShowreel(works(5), cartoon, 48).reel.length, 5);
  // Картинки в большую карусель тоже не идут.
  const image = (i) => ({ kind: "image", video_url: null, image_url: `/media/vstudio/${i}.png`, poster_url: null });
  const mixed = S.buildShowreel(works(30, (i) => (i % 2 ? image(i) : {})), cartoon, 48);
  assert.equal(mixed.reel.length, 15);
  assert.ok(mixed.reel.every((i) => i.kind === "video"));
});

test("карусель: старые ключи сервера встают на места своих сценариев", () => {
  const order = ["social", "anime", "music", "ad", "film"];
  const view = S.buildShowreel(works(5, (i) => ({ category: order[i] })), []);
  assert.deepEqual(view.reel.map((i) => i.scenario), ["film", "ad", "music", "anim", "vertical"]);
});

test("карусель: картинки студии в неё не идут и до пяти роликов не досчитываются", () => {
  const image = (i) => ({ kind: "image", video_url: null, image_url: `/media/vstudio/${i}.png`, poster_url: null });
  // Четыре ролика и три картинки — роликов мало, карусель у мультстудии.
  const few = S.buildShowreel(works(7, (i) => (i < 3 ? image(i) : {})), scenes(8));
  assert.equal(few.source, "cartoon");
  assert.ok(few.reel.every((i) => i.source === "cartoon"));
  // Пять роликов и картинки между ними — в карусели только ролики.
  const enough = S.buildShowreel(works(8, (i) => (i % 3 === 0 ? image(i) : {})), scenes(8));
  assert.equal(enough.source, "vstudio");
  assert.deepEqual(ids(enough.reel), ["vs:2", "vs:3", "vs:5", "vs:6", "vs:8"]);
});

test("карусель: сцен мультстудии нет — показываем и два своих ролика, а не пустой экран", () => {
  const view = S.buildShowreel(works(2), []);
  assert.equal(view.source, "vstudio");
  assert.deepEqual(ids(view.reel), ["vs:1", "vs:2"]);
  assert.equal(view.cartoonPoster, null);
  // Нет ни роликов, ни сцен (или у студии одни картинки) — карусели нет.
  assert.deepEqual(S.buildShowreel([], []), S.EMPTY_SHOWREEL);
  assert.deepEqual(S.EMPTY_SHOWREEL, { reel: [], source: null, cartoonPoster: null });
  const images = works(3, (i) => ({ kind: "image", video_url: null, image_url: `/media/vstudio/${i}.png` }));
  assert.deepEqual(S.buildShowreel(images, []), S.EMPTY_SHOWREEL);
});

test("карусель мультстудии: отмеченных сцен хватает — обычные не добавляются", () => {
  const view = S.buildShowreel([], scenes(20, 6));
  assert.equal(view.source, "cartoon");
  assert.equal(view.reel.length, 6);
  assert.ok(view.reel.every((i) => i.pick));
});

test("карусель мультстудии: отмеченных мало — добираем до пяти, сначала из других разделов и только с постером", () => {
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
  });
  const view = S.buildShowreel([], cartoon);
  assert.deepEqual(ids(view.reel), ["ct:scene-1", "ct:scene-5", "ct:scene-6", "ct:scene-2", "ct:scene-3"]);
  assert.equal(new Set(ids(view.reel)).size, S.REEL_MIN);

  // Сцен всего три — карусель из трёх, без повторов и без падения.
  const few = S.buildShowreel([], cartoon.slice(0, 3));
  assert.equal(few.reel.length, 3);
});

test("постер для карточки «Мультстудия»: из карусели, если она мультстудии, иначе — первой сцены с постером", () => {
  const cartoon = S.cartoonItems({
    presets: [
      preset(1, { preview_poster: "" }),
      preset(2),
      ...Array.from({ length: 6 }, (_, i) => preset(i + 3, { is_pick: true, ...(i === 0 ? { preview_poster: "" } : {}) })),
    ],
  });
  // Карусель у мультстудии: постер сцены, которая в ней уже стоит (первая отмеченная — без постера).
  assert.equal(S.buildShowreel(works(2), cartoon).cartoonPoster, "/media/cartoon/posters/thumbs/4.jpg");
  // Карусель у студии: сцен на экране нет — первая сцена с постером.
  const own = S.buildShowreel(works(5), cartoon);
  assert.equal(own.source, "vstudio");
  assert.equal(own.cartoonPoster, "/media/cartoon/posters/thumbs/2.jpg");
  // Постеров нет ни у одной сцены.
  const bare = S.cartoonItems({ presets: [preset(1, { preview_poster: "" })] });
  assert.equal(S.buildShowreel(works(5), bare).cartoonPoster, null);
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
    // starters — заготовки первого экрана (starters.homeStarters); без них заменяется только пустой запрос.
    apply: (item, starters) => A.applyReelItem(item, state, dispatch, starters),
    // Как в StudioHome: что применилось и что об этом сказать — по состоянию до нажатия.
    use: (item, starters) => {
      const { models, composer } = state;
      const outcome = A.applyReelItem(item, state, dispatch, starters);
      return [outcome, A.applyNotice(item, models, outcome, composer.kind)];
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

/* ---------- пример за примером ---------- */

const St = await import("./starters.ts");
const { exampleDoc, starterReplaceable } = await import("../feed/examples.ts");

const ruT = (key, options) => options.defaultValue;
const NIGHT = work();
const LATTE = work({
  id: 13,
  model: { id: SEEDANCE, name: "Seedance 2.0" },
  prompt: "Бариста наливает матча-латте в высокий стакан",
  params: { duration: 5, resolution: "720p", aspect_ratio: "9:16" },
});
/** Заготовки первого экрана при карусели из двух роликов. */
const STARTERS = St.homeStarters(ruT, [NIGHT, LATTE]);

test("заготовки первого экрана: сценарии — исходник и перевод — и запросы роликов карусели", () => {
  const film = T.VS_TEMPLATES.find((t) => t.id === "film").prompt;
  assert.ok(STARTERS.includes(film));
  assert.ok(STARTERS.includes(NIGHT.prompt) && STARTERS.includes(LATTE.prompt));
  assert.equal(STARTERS.length, T.VS_TEMPLATES.length + 2, "перевод, равный исходнику, второй раз не кладём");

  // Заготовку могли взять до смены языка: в списке и русский исходник, и перевод.
  const calls = [];
  const enT = (key, options) => {
    calls.push(key);
    return key === "home.tpl.film.prompt" ? "Cinematic shot: [who] [does what] in [where]." : options.defaultValue;
  };
  const en = St.homeStarters(enT, []);
  assert.ok(en.includes(film) && en.includes("Cinematic shot: [who] [does what] in [where]."));
  assert.deepEqual(calls, T.VS_TEMPLATES.map((t) => `home.tpl.${t.id}.prompt`));
  // i18next без готового перевода может вернуть не строку — исходник всё равно в списке.
  assert.deepEqual(St.homeStarters(() => undefined, []), T.VS_TEMPLATES.map((t) => t.prompt));

  // Запрос скрыт владельцем, сцена мультстудии — подставлять было нечего, заменять тоже.
  const hidden = work({ id: 14, prompt: null });
  const [scene] = scenes(1);
  assert.equal(St.homeStarters(ruT, [hidden, scene]).length, T.VS_TEMPLATES.length);
});

test("пример за примером: текст прошлого примера заменяется новым вместе с моделью", () => {
  const s = studio();
  assert.equal(s.apply(NIGHT, STARTERS), "filled");
  assert.equal(s.composer.model, VEO);
  // Второй пример: модель, длительность и текст — все его, а не «его модель с чужим текстом».
  assert.deepEqual(s.use(LATTE, STARTERS), ["filled", null]);
  assert.equal(s.composer.model, SEEDANCE);
  assert.equal(s.composer.params.duration, 5);
  assert.equal(plainText(s.composer.doc), LATTE.prompt);
  // Повторное нажатие на тот же пример — то же самое, без «текст запроса не тронули».
  assert.deepEqual(s.use(LATTE, STARTERS), ["filled", null]);
  assert.equal(plainText(s.composer.doc), LATTE.prompt);

  // Без списка заготовок заменяется только пустой запрос — как раньше.
  assert.deepEqual(s.use(NIGHT), ["kept", "kept"]);
  assert.equal(plainText(s.composer.doc), LATTE.prompt);
  // Ролик ушёл из карусели, пока его текст стоял в запросе, — чей он, уже не узнать: не трогаем.
  assert.equal(s.apply(NIGHT, St.homeStarters(ruT, [NIGHT])), "kept");
});

test("пример за примером: поправленный текст примера и текст с отметкой @ — уже свои", () => {
  const edited = studio([{ type: "composer/doc", doc: exampleDoc(`${NIGHT.prompt} И туман.`) }]);
  assert.deepEqual(edited.use(LATTE, STARTERS), ["kept", "kept"]);
  assert.equal(plainText(edited.composer.doc), `${NIGHT.prompt} И туман.`);
  assert.ok(!edited.log.includes("composer/doc"));

  // Текст примера тот же, но человек отметил в нём своё фото.
  const tagged = { v: 1, blocks: [[{ t: "text", v: NIGHT.prompt }, { t: "ref", asset: "asset-1" }]] };
  const withRef = studio([{ type: "composer/doc", doc: tagged }]);
  assert.equal(plainText(withRef.composer.doc), NIGHT.prompt);
  assert.equal(withRef.apply(LATTE, STARTERS), "kept");
  assert.deepEqual(withRef.composer.doc, tagged);

  // Свой текст с нуля — тем более.
  assert.equal(studio([{ type: "composer/doc", doc: exampleDoc("мой сценарий") }]).apply(LATTE, STARTERS), "kept");
});

test("пример из «Трендов» за примером из карусели и наоборот: текст прошлого заменяется", () => {
  // StudioHome кладёт в заготовки запросы и карусели, и «Трендов».
  const TREND = S.trendItems({
    trends: [
      showcase({
        id: 31,
        model: { id: SEEDANCE, name: "Seedance 2.0" },
        prompt: "Кот в очках читает газету в кафе",
        params: { duration: 5, resolution: "720p", aspect_ratio: "16:9" },
      }),
    ],
  })[0];
  const both = St.homeStarters(ruT, [NIGHT, LATTE, TREND]);
  const s = studio();
  assert.equal(s.apply(NIGHT, both), "filled");
  assert.deepEqual(s.use(TREND, both), ["filled", null]);
  assert.equal(s.composer.model, SEEDANCE);
  assert.equal(plainText(s.composer.doc), TREND.prompt);
  assert.deepEqual(s.use(LATTE, both), ["filled", null]);
  assert.equal(plainText(s.composer.doc), LATTE.prompt);

  // Без запросов «Трендов» текст тренда сошёл бы за свой: модель сменилась бы, а текст — нет.
  const s2 = studio();
  s2.apply(TREND, both);
  assert.deepEqual(s2.use(LATTE, STARTERS), ["kept", "kept"]);
  // Заготовкой текст тренда становится и для чипов сценариев.
  assert.equal(starterReplaceable(s2.composer.doc, both), true);
});

test("пример и сценарий «С чего начать» заменяют друг друга, пока текст не тронут", () => {
  // Чип после примера: запрос ролика карусели — такая же заготовка.
  const s = studio();
  s.apply(NIGHT, STARTERS);
  assert.equal(starterReplaceable(s.composer.doc, STARTERS), true);
  assert.equal(starterReplaceable(s.composer.doc, St.homeStarters(ruT, [])), false, "без роликов карусели чип бы отказал");

  // Пример после чипа: заготовка сценария в запросе — не свой текст.
  const poster = T.VS_TEMPLATES.find((t) => t.id === "poster");
  const fromChip = studio([
    { type: "composer/kind", kind: "image" },
    { type: "composer/model", model: FLUX },
    { type: "composer/doc", doc: exampleDoc(poster.prompt) },
  ]);
  assert.deepEqual(fromChip.use(LATTE, STARTERS), ["filled", null]);
  assert.equal(fromChip.composer.kind, "video");
  assert.equal(plainText(fromChip.composer.doc), LATTE.prompt);

  // Скобки в заготовке заполнили — это уже свой текст.
  const filled = studio([{ type: "composer/doc", doc: exampleDoc(poster.prompt.replace("[сюжет]", "юрта в горах")) }]);
  assert.equal(filled.apply(LATTE, STARTERS), "kept");
});

test("работа без запроса: выбирается только модель — исход set", () => {
  const s = studio();
  assert.equal(s.apply(work({ prompt: null, params: null })), "set");
  assert.equal(s.composer.model, VEO);
  assert.equal(plainText(s.composer.doc), "");
});

test("картинка студии при выбранном видео: вид и модель переключаются", () => {
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

const LOCKED = { id: KLING_LOCKED, name: "Kling v3" };
const RETIRED = { id: "retired/model", name: "Старая" };
const MINE = { type: "composer/doc", doc: { v: 1, blocks: [[{ t: "text", v: "мой сценарий" }]] } };
/** Замок не должен вести ни к пэйволлу, ни к окну входа, ни к смене модели. */
const quiet = (log) => !log.some((type) => type.startsWith("ui/") || type === "composer/model" || type === "composer/kind");

test("модель под замком: пример всё равно применяется — на своей модели", () => {
  const s = studio();
  // 10 секунд, 720p и 1:1 умеет и Seedance, на которой человек остаётся.
  const outcome = s.apply(work({ model: LOCKED, params: { duration: 10, resolution: "720P", aspect_ratio: "1:1" } }));
  assert.equal(outcome, "filled_locked");
  assert.equal(s.composer.model, SEEDANCE);
  assert.equal(s.composer.params.duration, 10);
  assert.equal(s.composer.params.resolution, "720p");
  assert.equal(s.composer.params.aspect_ratio, "1:1");
  assert.equal(plainText(s.composer.doc), "Ночной город под дождём");
  assert.deepEqual(s.log, ["composer/params", "composer/doc"]);
});

test("модель под замком: параметры — только те, что умеет своя модель", () => {
  const s = studio([{ type: "composer/model", model: VEO }]);
  const before = { ...s.composer.params };
  // Veo не снимает 5 секунд и 1:1 — эти значения остаются её собственными.
  assert.equal(s.apply(work({ model: LOCKED, params: { duration: 5, resolution: "720p", aspect_ratio: "1:1" } })), "filled_locked");
  assert.equal(s.composer.model, VEO);
  assert.equal(s.composer.params.duration, before.duration);
  assert.equal(s.composer.params.aspect_ratio, before.aspect_ratio);
  assert.equal(s.composer.params.resolution, "720p");
  assert.ok(quiet(s.log), s.log.join(","));
});

test("модель под замком: свой текст не затирается, а без запроса и параметров стор не тронут", () => {
  const mine = studio([MINE]);
  assert.equal(mine.apply(work({ model: LOCKED, params: { aspect_ratio: "1:1" } })), "locked");
  assert.equal(mine.composer.model, SEEDANCE);
  assert.equal(mine.composer.params.aspect_ratio, "1:1");
  assert.equal(plainText(mine.composer.doc), "мой сценарий");
  assert.deepEqual(mine.log, ["composer/params"]);

  // Запрос скрыт, кнопка — «Выбрать эту модель»: выбрать её нельзя, менять нечего.
  const hidden = studio();
  assert.equal(hidden.apply(work({ model: LOCKED, prompt: null, params: null })), "locked");
  assert.deepEqual(hidden.log, []);
  assert.equal(hidden.composer.model, SEEDANCE);
});

test("модель под замком, а в панели картинка: вид меняется, модель видео — своя", () => {
  const onImage = [
    { type: "composer/kind", kind: "image" },
    { type: "composer/model", model: FLUX },
  ];
  const s = studio(onImage);
  // «Модель осталась ваша» здесь неправда: вид и модель сменились — говорим о переключении.
  assert.deepEqual(s.use(work({ model: LOCKED })), ["filled_locked", "locked_switched"]);
  assert.equal(s.composer.kind, "video");
  assert.equal(s.composer.model, SEEDANCE, "первая доступная, а не модель под замком");
  assert.equal(plainText(s.composer.doc), "Ночной город под дождём");
  assert.ok(!s.log.some((type) => type.startsWith("ui/")), s.log.join(","));

  // В панели свой текст: он остался, а вид и модель всё равно сменились.
  const mine = studio([...onImage, MINE]);
  assert.deepEqual(mine.use(work({ model: LOCKED })), ["locked", "locked_switched_kept"]);
  assert.equal(mine.composer.kind, "video");
  assert.equal(mine.composer.model, SEEDANCE);
  assert.equal(plainText(mine.composer.doc), "мой сценарий");

  // Запрос работы скрыт: подставлять нечего, о своём тексте речи нет — с ним или без него.
  const bare = work({ model: LOCKED, prompt: null, params: null });
  assert.deepEqual(studio(onImage).use(bare), ["locked", "locked_switched"]);
  assert.deepEqual(studio([...onImage, MINE]).use(bare), ["locked", "locked_switched"]);

  // Вид до нажатия не назвали — считаем, что он тот же: слова прежние.
  assert.equal(A.applyNotice(work({ model: LOCKED }), FIXTURE_MODELS, "filled_locked"), "locked_filled");
  assert.equal(A.applyNotice(work({ model: LOCKED }), FIXTURE_MODELS, "locked", "video"), "locked_kept");
  // Модель примера уже выбрана в панели (гость: модель по умолчанию под замком) —
  // «модель осталась ваша» было бы про неё же; о замке молчим.
  const lockedId = work({ model: LOCKED }).modelId;
  assert.equal(A.applyNotice(work({ model: LOCKED }), FIXTURE_MODELS, "filled_locked", "video", lockedId), null);
  assert.equal(A.applyNotice(work({ model: LOCKED }), FIXTURE_MODELS, "locked", "video", lockedId), "kept");
  assert.equal(A.applyNotice(work({ model: LOCKED }), FIXTURE_MODELS, "filled_locked", "video", "other/model"), "locked_filled");
  // Вид переключился — модель подобрал стор, совпадение прежней модели ничего не значит.
  assert.equal(A.applyNotice(work({ model: LOCKED }), FIXTURE_MODELS, "filled_locked", "image", lockedId), "locked_switched");
  // Замка нет — смена вида видна и так, отдельных слов для неё нет.
  assert.deepEqual(studio(onImage).use(work()), ["filled", null]);
});

test("модели работы уже нет: остаёмся на своей, берём подходящие параметры и текст", () => {
  const s = studio();
  assert.equal(s.apply(work({ model: RETIRED, params: { duration: 10, resolution: "480p", aspect_ratio: "1:1" } })), "filled");
  assert.equal(s.composer.model, SEEDANCE);
  assert.equal(s.composer.params.duration, 10);
  assert.equal(s.composer.params.resolution, "480p");
  assert.equal(s.composer.params.aspect_ratio, "1:1");

  // Нечего применить и нечего вписать — исход none, стор не тронут.
  const idle = studio([{ type: "composer/doc", doc: { v: 1, blocks: [[{ t: "text", v: "своё" }]] } }]);
  assert.equal(idle.apply(work({ model: null, params: null })), "none");
  assert.deepEqual(idle.log, []);
});

test("что сказать после нажатия: о выбранной модели — только если её правда выбрали", () => {
  // Обычные исходы: свой текст сохранён — говорим; текст лёг или выбрана модель — видно и так.
  assert.deepEqual(studio([MINE]).use(work()), ["kept", "kept"]);
  assert.deepEqual(studio().use(work()), ["filled", null]);
  assert.deepEqual(studio().use(work({ prompt: null, params: null })), ["set", null]);
});

test("модель под замком: о платной модели говорим всегда — и что стало с запросом", () => {
  // Текст работы лёг в пустую панель; модель осталась своя.
  assert.deepEqual(studio().use(work({ model: LOCKED })), ["filled_locked", "locked_filled"]);
  // В панели свой текст — он и остался.
  assert.deepEqual(studio([MINE]).use(work({ model: LOCKED })), ["locked", "locked_kept"]);
  // Запрос работы скрыт — подставлять было нечего.
  assert.deepEqual(studio().use(work({ model: LOCKED, prompt: null, params: null })), ["locked", "locked"]);
  assert.deepEqual(studio([MINE]).use(work({ model: LOCKED, prompt: null })), ["locked", "locked"]);
});

test("модель под замком: повторное нажатие на тот же пример говорит то же самое", () => {
  const paid = work({ model: LOCKED });
  const starters = St.homeStarters(ruT, [paid]);
  const s = studio();
  // Раньше второе нажатие называло текст самого примера «вашим» — две подсказки спорили друг с другом.
  assert.deepEqual(s.use(paid, starters), ["filled_locked", "locked_filled"]);
  assert.deepEqual(s.use(paid, starters), ["filled_locked", "locked_filled"]);
  assert.equal(s.composer.model, SEEDANCE);
  assert.equal(plainText(s.composer.doc), paid.prompt);
});

test("название модели в подсказке: как в списке моделей студии, иначе — как подписана работа", () => {
  assert.equal(A.reelModelName(work({ model: LOCKED }), FIXTURE_MODELS), "Kling v3 Standard");
  assert.equal(A.reelModelName(work({ model: LOCKED }), null), "Kling v3");
  assert.equal(A.reelModelName(work({ model: RETIRED }), FIXTURE_MODELS), "Старая");
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
  // О замке без списка моделей тоже судить рано: пример ложится как обычный.
  assert.equal(A.applyReelItem(work({ model: LOCKED }), state, dispatch), "filled");
  assert.equal(plainText(state.composer.doc), "Ночной город под дождём");
});

/* ---------- пример, снятый по фото ---------- */

const PHOTO = { needs_photo: true, start_frame_url: "/media/vstudio/thumbs/f.jpg" };
const chip = (over = {}) => ({
  lid: "c1",
  assetUid: "asset-1",
  slot: "first_frame",
  role: "",
  included: true,
  status: "ready",
  progress: 100,
  preview: null,
  ...over,
});
const withChip = (over) => studio([{ type: "tray/add", item: chip(over) }]).composer;

test("пример снят по фото: просим своё, пока фото в запросе нет", () => {
  const photo = work(PHOTO);
  assert.equal(A.wantsPhoto(photo, studio().composer), true);
  assert.equal(A.wantsPhoto(work(), studio().composer), false, "обычный пример фото не просит");
  // Кадр или включённый референс уже в запросе — просить нечего.
  assert.equal(A.wantsPhoto(photo, withChip()), false);
  assert.equal(A.wantsPhoto(photo, withChip({ slot: "last_frame" })), false);
  assert.equal(A.wantsPhoto(photo, withChip({ slot: "reference" })), false);
  // Выключенное и не загрузившееся фото в запрос не уйдёт — просим.
  assert.equal(A.wantsPhoto(photo, withChip({ slot: "reference", included: false })), true);
  assert.equal(A.wantsPhoto(photo, withChip({ status: "failed" })), true);
});

test("пример снят по фото: применяется как обычный, чужое фото в запрос не попадает", () => {
  const s = studio();
  const photo = work(PHOTO);
  assert.deepEqual(s.use(photo), ["filled", null]);
  assert.equal(s.composer.model, VEO);
  assert.deepEqual(s.composer.tray, []);
  assert.deepEqual(s.composer.frames, { first_frame: null, last_frame: null });
  assert.ok(!s.log.some((type) => type.startsWith("tray/") || type.startsWith("ui/")), s.log.join(","));
  // Фото всё ещё нужно: подсказку и слоты кадров показывает StudioHome.
  assert.equal(A.wantsPhoto(photo, s.composer), true);

  // То же с моделью под замком: и про модель скажем, и фото попросим.
  const locked = studio();
  const paid = work({ ...PHOTO, model: LOCKED });
  assert.deepEqual(locked.use(paid), ["filled_locked", "locked_filled"]);
  assert.equal(A.wantsPhoto(paid, locked.composer), true);
});
