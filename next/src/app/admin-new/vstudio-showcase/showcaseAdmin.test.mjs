// Админка, витрина видеостудии: разбор ответов сервера, тела запросов и порядок (showcaseAdmin.ts).
// Запуск (Node 22.6+):  node --experimental-strip-types --test src/app/admin-new/vstudio-showcase/showcaseAdmin.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import {
  SHOWCASE_PATH,
  addBody,
  applyMove,
  errorText,
  insertItem,
  itemPath,
  listPath,
  nextPage,
  parseItem,
  parseList,
  patchBody,
  planMove,
  previousOf,
  publicOrder,
  sortForNew,
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
    { key: "film", label: "Кино" },
    { key: "music", label: "Клипы" },
  ],
  public_limit: 48,
  ...over,
});

/** Работа для проверок порядка: нужны только id и sort, остальное — как у настоящей. */
const item = (id, sort, over = {}) => ({ ...parseItem(row({ id, sort })), ...over });

/** Порядок сервера: sort по возрастанию, при равных — новые (больший id) выше. */
const serverOrder = (list) => list.slice().sort((a, b) => a.sort - b.sort || b.id - a.id);

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
  assert.deepEqual(data.categories.map((c) => c.label), ["Кино", "Клипы"]);
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
  assert.equal(data.categories.length, 6, "без категорий — запасной список");
  assert.equal(data.categories.find((c) => c.key === "music").label, "Клипы");
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

test("имена полей сервера знает только showcaseAdmin.ts", () => {
  // Обещание модуля: сменилось имя поля — правится один файл. Сторожим его:
  // компоненты страницы не должны читать ответ сервера сами.
  const dir = new URL("./", import.meta.url);
  const server = /\b(is_active|show_prompt|user_email|user_is_staff|public_ok|poster_url|video_url|image_url|created_by_email|page_size|public_limit)\b/;
  for (const name of readdirSync(dir)) {
    if (!name.endsWith(".tsx")) continue;
    const source = readFileSync(new URL(name, dir), "utf8");
    assert.equal(server.test(source), false, `${name} читает поле сервера напрямую`);
  }
});
