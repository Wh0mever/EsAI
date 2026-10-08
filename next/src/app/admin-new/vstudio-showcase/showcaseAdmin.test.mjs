// Админка, витрина видеостудии: разбор ответов сервера, тела запросов, порядок и карусель (showcaseAdmin.ts).
// Запуск (Node 22.6+):  node --experimental-strip-types --test src/app/admin-new/vstudio-showcase/showcaseAdmin.test.mjs
// Хук нужен одной проверке — сверке с первым экраном: его модули импортируют друг друга без расширения.
import "../../../lib/vstudio/nodeTsHooks.mjs";
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import {
  SCENARIOS,
  SHOWCASE_PATH,
  addBody,
  addDefaults,
  applyMove,
  carousel,
  errorText,
  insertItem,
  itemPath,
  listPath,
  nextPage,
  parseItem,
  parseList,
  patchBody,
  placesOf,
  planMove,
  previousOf,
  publicOrder,
  sortForNew,
  titleForScenario,
} from "./showcaseAdmin.ts";

// Строки в том виде, как их собирает core/vstudio/showcase.py (take_row, staff_json).
const take = (over = {}) => ({
  uid: "a".repeat(32),
  status: "done",
  kind: "video",
  model: { id: "bytedance/seedance-2.0", name: "Seedance 2.0" },
  aspect_ratio: "16:9",
  duration_s: 5,
  width: 1280,
  height: 720,
  video_url: "/media/vstudio/a.mp4",
  image_url: null,
  poster_url: "/media/vstudio/a.jpg",
  prompt: "Ночной город, неон",
  params: { duration: 5, resolution: "720p", aspect_ratio: "16:9" },
  own_photos: false,
  start_frame_url: null,
  public_ok: true,
  user_email: "staff@esai.kg",
  user_is_staff: true,
  created_at: "2026-10-07T10:00:00+06:00",
  finished_at: "2026-10-07T10:01:30+06:00",
  ...over,
});

const row = (over = {}) => ({
  id: 12,
  title: "Ночной город",
  category: "film",
  sort: 0,
  is_active: true,
  show_prompt: true,
  state: "live",
  created_by_email: "owner@esai.kg",
  created_at: "2026-10-07T11:00:00+06:00",
  updated_at: "2026-10-07T11:00:00+06:00",
  take: take(),
  ...over,
});

const listBody = (over = {}) => ({
  items: [row()],
  candidates: { count: 73, page_size: 50, results: [take({ uid: "b".repeat(32) })] },
  scope: "staff",
  categories: [
    { key: "film", label: "Киносцена" },
    { key: "music", label: "Музыкальный клип" },
  ],
  public_limit: 48,
  ...over,
});

/** Работа для проверок порядка: нужны только id и sort, остальное — как у настоящей. */
const item = (id, sort, over = {}) => ({ ...parseItem(row({ id, sort })), ...over });

/** Порядок сервера: sort по возрастанию, при равных — новые (больший id) выше. */
const serverOrder = (list) => list.slice().sort((a, b) => a.sort - b.sort || b.id - a.id);

/** Сценарии и порядок карусели — таблица из брифа «12 сценариев», §1. */
const SCENARIO_TABLE = [
  ["film", "Киносцена"],
  ["ad", "Реклама товара"],
  ["person", "Персонаж"],
  ["car", "Автомобиль"],
  ["action", "Экшен"],
  ["scifi", "Фантастика"],
  ["fashion", "Fashion"],
  ["music", "Музыкальный клип"],
  ["i2v", "Image → Video"],
  ["anim", "Анимация"],
  ["real", "Реалистичная сцена"],
  ["vertical", "Reels / TikTok"],
];

/** Правило карусели, как на сайте: сервер отдаёт 48 работ, в карусели 12 мест, меньше 5 роликов она не показывает. */
const RULE = { limit: 48, size: 12, min: 5 };

/** Ролик витрины в сценарии `category`; место в списке задаёт порядок массива. */
const clip = (id, category, over = {}) => ({ ...parseItem(row({ id, category, title: `Работа ${id}` })), ...over });

