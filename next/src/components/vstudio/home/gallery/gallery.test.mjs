// Галерея «Сделано в EsAI»: вкладки, отбор карточек и порции (home/gallery/galleryModel.ts).
// Запуск (Node 22.6+):  node --experimental-strip-types --test src/components/vstudio/home/gallery/*.test.mjs
import "../../../../lib/vstudio/nodeTsHooks.mjs";
import { test } from "node:test";
import assert from "node:assert/strict";

const G = await import("./galleryModel.ts");
const S = await import("../showreelData.ts");

const scene = (n, category, over = {}) => ({
  id: `ct:scene-${n}`,
  source: "cartoon",
  kind: "video",
  title: `Сцена ${n}`,
  subtitle: "Герой идёт по лесу",
  category,
  video: `/media/cartoon/previews/clips/${n}.mp4`,
  poster: `/media/cartoon/posters/thumbs/${n}.jpg`,
  aspect: "16:9",
  duration: 5,
  href: "/studio",
  modelId: null,
  prompt: null,
  params: null,
  pick: false,
  ...over,
});

const work = (n, over = {}) => ({
  id: `vs:${n}`,
  source: "vstudio",
  kind: "video",
  title: `Работа ${n}`,
  subtitle: "Seedance 2.0",
  category: "film",
  video: `/media/vstudio/${n}.mp4`,
  poster: `/media/vstudio/${n}.jpg`,
  aspect: "16:9",
  duration: 5,
  href: null,
  modelId: "bytedance/seedance-2.0",
  prompt: "Ночной город под дождём",
  params: { duration: 5 },
  pick: false,
  ...over,
});

let serial = 0;
const scenes = (count, category) => Array.from({ length: count }, () => scene(++serial, category));
const cat = (slug, title, count) => ({ slug, title, count });
const ids = (tabs) => tabs.map((tab) => tab.id);

/* ---------- вкладки ---------- */

test("вкладки: «Все», «Видеостудия», затем разделы мультстудии от самых полных", () => {
  const items = [work(1), work(2), ...scenes(5, "tales"), ...scenes(9, "space"), ...scenes(4, "animals")];
  const tabs = G.galleryTabs(items, [cat("tales", "Сказки", 5), cat("space", "Космос", 9), cat("animals", "Животные", 4)], true);
  assert.deepEqual(ids(tabs), ["all", "studio", "ct:space", "ct:tales", "ct:animals"]);
  assert.deepEqual(
    tabs.map((tab) => tab.count),
    [20, 2, 9, 5, 4],
  );
  // «Все» и «Видеостудия» подписывает галерея, разделы — сервер.
  assert.deepEqual(
    tabs.map((tab) => tab.title),
    [null, null, "Космос", "Сказки", "Животные"],
  );
});

test("вкладки: раздел короче четырёх сцен и раздел без названия вкладкой не становятся", () => {
  const items = [...scenes(6, "tales"), ...scenes(3, "space"), ...scenes(5, "nameless")];
  const tabs = G.galleryTabs(items, [cat("tales", "Сказки", 6), cat("space", "Космос", 3), cat("nameless", "", 5)], false);
  assert.deepEqual(ids(tabs), ["all", "ct:tales"]);
});

test("вкладки: разделов не больше восьми, при равном счёте — порядок сервера", () => {
  const slugs = Array.from({ length: 11 }, (_, i) => `c${i}`);
  const items = slugs.flatMap((slug, i) => scenes(i === 10 ? 7 : 4, slug));
  const tabs = G.galleryTabs(
    items,
    slugs.map((slug) => cat(slug, slug.toUpperCase(), 4)),
    false,
  );
  assert.deepEqual(ids(tabs), ["all", "ct:c10", "ct:c0", "ct:c1", "ct:c2", "ct:c3", "ct:c4", "ct:c5", "ct:c6"]);
});

test("вкладки: счёт идёт по самим карточкам, а не по присланным числам", () => {
  const items = [...scenes(4, "tales"), ...scenes(2, "space")];
  // Сервер «обещал» в космосе 40 сцен, но карточек всего две — вкладки не будет.
  const tabs = G.galleryTabs(items, [cat("tales", "Сказки", 1), cat("space", "Космос", 40)], false);
  assert.deepEqual(ids(tabs), ["all", "ct:tales"]);
  assert.equal(tabs[1].count, 4);
});

test("вкладки: когда выбирать не из чего, их нет вовсе", () => {
  // Только сцены одного раздела: вкладка повторяла бы «Все».
  const one = scenes(6, "tales");
  assert.deepEqual(G.galleryTabs(one, [cat("tales", "Сказки", 6)], false), []);
  // Только работы видеостудии: «Видеостудия» — то же, что «Все».
  assert.deepEqual(G.galleryTabs([work(1), work(2)], [], true), []);
  // Мелкие разделы и пустая витрина.
  assert.deepEqual(G.galleryTabs([...scenes(3, "a"), ...scenes(3, "b")], [cat("a", "А", 3), cat("b", "Б", 3)], false), []);
  assert.deepEqual(G.galleryTabs([], [], false), []);
});

test("вкладки: «Видеостудии» нет, пока витрина о ней не сказала", () => {
  const items = [work(1), ...scenes(4, "tales"), ...scenes(4, "space")];
  const tabs = G.galleryTabs(items, [cat("tales", "Сказки", 4), cat("space", "Космос", 4)], false);
  assert.deepEqual(ids(tabs), ["all", "ct:tales", "ct:space"]);
});