/** Чем картинка витрины отличается от ролика. */
const PICTURE = { kind: "image", video: null, image: "/m/i.png", poster: "/m/i.png", duration: null };

test("parseList: витрина, кандидаты, категории и лимит — из ответа сервера", () => {
  const data = parseList(listBody());
  assert.equal(data.items.length, 1);
  assert.deepEqual(data.items[0], {
    takeUid: "a".repeat(32),
    kind: "video",
    video: "/media/vstudio/a.mp4",
    image: null,
    poster: "/media/vstudio/a.jpg",
    aspect: "16:9",
    duration: 5,
    resolution: "720p",
    modelName: "Seedance 2.0",
    prompt: "Ночной город, неон",
    authorEmail: "staff@esai.kg",
    staff: true,
    startFrame: null,
    id: 12,
    title: "Ночной город",
    category: "film",
    sort: 0,
    visible: true,
    showPrompt: true,
    createdAt: "2026-10-07T11:00:00+06:00",
    addedBy: "owner@esai.kg",
    available: true,
  });
  assert.equal(data.candidates.length, 1);
  assert.equal(data.candidates[0].takeUid, "b".repeat(32));
  assert.equal(data.candidates[0].publishable, true);
  assert.equal(data.candidates[0].finishedAt, "2026-10-07T10:01:30+06:00");
  assert.equal(data.count, 73);
  assert.equal(data.pageSize, 50);
  assert.equal(data.publicLimit, 48);
  assert.deepEqual(data.categories.map((c) => c.label), ["Киносцена", "Музыкальный клип"]);
});

test("parseList: чужое и битое пропускаем, а не падаем", () => {
  assert.equal(parseList("<html>502</html>"), null);
  assert.equal(parseList(null), null);
  assert.equal(parseList([]), null);

  const data = parseList({
    items: [row(), row(), { title: "без id" }, "мусор", row({ id: 13, take: null, sort: "7", is_active: "false" })],
    candidates: { results: [take(), take(), { uid: "" }, 5, take({ uid: "c".repeat(32), public_ok: false })] },
  });
  assert.deepEqual(data.items.map((x) => x.id), [12, 13], "повтор id и запись без id отброшены");
  const bare = data.items[1];
  assert.equal(bare.takeUid, "");
  assert.equal(bare.video, null);
  assert.equal(bare.sort, 0, "sort не числом — как у новой строки");
  assert.equal(bare.visible, true, 'строка "false" — не false');
  assert.deepEqual(data.candidates.map((c) => c.takeUid), ["a".repeat(32), "c".repeat(32)]);
  assert.equal(data.candidates[1].publishable, false);
  assert.equal(data.count, 2, "без count — сколько пришло");
  assert.equal(data.pageSize, 50);
  assert.equal(data.publicLimit, 48);
  assert.deepEqual(
    data.categories.map((c) => [c.key, c.label]),
    [...SCENARIO_TABLE, ["other", "Другое"]],
    "без списка сервера — запасной: двенадцать сценариев и «Другое»",
  );
});

test("сценарии: двенадцать ключей в порядке карусели, как у сервера и первого экрана", () => {
  assert.deepEqual(SCENARIOS.map((c) => [c.key, c.label]), SCENARIO_TABLE);
  // Поле ShowcaseItem.category — восемь символов: длиннее ключ сервер не сохранит.
  for (const { key } of SCENARIOS) assert.ok(/^[a-z0-9]{1,8}$/.test(key), key);
  assert.equal(SCENARIOS.some((c) => c.key === "other"), false, "«Другое» — не сценарий");
});

test("parseItem: картинка, скрытая строка, удалённый результат", () => {
  const image = parseItem(
    row({ take: take({ kind: "image", video_url: null, image_url: "/m/i.png", poster_url: "/m/i.png", duration_s: null, params: {} }) }),
  );
  assert.equal(image.kind, "image");
  assert.equal(image.video, null);
  assert.equal(image.image, "/m/i.png");
  assert.equal(image.duration, null);
  assert.equal(image.resolution, "");

  const hidden = parseItem(row({ is_active: false, show_prompt: false, state: "hidden" }));
  assert.equal(hidden.visible, false);
  assert.equal(hidden.showPrompt, false);
  assert.equal(hidden.available, true);

  assert.equal(parseItem(row({ state: "result_gone" })).available, false);
  assert.equal(parseItem(row({ state: "over_limit" })).available, true);
  assert.equal(parseItem(row({ take: take({ model: { id: "x/y", name: "" } }) })).modelName, "x/y");
  assert.equal(parseItem(null), null);
  assert.equal(parseItem({ id: "12" }), null);
});

test("первый кадр ролика с фото: панель получает его всегда — показать до публикации", () => {
  const frame = "/media/vstudio/7/abc_t.jpg";
  const i2v = { own_photos: true, start_frame_url: frame };
  // Кандидат: работа ещё не в витрине, а кадр уже виден владельцу.
  const data = parseList(listBody({ candidates: { count: 1, page_size: 50, results: [take({ uid: "b".repeat(32), ...i2v })] } }));
  assert.equal(data.candidates[0].startFrame, frame);
  // Работа в витрине: кадр приходит и с выключенным «Показывать запрос» — до включения.
  const off = parseItem(row({ show_prompt: false, take: take(i2v) }));
  assert.deepEqual([off.showPrompt, off.startFrame], [false, frame]);
  assert.equal(parseItem(row({ take: take(i2v) })).startFrame, frame);

  // Ролик без первого кадра, сервер прежней версии, мусор — кадра нет.
  for (const none of [null, undefined, "", "   ", 7, {}, []]) {
    assert.equal(parseItem(row({ take: take({ start_frame_url: none }) })).startFrame, null, JSON.stringify(none));
  }
  assert.equal(parseItem(row({ take: null })).startFrame, null);
  // У картинки первого кадра не бывает — как на сайте.
  const picture = take({ kind: "image", video_url: null, image_url: "/m/i.png", duration_s: null, start_frame_url: frame });
  assert.equal(parseItem(row({ take: picture })).startFrame, null);
});

test("запросы: адреса и тела — теми именами, что ждёт сервер", () => {
  assert.equal(SHOWCASE_PATH, "manage/vstudio/showcase/");
  assert.equal(itemPath(7), "manage/vstudio/showcase/7/");
  assert.equal(listPath({ staffOnly: true, search: "", page: 1 }), "manage/vstudio/showcase/?scope=staff");
  assert.equal(
    listPath({ staffOnly: false, search: "ночной город", page: 3 }),
    "manage/vstudio/showcase/?scope=all&q=%D0%BD%D0%BE%D1%87%D0%BD%D0%BE%D0%B9+%D0%B3%D0%BE%D1%80%D0%BE%D0%B4&page=3",
  );

  const form = { title: "  Ночной город ", category: "film", showPrompt: true };
  assert.deepEqual(addBody("u1", form), { take: "u1", title: "Ночной город", category: "film", show_prompt: true });
  assert.deepEqual(addBody("u1", form, -10).sort, -10);

  assert.deepEqual(patchBody({ visible: false }), { is_active: false });
  assert.deepEqual(patchBody({ showPrompt: true, title: " А ", category: "ad", sort: 30 }), {
    title: "А",
    category: "ad",
    sort: 30,
    show_prompt: true,
  });
  assert.deepEqual(patchBody({}), {});
});

test("previousOf: откатываем только то, что меняли", () => {
  const it = item(1, 20, { title: "Старое", visible: true, showPrompt: false });
  assert.deepEqual(previousOf(it, { title: "Новое" }), { title: "Старое" });
  assert.deepEqual(previousOf(it, { visible: false, showPrompt: true }), { visible: true, showPrompt: false });
  assert.deepEqual(previousOf(it, {}), {});
});

test("errorText: текст сервера, иначе — понятная причина", () => {
  assert.equal(errorText({ status: 400, data: { detail: "Название длиннее 80 символов", field: "title" } }, "x"), "Название длиннее 80 символов");
  assert.equal(
    errorText({ status: 503, data: { error: "Видеостудия не подключена на этом сервере.", error_code: "vstudio_disabled" } }, "x"),
    "Видеостудия не подключена на этом сервере.",
  );
  assert.match(errorText({ status: 0, data: null }, "x"), /Нет связи/);
  assert.match(
    errorText({ status: 429, data: { detail: "Запрос был проигнорирован. Ожидаемая доступность через 31 секунду." } }, "x"),
    /Слишком много запросов/,
    "служебный текст лимита не показываем",
  );
  assert.equal(errorText({ status: 502, data: "<html>" }, "Не удалось сохранить"), "Не удалось сохранить (HTTP 502)");
});