test("вкладки: раздел мультстудии по имени all или studio не путается с нашими", () => {
  const items = [work(1), ...scenes(4, "all"), ...scenes(5, "studio")];
  const tabs = G.galleryTabs(items, [cat("all", "Разное", 4), cat("studio", "В студии", 5)], true);
  assert.deepEqual(ids(tabs), ["all", "studio", "ct:studio", "ct:all"]);
  assert.equal(G.tabItems(items, "studio").length, 1);
  assert.equal(G.tabItems(items, "ct:studio").length, 5);
  assert.equal(G.tabItems(items, "ct:all").length, 4);
  assert.equal(G.tabItems(items, "all").length, 10);
});

test("выбранная вкладка исчезла — возвращаемся ко «Все»", () => {
  const items = [...scenes(4, "tales"), ...scenes(4, "space")];
  const tabs = G.galleryTabs(items, [cat("tales", "Сказки", 4), cat("space", "Космос", 4)], false);
  assert.equal(G.currentTab(tabs, "ct:space"), "ct:space");
  assert.equal(G.currentTab(tabs, "ct:gone"), "all");
  assert.equal(G.currentTab(tabs, "studio"), "all");
  assert.equal(G.currentTab([], "ct:space"), "all");
});

/* ---------- содержимое вкладки ---------- */

test("карточки вкладки идут в порядке витрины; работа видеостудии в раздел мультстудии не попадает", () => {
  const tales = scenes(4, "tales");
  // У работ видеостудии свои категории (film, ad…) — совпадение имён не должно их смешать.
  const items = [work(1, { category: "tales" }), tales[0], scene(900, "space"), ...tales.slice(1)];
  assert.deepEqual(G.tabItems(items, "all"), items);
  assert.deepEqual(G.tabItems(items, "studio").map((item) => item.id), ["vs:1"]);
  assert.deepEqual(
    G.tabItems(items, "ct:tales").map((item) => item.id),
    tales.map((item) => item.id),
  );
  assert.deepEqual(G.tabItems(items, "ct:none"), []);
});

/* ---------- порции ---------- */

test("первая порция — 12 карточек, на телефоне 8; «Показать ещё» добавляет по 12", () => {
  assert.equal(G.pageLimit(4, 0), 12);
  assert.equal(G.pageLimit(3, 0), 12);
  assert.equal(G.pageLimit(2, 0), 8);
  assert.equal(G.pageLimit(2, 1), 20);
  assert.equal(G.pageLimit(4, 2), 36);
  assert.equal(G.pageLimit(3, -1), 12);
});

test("карточки ряда появляются по очереди, задержка не больше 240 мс", () => {
  assert.deepEqual([0, 1, 2, 3, 4, 5].map((i) => G.revealDelay(i, 4)), [0, 60, 120, 180, 0, 60]);
  assert.deepEqual([0, 1, 2, 3].map((i) => G.revealDelay(i, 2)), [0, 60, 0, 60]);
  for (const cols of [2, 3, 4]) {
    for (let i = 0; i < 24; i++) assert.ok(G.revealDelay(i, cols) <= 240);
  }
  assert.equal(G.revealDelay(5, 0), 0);
});

/* ---------- подписи ---------- */

test("подзаголовок не обещает того, чего в витрине нет", () => {
  assert.equal(G.galleryMix([work(1), scene(1, "tales")], true), "mixed");
  assert.equal(G.galleryMix([work(1)], true), "studio");
  assert.equal(G.galleryMix([scene(1, "tales")], false), "cartoon");
});

test("действие карточки: сцена, «снять похожее», а без запроса — только модель", () => {
  assert.equal(G.cardAction(scene(1, "tales")), "scene");
  assert.equal(G.cardAction(work(1)), "similar");
  assert.equal(G.cardAction(work(2, { prompt: null })), "model");
  // Ни запроса, ни модели: остаются параметры — это всё ещё «похожее».
  assert.equal(G.cardAction(work(3, { prompt: null, modelId: null })), "similar");
});

/* ---------- вместе с настоящей сборкой витрины ---------- */

test("настоящая витрина: вкладки сходятся с тем, что отдаёт buildShowreel", () => {
  const preset = (n, category) => ({
    id: n,
    slug: `scene-${n}`,
    title: `Сцена ${n}`,
    subtitle: "",
    preview_video: `/media/cartoon/previews/clips/${n}.mp4`,
    preview_poster: `/media/cartoon/posters/thumbs/${n}.jpg`,
    duration: 5,
    aspect_ratio: "16:9",
    category,
    is_pick: n % 5 === 0,
  });
  const presets = [
    ...Array.from({ length: 7 }, (_, i) => preset(i + 1, "tales")),
    ...Array.from({ length: 12 }, (_, i) => preset(i + 100, "space")),
    ...Array.from({ length: 2 }, (_, i) => preset(i + 200, "rare")),
  ];
  const cartoon = S.cartoonItems({
    categories: [
      { slug: "tales", title: "Сказки" },
      { slug: "space", title: "Космос" },
      { slug: "rare", title: "Редкое" },
    ],
    presets,
  });
  const studio = S.studioItems({
    items: [{ id: 1, title: "Ночной город", kind: "video", video_url: "/media/vstudio/a.mp4", poster_url: "/media/vstudio/a.jpg" }],
  });
  const data = S.buildShowreel(studio, cartoon.items, cartoon.titles);
  const tabs = G.galleryTabs(data.all, data.categories, data.hasStudio);
  assert.deepEqual(ids(tabs), ["all", "studio", "ct:space", "ct:tales"]);
  // Сумма вкладок меньше «Всех» ровно на сцены раздела, который вкладкой не стал.
  assert.equal(tabs[0].count, 22);
  assert.equal(G.tabItems(data.all, "ct:space").length, 12);
  assert.equal(G.tabItems(data.all, "studio")[0].id, "vs:1");
  // Первая порция «Всех» начинается с работ видеостудии.
  assert.equal(data.all.slice(0, G.pageLimit(2, 0))[0].source, "vstudio");
});