test("planMove: между соседями есть промежуток — одна запись", () => {
  const list = [item(1, 10), item(2, 20), item(3, 30), item(4, 40)];
  const down = planMove(list, 1, 2);
  assert.deepEqual(down.order, [2, 3, 1, 4]);
  assert.deepEqual([...down.sorts], [[1, 35]]);

  const first = planMove(list, 4, 0);
  assert.deepEqual(first.order, [4, 1, 2, 3]);
  assert.deepEqual([...first.sorts], [[4, 0]]);

  const last = planMove(list, 2, 99);
  assert.deepEqual(last.order, [1, 3, 4, 2]);
  assert.deepEqual([...last.sorts], [[2, 50]]);

  assert.deepEqual([...planMove([item(1, 0), item(2, 10)], 2, 0).sorts], [[2, -10]], "выше нуля — в минус: сервер принимает");
});

test("planMove: промежутка нет — нумеруем весь список один раз", () => {
  // Свежая витрина: у всех sort 0, порядок держится на «новые выше».
  const fresh = [item(4, 0), item(3, 0), item(2, 0), item(1, 0)];
  const plan = planMove(fresh, 4, 1);
  assert.deepEqual(plan.order, [3, 4, 2, 1]);
  assert.deepEqual([...plan.sorts], [[3, 10], [4, 20], [2, 30], [1, 40]]);

  // После нумерации следующая перестановка — снова одна запись.
  const next = applyMove(fresh, plan);
  assert.deepEqual(next.map((x) => [x.id, x.sort]), [[3, 10], [4, 20], [2, 30], [1, 40]]);
  assert.equal(planMove(next, 1, 0).sorts.size, 1);

  // Соседи подряд (10 и 11): целого между ними нет.
  const tight = planMove([item(1, 10), item(2, 11), item(3, 30)], 3, 1);
  assert.deepEqual(tight.order, [1, 3, 2]);
  assert.deepEqual([...tight.sorts], [[3, 20], [2, 30]], "пишем только тех, у кого число изменилось");

  // Список на экране не по возрастанию — одной записью его не починить.
  const broken = planMove([item(1, 30), item(2, 10), item(3, 20)], 3, 0);
  assert.equal(broken.sorts.size, 3);
});

test("planMove: нечего двигать", () => {
  const list = [item(1, 10), item(2, 20)];
  assert.equal(planMove(list, 1, 0), null);
  assert.equal(planMove(list, 1, -5), null, "выше первого места некуда");
  assert.equal(planMove(list, 2, 7), null, "ниже последнего некуда");
  assert.equal(planMove(list, 99, 0), null);
  assert.equal(planMove(list, 1, Number.NaN), null);
  assert.equal(planMove([], 1, 0), null);
});

test("planMove: после записи сервер отдаст тот же порядок, что на экране", () => {
  // Детерминированный генератор: случайные витрины с повторами sort.
  let seed = 20261007;
  const rnd = (n) => {
    seed = (seed * 1103515245 + 12345) % 2147483648;
    return seed % n;
  };
  for (let round = 0; round < 400; round++) {
    const size = 2 + rnd(9);
    let list = serverOrder(Array.from({ length: size }, (_, i) => item(i + 1, (rnd(4) - 1) * (round % 2 ? 1 : 10))));
    for (let step = 0; step < 6; step++) {
      const plan = planMove(list, list[rnd(size)].id, rnd(size + 2) - 1);
      if (!plan) continue;
      for (const value of plan.sorts.values()) assert.ok(Number.isInteger(value) && Math.abs(value) <= 100000);
      const onScreen = applyMove(list, plan);
      assert.deepEqual(onScreen.map((x) => x.id), plan.order);
      assert.deepEqual(serverOrder(onScreen).map((x) => x.id), plan.order, `раунд ${round}, шаг ${step}`);
      list = onScreen;
    }
  }
});

test("planMove: у края допустимого sort — нумерация вместо выхода за предел", () => {
  const top = planMove([item(1, -99995), item(2, 0)], 2, 0);
  assert.deepEqual([...top.sorts], [[2, 10], [1, 20]]);
  const bottom = planMove([item(1, 0), item(2, 99995)], 1, 1);
  assert.deepEqual([...bottom.sorts], [[2, 10], [1, 20]]);
});

test("новая работа: встаёт первой, и на экране, и на сервере", () => {
  assert.equal(sortForNew([]), undefined, "пустая витрина — решает сервер");
  assert.equal(sortForNew([item(1, 0), item(2, 10)]), -10);
  assert.equal(sortForNew([item(1, -99995)]), undefined, "выше некуда — решает сервер");

  const list = [item(5, 0), item(3, 0), item(9, 20)];
  assert.deepEqual(insertItem(list, item(10, -10)).map((x) => x.id), [10, 5, 3, 9]);
  assert.deepEqual(insertItem(list, item(10, 0)).map((x) => x.id), [10, 5, 3, 9], "равный sort — новая выше");
  assert.deepEqual(insertItem(list, item(4, 0)).map((x) => x.id), [5, 4, 3, 9]);
  assert.deepEqual(insertItem(list, item(10, 50)).map((x) => x.id), [5, 3, 9, 10]);
  assert.deepEqual(insertItem(list, item(3, 30)).map((x) => x.id), [5, 9, 3], "та же работа не дублируется");
  for (const added of [item(10, -10), item(10, 0), item(4, 0), item(10, 50)]) {
    const next = insertItem(list, added);
    assert.deepEqual(next.map((x) => x.id), serverOrder(next).map((x) => x.id));
  }
});

test("publicOrder: посетители видят первые видимые работы с живым файлом", () => {
  const list = [
    item(1, 10),
    item(2, 20, { visible: false }),
    item(3, 30, { available: false }),
    item(4, 40),
    item(5, 50),
  ];
  assert.deepEqual(publicOrder(list, 48), [1, 4, 5]);
  assert.deepEqual(publicOrder(list, 2), [1, 4], "лишние ждут очереди");
  assert.deepEqual(publicOrder([], 48), []);
});

test("nextPage: страница считается от числа строк на экране", () => {
  assert.equal(nextPage(50, 50), 2);
  assert.equal(nextPage(100, 50), 3);
  // Один дубль ушёл в витрину: его место на первой странице занял следующий —
  // «страница 2» его бы пропустила.
  assert.equal(nextPage(49, 50), 1);
  assert.equal(nextPage(0, 50), 1);
  assert.equal(nextPage(10, 0), 11, "нулевой размер страницы не делит на ноль");
});

test("carousel: пустая витрина — двенадцать пустых сценариев", () => {
  const empty = carousel([], RULE);
  assert.deepEqual(empty.slots.map((slot) => [slot.key, slot.label]), SCENARIO_TABLE);
  assert.ok(empty.slots.every((slot) => slot.item === null && slot.spare === 0));
  assert.deepEqual(
    { filled: empty.filled, videos: empty.videos, order: empty.order, studio: empty.studio },
    { filled: 0, videos: 0, order: [], studio: false },
  );
});

test("carousel: сценарий занимает верхний ролик, остальные идут следом в порядке витрины", () => {
  const list = [
    clip(1, "music"),
    clip(2, "other"),
    clip(3, "film"),
    clip(4, "music"),
    clip(5, "ad"),
    clip(6, "film"),
    clip(7, "music"),
  ];
  const reel = carousel(list, RULE);
  const slot = (key) => reel.slots.find((x) => x.key === key);
  assert.equal(slot("film").item.id, 3);
  assert.equal(slot("film").spare, 1);
  assert.equal(slot("music").item.id, 1, "из роликов одного сценария — верхний в списке");
  assert.equal(slot("music").spare, 2);
  assert.equal(slot("ad").item.id, 5);
  assert.equal(slot("ad").spare, 0);
  assert.equal(slot("person").item, null);
  assert.equal(reel.filled, 3);
  assert.equal(reel.videos, 7, "ролик без сценария тоже ролик");
  // Сначала сценарии в своём порядке (film, ad, music), затем остальное как в списке.
  assert.deepEqual(reel.order, [3, 5, 1, 2, 4, 6, 7]);
  assert.equal(reel.studio, true);
});

test("carousel: в счёт только ролики, которые видит сайт", () => {
  const list = [
    clip(1, "film", PICTURE),
    clip(2, "film", { visible: false }),
    clip(3, "film", { available: false }),
    clip(4, "film"),
    clip(5, "car", PICTURE),
    clip(6, "ad", { visible: false }),
  ];
  const reel = carousel(list, RULE);
  const slot = (key) => reel.slots.find((x) => x.key === key);
  assert.equal(slot("film").item.id, 4, "картинка, скрытая и работа без файла сценарий не занимают");
  assert.equal(slot("film").spare, 0);
  assert.equal(slot("car").item, null);
  assert.equal(slot("ad").item, null);
  assert.deepEqual({ filled: reel.filled, videos: reel.videos, order: reel.order }, { filled: 1, videos: 1, order: [4] });

  // Сервер отдаёт сайту только первые limit работ — картинка занимает в них место наравне с роликом.
  const tight = carousel(list, { ...RULE, limit: 1 });
  assert.equal(tight.videos, 0, "единственная отданная работа — картинка");
  assert.equal(tight.filled, 0);
});

test("carousel: порог — меньше пяти роликов карусель студию не показывает", () => {
  const keys = SCENARIOS.map((c) => c.key);
  const first = (n) => keys.slice(0, n).map((key, i) => clip(i + 1, key));
  assert.equal(carousel(first(3), RULE).studio, false);
  assert.equal(carousel(first(4), RULE).studio, false);
  assert.equal(carousel(first(5), RULE).studio, true);
  assert.equal(carousel(first(4), RULE).filled, 4, "сценарии заняты, хотя карусель ещё ждёт");

  const full = carousel(first(12), RULE);
  assert.equal(full.filled, 12);
  assert.deepEqual(full.order, [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]);
  assert.ok(full.slots.every((slot) => slot.item !== null && slot.spare === 0));

  // Пять роликов одного сценария: карусель есть, а занят один сценарий.
  const same = carousel([1, 2, 3, 4, 5].map((id) => clip(id, "car")), RULE);
  assert.deepEqual(
    { filled: same.filled, studio: same.studio, order: same.order },
    { filled: 1, studio: true, order: [1, 2, 3, 4, 5] },
  );
  assert.equal(same.slots.find((x) => x.key === "car").spare, 4);
});

test("carousel: мест двенадцать — сценарии впереди, лишнее не помещается", () => {
  // Двадцать роликов: сверху восемь «Другое», под ними все двенадцать сценариев в обратном порядке.
  const keys = SCENARIOS.map((c) => c.key);
  const list = [
    ...Array.from({ length: 8 }, (_, i) => clip(i + 1, "other")),
    ...keys.slice().reverse().map((key, i) => clip(i + 9, key)),
  ];
  const reel = carousel(list, RULE);
  assert.equal(reel.videos, 20);
  assert.equal(reel.filled, 12);
  assert.deepEqual(reel.order, [20, 19, 18, 17, 16, 15, 14, 13, 12, 11, 10, 9], "порядок сценариев, а не списка");

  // Заняты десять сценариев — два свободных места достаются верхним из остальных.
  const partial = carousel(list.filter((x) => x.category !== "film" && x.category !== "vertical"), RULE);
  assert.equal(partial.filled, 10);
  assert.deepEqual(partial.order, [19, 18, 17, 16, 15, 14, 13, 12, 11, 10, 1, 2]);
});

test("carousel: ключи до переименования считаются новыми сценариями", () => {
  const reel = carousel([clip(1, "social"), clip(2, "anime"), clip(3, "anim"), clip(4, "неизвестный")], RULE);
  const slot = (key) => reel.slots.find((x) => x.key === key);
  assert.equal(slot("vertical").item.id, 1);
  assert.equal(slot("anim").item.id, 2, "старый ключ стоит выше — он и занимает сценарий");
  assert.equal(slot("anim").spare, 1);
  assert.equal(reel.filled, 2, "незнакомый ключ сценарий не занимает");
  assert.deepEqual(reel.order, [2, 1, 3, 4]);
});

test("carousel: панель собирает карусель так же, как первый экран", async () => {
  // Правило карусели живёт на сайте (home/showreelData.ts), панель его
  // повторяет. Разойдутся — доска покажет не то, что видит посетитель.
  const site = await import("../../../components/vstudio/home/showreelData.ts");
  const { SCENARIOS: siteKeys } = await import("../../../components/vstudio/home/scenarios.ts");
  assert.deepEqual(SCENARIOS.map((c) => c.key), [...siteKeys]);

  // Что сервер отдаёт сайту (showcase.public_json): первые limit работ, которые видит посетитель.
  const sitePayload = (list, limit) => {
    const sent = new Set(publicOrder(list, limit));
    return {
      items: list
        .filter((x) => sent.has(x.id))
        .map((x) => ({
          id: x.id,
          title: x.title,
          category: x.category,
          kind: x.kind,
          model: { id: "bytedance/seedance-2.0", name: x.modelName },
          aspect_ratio: x.aspect,
          duration_s: x.duration,
          video_url: x.video,
          image_url: x.image,
          poster_url: x.poster,
          prompt: null,
          params: null,
        })),
    };
  };
  const scenes = site.cartoonItems({
    presets: Array.from({ length: 8 }, (_, i) => ({
      slug: `scene-${i}`,
      title: `Сцена ${i}`,
      category: "tales",
      preview_video: `/c/${i}.mp4`,
      preview_poster: `/c/${i}.jpg`,
      is_pick: true,
    })),
  });
  assert.equal(scenes.length, 8);

  const pool = [...SCENARIOS.map((c) => c.key), "other", "other", "social", "anime", "чужой"];
  let seed = 20261008;
  const rnd = (n) => {
    seed = (seed * 1103515245 + 12345) % 2147483648;
    return seed % n;
  };
  let studioRounds = 0;
  for (let round = 0; round < 400; round++) {
    const rule = { limit: round % 4 === 0 ? 9 : 48, size: site.REEL_SIZE, min: site.REEL_MIN };
    const list = Array.from({ length: rnd(26) }, (_, i) =>
      clip(i + 1, pool[rnd(pool.length)], {
        ...(rnd(6) === 0 ? PICTURE : {}),
        visible: rnd(7) !== 0,
        available: rnd(9) !== 0,
      }),
    );
    const panel = carousel(list, rule);
    const view = site.buildShowreel(site.studioItems(sitePayload(list, rule.limit)), scenes);
    if (panel.studio) {
      studioRounds++;
      assert.equal(view.source, "vstudio", `раунд ${round}`);
      assert.deepEqual(view.reel.map((x) => x.id), panel.order.map((id) => `vs:${id}`), `раунд ${round}`);
    } else {
      assert.equal(view.source, "cartoon", `раунд ${round}`);
      assert.ok(view.reel.every((x) => x.source === "cartoon"), `раунд ${round}: ролики студии со сценами не смешиваются`);
    }
  }
  assert.ok(studioRounds > 100 && studioRounds < 300, "проверены обе карусели — и студии, и мультстудии");
});

test("placesOf: где работа сейчас на сайте", () => {
  const keys = SCENARIOS.map((c) => c.key);
  const base = [
    clip(101, "film", { visible: false }),
    clip(102, "film", { available: false }),
    clip(103, "film", { visible: false, available: false }),
    clip(104, "ad", PICTURE),
  ];

  // Роликов четыре: карусель показывает мультстудию, готовые ролики ждут.
  const few = [...base, ...keys.slice(0, 4).map((key, i) => clip(i + 1, key))];
  const waiting = placesOf(few, RULE.limit, carousel(few, RULE));
  assert.deepEqual(
    [...waiting],
    [[101, "hidden"], [102, "nofile"], [103, "nofile"], [104, "out"], [1, "wait"], [2, "wait"], [3, "wait"], [4, "wait"]],
  );

  // Роликов четырнадцать: двенадцать в карусели, двум места не хватило.
  const many = [...base, ...keys.map((key, i) => clip(i + 1, key)), clip(13, "film"), clip(14, "other")];
  const places = placesOf(many, RULE.limit, carousel(many, RULE));
  assert.equal(places.get(104), "out", "картинка в карусель не идёт");
  for (let id = 1; id <= 12; id++) assert.equal(places.get(id), "reel");
  assert.equal(places.get(13), "out");
  assert.equal(places.get(14), "out");
  assert.equal(places.size, many.length, "место есть у каждой работы");

  // Сервер отдаёт только первые limit видимых работ — остальные до сайта не доходят.
  const cut = { ...RULE, limit: 6 };
  const over = placesOf(many, cut.limit, carousel(many, cut));
  assert.equal(over.get(104), "out");
  assert.equal(over.get(5), "reel", "пять роликов отдано — карусель есть");
  assert.equal(over.get(6), "over");
  assert.equal(over.get(14), "over");
  assert.equal(over.get(101), "hidden", "скрытая остаётся скрытой, а не «не поместилась»");
});

test("окно «В витрину»: запрос сотрудника показываем сразу", () => {
  assert.deepEqual(addDefaults({ staff: true, prompt: "Ночной город, неон" }), { title: "", category: "", showPrompt: true });
  assert.equal(addDefaults({ staff: true, prompt: "" }).showPrompt, false, "показывать нечего");
  assert.equal(addDefaults({ staff: false, prompt: "Находка пользователя" }).showPrompt, false, "чужой запрос — только явной галочкой");
  assert.equal(addDefaults(parseList(listBody()).candidates[0]).showPrompt, true);
});

test("titleForScenario: пустое название получает имя сценария, набранное не трогаем", () => {
  const options = [...SCENARIOS, { key: "other", label: "Другое" }];
  assert.equal(titleForScenario("", "film", options), "Киносцена");
  assert.equal(titleForScenario("   ", "i2v", options), "Image → Video");
  assert.equal(titleForScenario("Ночной город", "film", options), "Ночной город");
  assert.equal(titleForScenario(" Ночной город ", "ad", options), " Ночной город ", "набранное возвращаем как есть");

  // Имя сценария в поле подставили мы — оно уходит вслед за сценарием.
  assert.equal(titleForScenario("Киносцена", "ad", options), "Реклама товара");
  assert.equal(titleForScenario("Киносцена", "film", options), "Киносцена");
  assert.equal(titleForScenario("Киносцена", "other", options), "", "у «Другого» имени для подписи нет");
  assert.equal(titleForScenario("", "other", options), "");
  assert.equal(titleForScenario("Другое", "film", options), "Другое", "«Другое» мы не подставляем — значит, набрано");
  assert.equal(titleForScenario("", "нет такого", options), "");
  assert.equal(titleForScenario("Своё", "нет такого", options), "Своё");

  // Подписи берём из списка сервера: что в окне на кнопках, то и в поле.
  const server = [
    { key: "film", label: "Кино" },
    { key: "ad", label: "Реклама" },
  ];
  assert.equal(titleForScenario("", "film", server), "Кино");
  assert.equal(titleForScenario("Кино", "ad", server), "Реклама");
  assert.equal(titleForScenario("Киносцена", "ad", server), "Киносцена");
});

test("имена полей сервера знает только showcaseAdmin.ts", () => {
  // Обещание модуля: сменилось имя поля — правится один файл. Сторожим его:
  // компоненты страницы не должны читать ответ сервера сами.
  const dir = new URL("./", import.meta.url);
  const server = /\b(is_active|show_prompt|user_email|user_is_staff|public_ok|poster_url|video_url|image_url|start_frame_url|created_by_email|page_size|public_limit)\b/;
  for (const name of readdirSync(dir)) {
    if (!name.endsWith(".tsx")) continue;
    const source = readFileSync(new URL(name, dir), "utf8");
    assert.equal(server.test(source), false, `${name} читает поле сервера напрямую`);
  }
});
