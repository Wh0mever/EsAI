// Админка, витрина видеостудии: разбор ответов сервера, тела запросов, порядок, карусель и её размер (showcaseAdmin.ts).
// Запуск (Node 22.6+):  node --experimental-strip-types --test src/app/admin-new/vstudio-showcase/showcaseAdmin.test.mjs
// showcaseAdmin.ts берёт границы размера карусели у первого экрана — через алиас "@/…", которого Node не знает.
// Поэтому хук идёт первой строкой, а сам модуль подключается динамически, уже после него.
import "../../../lib/vstudio/nodeTsHooks.mjs";
import { test } from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync, readdirSync } from "node:fs";

const {
  SCENARIOS,
  SHOWCASE_PATH,
  addBody,
  addDefaults,
  addReady,
  applyMove,
  carousel,
  errorText,
  insertItem,
  isPlacement,
  itemPath,
  itemsIn,
  listPath,
  nextPage,
  parseItem,
  parseList,
  patchBody,
  placesOf,
  plural,
  planMove,
  previousOf,
  publicOrder,
  reelSizeBody,
  reelSizeError,
  reelSizeExact,
  reelSizeHint,
  reelSizeQuick,
  reelSizeStep,
  reelSizeTyped,
  savedReelSize,
  scenarioless,
  sortForNew,
  titleForScenario,
  trendsAllowed,
  trendsOf,
} = await import("./showcaseAdmin.ts");

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
  placement: "reel",
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
  placements: [
    { key: "reel", label: "Карусель" },
    { key: "trends", label: "Тренды" },
  ],
  public_limit: 48,
  trends_limit: 24,
  reel_size: 24,
  reel_size_min: 5,
  reel_size_max: 48,
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

/** Правило карусели, как на сайте: сервер отдаёт 48 работ, мест 12 (пока владелец не выбрал другое число), меньше 5 роликов она не показывает. */
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
    placement: "reel",
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
  assert.equal(data.trendsLimit, 24);
  assert.deepEqual(data.placements, [
    { key: "reel", label: "Карусель" },
    { key: "trends", label: "Тренды" },
  ]);
  assert.deepEqual(data.reelSize, { value: 24, min: 5, max: 48 });
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
  assert.deepEqual(data.reelSize, { value: 12, min: 5, max: 48 }, "сервер прежней версии размера не присылает");
  assert.deepEqual(
    data.categories.map((c) => [c.key, c.label]),
    [...SCENARIO_TABLE, ["other", "Другое"]],
    "без списка сервера — запасной: двенадцать сценариев и «Другое»",
  );
});

test("размер карусели: число и границы — с сервера, без них — как у сайта", () => {
  const size = (over) => parseList(listBody(over)).reelSize;
  assert.deepEqual(size({}), { value: 24, min: 5, max: 48 });
  assert.equal(size({ reel_size: 5 }).value, 5);
  assert.equal(size({ reel_size: 48 }).value, 48);
  // Не целое от 5 до 48 — настройки как будто нет: так же решит и первый экран.
  for (const bad of [undefined, null, "24", true, 24.5, 4, 49, 0, -12, Number.NaN, {}, [24]]) {
    assert.equal(size({ reel_size: bad }).value, 12, String(bad));
  }
  // Границы сервера уже, чем у сайта, — берём их: больше он всё равно не примет.
  assert.deepEqual(size({ reel_size_min: 8, reel_size_max: 36 }), { value: 24, min: 8, max: 36 });
  assert.deepEqual(size({ reel_size_min: 24, reel_size_max: 24 }), { value: 24, min: 24, max: 24 });
  // Шире — не берём: такой размер сайт не покажет. Перепутанные и не числа — тоже как у сайта.
  assert.deepEqual(size({ reel_size_min: 1, reel_size_max: 96 }), { value: 24, min: 5, max: 48 });
  assert.deepEqual(size({ reel_size_min: 30, reel_size_max: 10 }), { value: 24, min: 5, max: 48 });
  assert.deepEqual(size({ reel_size_min: "5", reel_size_max: null }), { value: 24, min: 5, max: 48 });
  assert.deepEqual(size({ reel_size_min: 5.5, reel_size_max: true }), { value: 24, min: 5, max: 48 });
});

test("размер карусели: тело запроса, ответ сервера и отказ", () => {
  assert.deepEqual(reelSizeBody(24), { reel_size: 24 });
  assert.equal(typeof reelSizeBody(24).reel_size, "number", "строку сервер не примет");

  assert.equal(savedReelSize({ reel_size: 36 }), 36);
  const garbage = [null, "<html>", [], {}, { reel_size: "36" }, { reel_size: true }, { reel_size: 4 }, { reel_size: 49 }, { reel_size: 24.5 }];
  for (const bad of garbage) assert.equal(savedReelSize(bad), null, JSON.stringify(bad));

  // Текст отказа — как его пишет сервер (showcase._clean_reel_size): показываем дословно.
  assert.equal(
    reelSizeError({ status: 400, data: { detail: "Роликов в карусели — целое число от 5 до 48" } }),
    "Роликов в карусели — целое число от 5 до 48",
  );
  assert.equal(reelSizeError({ status: 502, data: "<html>" }), "Не удалось сохранить размер карусели (HTTP 502)");
  assert.match(reelSizeError({ status: 0, data: null }), /Нет связи/);
  // Сервер прежней версии: PATCH на этот адрес он не знает, а его текст владельцу ничего не скажет.
  assert.match(reelSizeError({ status: 405, data: { detail: 'Метод "PATCH" не разрешен.' } }), /Сервер ещё не обновлён/);
});

test("размер карусели: шаг, набранное число и быстрые значения не выходят за границы", () => {
  const size = (value, min = 5, max = 48) => ({ value, min, max });
  assert.equal(reelSizeStep(size(12), 1), 13);
  assert.equal(reelSizeStep(size(12), -1), 11);
  assert.equal(reelSizeStep(size(47), 1), 48);
  assert.equal(reelSizeStep(size(48), 1), null, "больше некуда — кнопка гаснет");
  assert.equal(reelSizeStep(size(5), -1), null, "меньше некуда");
  // Число оказалось вне границ (сервер их сузил) — первый же шаг возвращает его в границы.
  assert.equal(reelSizeStep(size(40, 5, 36), 1), 36);
  assert.equal(reelSizeStep(size(40, 5, 36), -1), 36);

  assert.equal(reelSizeTyped("24", size(12)), 24);
  assert.equal(reelSizeTyped(" 18 ", size(12)), 18);
  assert.equal(reelSizeTyped("100", size(12)), 48, "больше предела — предел");
  assert.equal(reelSizeTyped("3", size(12)), 5);
  assert.equal(reelSizeTyped("0", size(12)), 5);
  assert.equal(reelSizeTyped("12", size(12)), 12);
  for (const not of ["", "  ", "abc", "12.5", "-7", "1e2", "12 шт"]) {
    assert.equal(reelSizeTyped(not, size(12)), null, `«${not}» — не число: человек передумал`);
  }

  assert.deepEqual(reelSizeQuick(size(12)), [12, 18, 24, 36, 48]);
  assert.deepEqual(reelSizeQuick(size(12, 5, 24)), [12, 18, 24]);
  assert.deepEqual(reelSizeQuick(size(20, 20, 40)), [24, 36]);
});

test("размер карусели: уход из поля сохраняет только число, годное как есть, — к границе подгоняет один Enter", () => {
  const size = (value, min = 5, max = 48) => ({ value, min, max });
  // Первая цифра любого из быстрых значений — меньше минимума. Набрали её и кликнули мимо
  // (или сменили окно): Enter записал бы 5, и на сайт ушла бы карусель из пяти роликов.
  for (const half of ["1", "2", "3", "4", "0"]) {
    assert.equal(reelSizeTyped(half, size(12)), 5, `Enter: «${half}» — на ближнюю границу`);
    assert.equal(reelSizeExact(half, size(12)), null, `уход из поля: «${half}» пропадает`);
  }
  assert.equal(reelSizeTyped("100", size(12)), 48);
  assert.equal(reelSizeExact("100", size(12)), null);
  assert.equal(reelSizeExact("49", size(12)), null);
  // Число в границах сохраняется и без Enter: у цифровой клавиатуры телефона его нет.
  assert.equal(reelSizeExact("5", size(12)), 5);
  assert.equal(reelSizeExact("24", size(12)), 24);
  assert.equal(reelSizeExact(" 18 ", size(12)), 18);
  assert.equal(reelSizeExact("048", size(12)), 48);
  assert.equal(reelSizeExact("12", size(12)), 12);
  // Не число — «передумал», как и у Enter; null — в поле ничего не набирали.
  for (const not of ["", "  ", "abc", "12.5", "-7", "1e2", "12 шт", null]) {
    assert.equal(reelSizeExact(not, size(12)), null, String(not));
  }
  // Границы сервера уже — годится только то, что в них.
  assert.equal(reelSizeExact("40", size(12, 5, 36)), null);
  assert.equal(reelSizeExact("36", size(12, 5, 36)), 36);
  // Всё, что уход из поля может сохранить, — ровно набранное число, и Enter сохранил бы его же.
  for (let typed = 0; typed <= 999; typed++) {
    const exact = reelSizeExact(String(typed), size(12));
    assert.equal(exact, typed >= 5 && typed <= 48 ? typed : null, String(typed));
    if (exact !== null) assert.equal(reelSizeTyped(String(typed), size(12)), exact);
  }

  // От этого же числа шагают − и + (ReelSizeControl): набрали 20, нажали «+» — 21, а не 13.
  const from = (draft, saved) => ({ ...size(saved), value: reelSizeExact(draft, size(saved)) ?? saved });
  assert.equal(reelSizeStep(from("20", 12), 1), 21);
  assert.equal(reelSizeStep(from("20", 12), -1), 19);
  assert.equal(reelSizeStep(from("48", 12), 1), null, "в поле уже предел — «+» гаснет");
  // Недобранное в счёт не идёт: шаг от сохранённого.
  assert.equal(reelSizeStep(from("4", 12), 1), 13);
  assert.equal(reelSizeStep(from(null, 12), -1), 11);
});

test("размер карусели: присланное сервером показываем как есть, а просим только то, что он примет", async () => {
  const site = await import("../../../components/vstudio/home/showreelData.ts");
  const bounds = parseList({}).reelSize;
  assert.deepEqual(bounds, { value: site.REEL_SIZE, min: site.REEL_MIN, max: site.REEL_MAX });

  // Сервер отдаёт только целое в границах (чужое в базе он зажимает сам): у сайта,
  // у доски панели и в ответе на сохранение оно остаётся тем же числом.
  for (let n = site.REEL_MIN; n <= site.REEL_MAX; n++) {
    assert.equal(site.clampReelSize(n), n);
    assert.equal(site.reelSizeOf({ items: [], reel_size: n }), n);
    assert.equal(parseList({ reel_size: n }).reelSize.value, n);
    assert.equal(savedReelSize({ reel_size: n }), n);
  }

  // Всё, до чего можно дойти кнопками, полем и быстрыми значениями, — целое в
  // тех же границах: число вне их сервер не зажмёт, а откажет.
  const asked = new Set(reelSizeQuick(bounds));
  for (let value = bounds.min; value <= bounds.max; value++) {
    for (const by of [-1, 1]) {
      const next = reelSizeStep({ ...bounds, value }, by);
      if (next !== null) asked.add(next);
    }
  }
  for (let typed = 0; typed <= 999; typed++) {
    asked.add(reelSizeTyped(String(typed), bounds));
    // Уход из поля просит то же число, что набрано, — или ничего.
    const exact = reelSizeExact(String(typed), bounds);
    if (exact !== null) asked.add(exact);
  }
  for (const value of asked) {
    assert.ok(Number.isInteger(value) && value >= site.REEL_MIN && value <= site.REEL_MAX, String(value));
    assert.deepEqual(reelSizeBody(value), { reel_size: value });
  }
  assert.equal(asked.size, site.REEL_MAX - site.REEL_MIN + 1, "и каждое допустимое число достижимо");
});

// Сервер лежит рядом с фронтендом не всегда (сборка одного next/): тогда сверку пропускаем.
const SERVER_PY = {
  showcase: new URL("../../../../../core/vstudio/showcase.py", import.meta.url),
  panel: new URL("../../../../../core/adminapi/vstudio.py", import.meta.url),
  site: new URL("../../../../../core/vstudio/views.py", import.meta.url),
};

test(
  "размер карусели: границы и имена полей — те же, что в коде сервера",
  { skip: Object.values(SERVER_PY).every((file) => existsSync(file)) ? false : "рядом нет core/ (только фронтенд)" },
  async () => {
    const site = await import("../../../components/vstudio/home/showreelData.ts");
    const py = Object.fromEntries(Object.entries(SERVER_PY).map(([name, file]) => [name, readFileSync(file, "utf8")]));

    // Числа живут в трёх местах: showcase.py, showreelData.ts и (через него) панель.
    const constant = (name) => new RegExp(`^${name} = (\\S+)\\s*$`, "m").exec(py.showcase)?.[1];
    assert.equal(constant("REEL_SIZE_MIN"), String(site.REEL_MIN));
    assert.equal(constant("REEL_SIZE_DEFAULT"), String(site.REEL_SIZE));
    assert.equal(constant("REEL_SIZE_MAX"), "MAX_PUBLIC");
    assert.equal(constant("MAX_PUBLIC"), String(site.REEL_MAX));

    // Имя поля берём из кода сервера и кладём в ответ — фронтенд обязан его прочитать.
    const field = (source, value) => new RegExp(`"(\\w+)":\\s*${value}`).exec(source)?.[1];
    const told = field(py.site, "showcase\\.reel_size\\(\\)");
    assert.equal(told, "reel_size", "ответ сайту: GET vstudio/showcase/");
    assert.equal(site.reelSizeOf({ items: [], [told]: 30 }), 30);

    const staff = {
      value: field(py.panel, "showcase\\.reel_size\\(\\)"),
      min: field(py.panel, "showcase\\.REEL_SIZE_MIN\\b"),
      max: field(py.panel, "showcase\\.REEL_SIZE_MAX\\b"),
    };
    assert.deepEqual(staff, { value: "reel_size", min: "reel_size_min", max: "reel_size_max" }, "ответ панели");
    assert.deepEqual(parseList({ [staff.value]: 30, [staff.min]: 6, [staff.max]: 40 }).reelSize, { value: 30, min: 6, max: 40 });

    // Сохранение: какое поле сервер читает из тела и каким отвечает.
    const read = /size = data\["(\w+)"\]/.exec(py.showcase)?.[1];
    const answered = field(py.panel, "size\\}");
    assert.deepEqual([read, answered], ["reel_size", "reel_size"], "PATCH manage/vstudio/showcase/");
    assert.deepEqual(Object.keys(reelSizeBody(30)), [read]);
    assert.equal(savedReelSize({ [answered]: 30 }), 30);
  },
);

test("подсказка под размером: сколько роликов есть и сходится ли это с числом мест", () => {
  const rule = "Карусель берёт верхний ролик каждого сценария, затем остальные по порядку списка.";
  const hint = (videos, size) => reelSizeHint({ videos, studio: Math.min(videos, size) >= 5 }, { size, min: 5 });

  assert.deepEqual(hint(12, 12), { text: `${rule} Сейчас в витрине 12 включённых роликов.`, note: null });
  assert.deepEqual(hint(12, 24), {
    text: `${rule} Сейчас в витрине 12 включённых роликов.`,
    note: "Роликов меньше, чем мест: карусель покажет 12.",
  });
  assert.equal(hint(30, 24).note, "Не вошло роликов: 6 — в списке они помечены «Вне карусели».");
  assert.equal(hint(48, 48).note, null);
  // Меньше пяти роликов карусель не показывает вовсе — «покажет 3» было бы неправдой.
  assert.equal(hint(3, 12).note, "Роликов меньше 5: карусель пока показывает сцены мультстудии.");
  assert.equal(hint(0, 12).note, "Роликов меньше 5: карусель пока показывает сцены мультстудии.");

  // Число роликов любое — слова согласуются с ним.
  const have = (videos) => hint(videos, 48).text.slice(rule.length + 1);
  assert.equal(have(0), "Сейчас в витрине 0 включённых роликов.");
  assert.equal(have(1), "Сейчас в витрине 1 включённый ролик.");
  for (const n of [2, 3, 4, 22, 23, 24, 32, 44]) assert.equal(have(n), `Сейчас в витрине ${n} включённых ролика.`);
  for (const n of [5, 9, 10, 11, 12, 13, 14, 19, 20, 25, 30, 40, 48]) {
    assert.equal(have(n), `Сейчас в витрине ${n} включённых роликов.`);
  }
  for (const n of [21, 31, 41]) assert.equal(have(n), `Сейчас в витрине ${n} включённый ролик.`);
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

  const form = { title: "  Ночной город ", category: "film", placement: "reel", showPrompt: true };
  assert.deepEqual(addBody("u1", form), {
    take: "u1",
    title: "Ночной город",
    category: "film",
    placement: "reel",
    show_prompt: true,
  });
  assert.deepEqual(addBody("u1", form, -10).sort, -10);
  // «Тренды» без сценария — «Другое»: пустой сценарий сервер не примет.
  assert.deepEqual(addBody("u1", { ...form, category: "", placement: "trends" }), {
    take: "u1",
    title: "Ночной город",
    category: "other",
    placement: "trends",
    show_prompt: true,
  });
  assert.equal(addBody("u1", { ...form, placement: "trends" }).category, "film", "выбранный сценарий не теряем");
  assert.deepEqual(patchBody({ placement: "trends", sort: -10 }), { placement: "trends", sort: -10 });

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
  assert.deepEqual(previousOf(it, { placement: "trends", sort: -10 }), { placement: "reel", sort: 20 });
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

test("carousel: размер меняет только то, где очередь обрезана", () => {
  // Тридцать роликов: двенадцать сценариев в обратном порядке, шесть «Другое», затем ещё по одному на сценарий.
  const keys = SCENARIOS.map((c) => c.key);
  const list = [
    ...keys.slice().reverse().map((key, i) => clip(i + 1, key)),
    ...Array.from({ length: 6 }, (_, i) => clip(i + 13, "other")),
    ...keys.map((key, i) => clip(i + 19, key)),
  ];
  const heads = [12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1];
  const rest = Array.from({ length: 18 }, (_, i) => i + 13);
  const at = (size) => carousel(list, { ...RULE, size });

  for (const size of [5, 11, 12, 13, 18, 24, 30, 36, 48]) {
    const reel = at(size);
    assert.deepEqual(reel.queue, [...heads, ...rest], `размер ${size}: очередь от него не зависит`);
    assert.deepEqual(reel.order, reel.queue.slice(0, size), `размер ${size}`);
    assert.deepEqual({ filled: reel.filled, videos: reel.videos, studio: reel.studio }, { filled: 12, videos: 30, studio: true });
    assert.deepEqual(reel.tail.map((x) => x.id), reel.order.slice(12), `размер ${size}: после сценариев — как в списке`);
    assert.ok(reel.slots.every((slot) => slot.spare === 1));
  }
  assert.deepEqual(at(18).tail.map((x) => x.id), [13, 14, 15, 16, 17, 18]);
  assert.equal(at(48).order.length, 30, "мест больше, чем роликов, — идут все");
  assert.equal(at(48).tail.length, 18);

  // Карусель короче, чем занятых сценариев: последние сняты, но посетитель их не увидит.
  const short = at(5);
  assert.deepEqual(short.order, [12, 11, 10, 9, 8]);
  assert.deepEqual(short.slots.map((slot) => slot.fits), [true, true, true, true, true, false, false, false, false, false, false, false]);
  assert.deepEqual(short.tail, []);
  assert.ok(at(12).slots.every((slot) => slot.fits));
  assert.equal(carousel([], RULE).slots.some((slot) => slot.fits), false, "пустой сценарий никуда не «вошёл»");

  // Метки строк: кто в карусели, а кто в очереди дальше выбранного размера.
  const places = placesOf(list, RULE.limit, at(24));
  for (const id of at(24).queue.slice(0, 24)) assert.equal(places.get(id), "reel", `работа ${id}`);
  for (const id of [25, 26, 27, 28, 29, 30]) assert.equal(places.get(id), "out", `работа ${id}`);
  assert.ok([...placesOf(list, RULE.limit, at(48)).values()].every((place) => place === "reel"));
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

test("carousel: панель собирает карусель так же, как первый экран, — при любом её размере", async () => {
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

  // Размер и его границы панель берёт у сайта: без настройки сервера — те же числа.
  assert.deepEqual([site.REEL_SIZE, site.REEL_MIN, site.REEL_MAX], [12, 5, 48]);
  assert.deepEqual(parseList({}).reelSize, { value: site.REEL_SIZE, min: site.REEL_MIN, max: site.REEL_MAX });
  for (const told of [undefined, null, 5, 12, 30, 48, 4, 49, "24", 24.5, true]) {
    assert.equal(parseList({ reel_size: told }).reelSize.value, site.clampReelSize(told), String(told));
  }

  const pool = [...SCENARIOS.map((c) => c.key), "other", "other", "social", "anime", "чужой"];
  let seed = 20261008;
  const rnd = (n) => {
    seed = (seed * 1103515245 + 12345) % 2147483648;
    return seed % n;
  };
  const sizes = site.REEL_MAX - site.REEL_MIN + 1;
  const seen = { studio: 0, cut: 0, spare: 0, sizes: new Set() };
  for (let round = 0; round < 600; round++) {
    // Каждый третий раунд — размер по умолчанию, остальные перебирают все допустимые по кругу.
    const size = round % 3 === 0 ? site.REEL_SIZE : site.REEL_MIN + (round % sizes);
    const rule = { limit: round % 4 === 0 ? 9 : 48, size, min: site.REEL_MIN };
    // Витрины и короткие, и длиннее самой большой карусели: в ней должно бывать и тесно, и пусто.
    const list = Array.from({ length: rnd(round % 2 ? 70 : 20) }, (_, i) =>
      clip(i + 1, pool[rnd(pool.length)], {
        ...(rnd(6) === 0 ? PICTURE : {}),
        visible: rnd(7) !== 0,
        available: rnd(9) !== 0,
      }),
    );
    const panel = carousel(list, rule);
    const studio = site.studioItems(sitePayload(list, rule.limit));
    const view = site.buildShowreel(studio, scenes, size);
    if (size === site.REEL_SIZE) assert.deepEqual(view, site.buildShowreel(studio, scenes), `раунд ${round}: без размера — двенадцать`);
    if (panel.studio) {
      seen.studio++;
      seen.sizes.add(size);
      if (panel.videos > size) seen.cut++;
      if (panel.videos < size) seen.spare++;
      assert.equal(view.source, "vstudio", `раунд ${round}`);
      assert.deepEqual(view.reel.map((x) => x.id), panel.order.map((id) => `vs:${id}`), `раунд ${round}, размер ${size}`);
    } else {
      assert.equal(view.source, "cartoon", `раунд ${round}`);
      assert.ok(view.reel.every((x) => x.source === "cartoon"), `раунд ${round}: ролики студии со сценами не смешиваются`);
    }
  }
  assert.ok(seen.studio > 150 && seen.studio < 550, "проверены обе карусели — и студии, и мультстудии");
  assert.ok(seen.cut > 50 && seen.spare > 50, "и когда роликов больше, чем мест, и когда меньше");
  assert.equal(seen.sizes.size, sizes, "и при каждом допустимом размере");

  // Те же размеры, что владелец выбирает на деле, — на одной витрине и с ответом
  // в числах: случайные раунды говорят «совпало», но не говорят, с чем.
  // Шестьдесят работ: восемь «Другое» сверху, под ними двенадцать сценариев в
  // обратном порядке и ещё по ролику на сценарий, картинка, скрытая, без файла,
  // дальше вперемешку. Сайту уходят первые 48 видимых — одно место в них у картинки.
  const keys = SCENARIOS.map((c) => c.key);
  const mixed = ["other", "social", "anime", "чужой", "film"];
  const showcase = [
    ...Array.from({ length: 8 }, (_, i) => clip(i + 1, "other")),
    ...keys.slice().reverse().map((key, i) => clip(i + 9, key)),
    ...keys.map((key, i) => clip(i + 21, key)),
    clip(33, "ad", PICTURE),
    clip(34, "car", { visible: false }),
    clip(35, "music", { available: false }),
    ...Array.from({ length: 25 }, (_, i) => clip(i + 36, mixed[i % mixed.length])),
  ];
  const span = (from, to) => Array.from({ length: to - from + 1 }, (_, i) => from + i);
  const heads = span(9, 20).reverse();
  const queue = [...heads, ...span(1, 8), ...span(21, 32), ...span(36, 50)];
  assert.equal(queue.length, 47, "мест 48, роликов сайту ушло 47");
  const sent = sitePayload(showcase, 48);
  assert.equal(sent.items.length, 48);
  const idsAt = (places, place) => showcase.filter((x) => places.get(x.id) === place).map((x) => x.id);
  const byId = (a, b) => a - b;

  for (const size of [5, 12, 13, 24, 48]) {
    // Число приходит обеим сторонам одним полем: сайту — в ответе витрины, панели — в её списке.
    const onSite = site.reelSizeOf({ ...sent, reel_size: size });
    const onPanel = parseList({ reel_size: size, public_limit: 48 });
    assert.deepEqual([onSite, onPanel.reelSize.value], [size, size]);

    const panel = carousel(showcase, { limit: onPanel.publicLimit, size: onPanel.reelSize.value, min: site.REEL_MIN });
    const view = site.buildShowreel(site.studioItems(sent), scenes, onSite);
    assert.deepEqual(panel.queue, queue, `размер ${size}: очередь от него не зависит`);
    assert.deepEqual(panel.order, queue.slice(0, size), `размер ${size}`);
    assert.equal(view.source, "vstudio", `размер ${size}`);
    assert.deepEqual(view.reel.map((x) => x.id), panel.order.map((id) => `vs:${id}`), `размер ${size}: сайт и панель`);

    // Метки строк говорят то же: в карусели — кто вошёл, «вне» — остаток очереди.
    const places = placesOf(showcase, onPanel.publicLimit, panel);
    assert.deepEqual(idsAt(places, "reel").sort(byId), queue.slice(0, size).sort(byId), `размер ${size}: метки`);
    assert.deepEqual(idsAt(places, "out").sort(byId), queue.slice(size).sort(byId), `размер ${size}: вне карусели`);
    assert.deepEqual(idsAt(places, "over"), span(51, 60), `размер ${size}: сайту не ушли`);
    assert.deepEqual([places.get(33), places.get(34), places.get(35)], ["image", "hidden", "nofile"]);
  }
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
    [[101, "hidden"], [102, "nofile"], [103, "nofile"], [104, "image"], [1, "wait"], [2, "wait"], [3, "wait"], [4, "wait"]],
  );

  // Роликов четырнадцать: двенадцать в карусели, двум места не хватило.
  const many = [...base, ...keys.map((key, i) => clip(i + 1, key)), clip(13, "film"), clip(14, "other")];
  const places = placesOf(many, RULE.limit, carousel(many, RULE));
  assert.equal(places.get(104), "image", "картинка в карусель не идёт — при любом её размере");
  for (let id = 1; id <= 12; id++) assert.equal(places.get(id), "reel");
  assert.equal(places.get(13), "out");
  assert.equal(places.get(14), "out");
  assert.equal(places.size, many.length, "место есть у каждой работы");

  // Мест стало четырнадцать — вошли оба, картинка по-прежнему нет.
  const wider = placesOf(many, RULE.limit, carousel(many, { ...RULE, size: 14 }));
  assert.deepEqual([wider.get(13), wider.get(14), wider.get(104)], ["reel", "reel", "image"]);

  // Сервер отдаёт только первые limit видимых работ — остальные до сайта не доходят.
  const cut = { ...RULE, limit: 6 };
  const over = placesOf(many, cut.limit, carousel(many, cut));
  assert.equal(over.get(104), "image");
  assert.equal(over.get(5), "reel", "пять роликов отдано — карусель есть");
  assert.equal(over.get(6), "over");
  assert.equal(over.get(14), "over");
  assert.equal(over.get(101), "hidden", "скрытая остаётся скрытой, а не «не поместилась»");
});

test("окно «В витрину»: запрос сотрудника показываем сразу", () => {
  assert.deepEqual(addDefaults({ staff: true, prompt: "Ночной город, неон" }), {
    title: "",
    category: "",
    placement: "reel",
    showPrompt: true,
  });
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

test("plural: число и слово согласованы — подсказка «Не поместилась» у «Трендов»", () => {
  const forms = ["видимый ролик", "видимых ролика", "видимых роликов"];
  assert.deepEqual(
    [1, 3, 11, 12, 21, 22, 24, 25, 111, 124].map((n) => plural(n, ...forms)),
    [
      "1 видимый ролик",
      "3 видимых ролика",
      "11 видимых роликов",
      "12 видимых роликов",
      "21 видимый ролик",
      "22 видимых ролика",
      "24 видимых ролика",
      "25 видимых роликов",
      "111 видимых роликов",
      "124 видимых ролика",
    ],
  );
  // Потолок «Трендов» — 24: строка должна склонять его, а не писать «24 видимых роликов».
  const row = readFileSync(new URL("./ItemRow.tsx", import.meta.url), "utf8");
  assert.match(row, /первые \$\{plural\(size, "видимый ролик", "видимых ролика", "видимых роликов"\)\}/);
});

test("имена полей сервера знает только showcaseAdmin.ts", () => {
  // Обещание модуля: сменилось имя поля — правится один файл. Сторожим его:
  // компоненты страницы не должны читать ответ сервера сами.
  const dir = new URL("./", import.meta.url);
  const server =
    /\b(is_active|show_prompt|user_email|user_is_staff|public_ok|poster_url|video_url|image_url|start_frame_url|created_by_email|page_size|public_limit|trends_limit|reel_size|reel_size_min|reel_size_max)\b/;
  for (const name of readdirSync(dir)) {
    if (!name.endsWith(".tsx")) continue;
    const source = readFileSync(new URL(name, dir), "utf8");
    assert.equal(server.test(source), false, `${name} читает поле сервера напрямую`);
  }
});

/* ---------- «Тренды»: место работы ---------- */

/** Работа «Трендов»: тот же ролик витрины, другое место. */
const trendClip = (id, over = {}) => clip(id, "other", { placement: "trends", ...over });

test("место работы: с сервера — reel или trends, остальное — карусель, как у сервера прежней версии", () => {
  assert.equal(parseItem(row()).placement, "reel");
  assert.equal(parseItem(row({ placement: "trends" })).placement, "trends");
  for (const junk of [undefined, null, "", "Trends", "gallery", 1, true, {}]) {
    assert.equal(parseItem(row({ placement: junk })).placement, "reel", String(junk));
  }
  assert.deepEqual(["reel", "trends", "Reel", "", null].map(isPlacement), [true, true, false, false, false]);

  // Списка мест и потолка «Трендов» нет (сервер прежней версии) или они битые — свои.
  const bare = parseList({});
  assert.deepEqual(bare.placements, [
    { key: "reel", label: "Карусель" },
    { key: "trends", label: "Тренды" },
  ]);
  assert.equal(bare.trendsLimit, 24);
  for (const placements of [[], [{ key: "reel", label: "К" }], [{ key: "gallery", label: "Г" }, { key: "reel" }], "x"]) {
    assert.deepEqual(parseList({ placements }).placements.map((p) => p.key), ["reel", "trends"], JSON.stringify(placements));
  }
  for (const bad of [0, -3, "24", null, Number.NaN]) assert.equal(parseList({ trends_limit: bad }).trendsLimit, 24, String(bad));
  assert.equal(parseList({ trends_limit: 12 }).trendsLimit, 12);
  // Подписи — сервера; без подписи — ключ.
  const told = parseList({
    placements: [
      { key: "trends", label: "В тренде" },
      { key: "reel", label: "" },
    ],
  }).placements;
  assert.deepEqual(told, [
    { key: "trends", label: "В тренде" },
    { key: "reel", label: "reel" },
  ]);
});

test("окно «В витрину»: «Тренды» без сценария можно, карусель без сценария — нет; картинку в «Тренды» не ставим", () => {
  assert.equal(addReady({ title: "Кот", category: "", placement: "reel" }), false);
  assert.equal(addReady({ title: "Кот", category: "film", placement: "reel" }), true);
  assert.equal(addReady({ title: "Кот", category: "", placement: "trends" }), true);
  assert.equal(addReady({ title: "  ", category: "film", placement: "trends" }), false, "название нужно везде");
  assert.equal(trendsAllowed({ kind: "video" }), true);
  assert.equal(trendsAllowed({ kind: "image" }), false);
});

test("без сценария: «Другое» и незнакомый ключ; старые ключи сервера — сценарии", () => {
  for (const key of SCENARIOS.map((c) => c.key)) assert.equal(scenarioless({ category: key }), false, key);
  assert.equal(scenarioless({ category: "social" }), false);
  assert.equal(scenarioless({ category: "anime" }), false);
  for (const key of ["other", "", "чужой"]) assert.equal(scenarioless({ category: key }), true, key);
});

test("карусель «Трендов» не видит: ни места, ни сценария, ни порога они не занимают", () => {
  const keys = SCENARIOS.map((c) => c.key);
  const reelOnly = keys.slice(0, 4).map((key, i) => clip(i + 1, key));
  // Четыре ролика карусели и пять «Трендов» сверху: роликов студии в карусели по-прежнему четыре.
  const list = [...[11, 12, 13, 14, 15].map((id) => trendClip(id, { category: "film" })), ...reelOnly];
  const reel = carousel(list, RULE);
  assert.deepEqual(reel, carousel(reelOnly, RULE));
  assert.equal(reel.studio, false, "порог карусели «Тренды» не добирают");
  assert.equal(reel.slots[0].item.id, 1, "сценарий занимает ролик карусели, а не тренд того же сценария");

  // Потолок сервера у карусели свой: «Тренды» сверху его не съедают.
  const tight = [...Array.from({ length: 6 }, (_, i) => trendClip(i + 21)), ...keys.slice(0, 6).map((key, i) => clip(i + 1, key))];
  assert.deepEqual(carousel(tight, { ...RULE, limit: 6 }).order, [1, 2, 3, 4, 5, 6]);

  // Метки карусели — только у её работ.
  const places = placesOf(tight, 6, carousel(tight, { ...RULE, limit: 6 }));
  assert.deepEqual([...places.keys()].sort((a, b) => a - b), [1, 2, 3, 4, 5, 6]);
  assert.ok([...places.values()].every((place) => place === "reel"));
});

test("trendsOf: «Тренды» на сайте — первые видимые ролики своего места, по порядку списка", () => {
  const list = [
    clip(1, "film"),
    trendClip(2),
    trendClip(3, { visible: false }),
    clip(4, "ad"),
    trendClip(5, { available: false }),
    trendClip(6, PICTURE),
    trendClip(7),
    trendClip(8),
  ];
  const view = trendsOf(list, 4);
  // Сервер отдаёт четыре: 2, 6, 7, 8 (скрытая и без файла не в счёт); картинку сайт не показывает.
  assert.deepEqual(view.order, [2, 7, 8]);
  assert.deepEqual(
    [...view.places],
    [[2, "trend"], [3, "hidden"], [5, "nofile"], [6, "image"], [7, "trend"], [8, "trend"]],
  );
  assert.deepEqual(trendsOf(list, 2).order, [2], "потолок режет и картинку, и ролики за ней");
  assert.equal(trendsOf(list, 2).places.get(7), "over");
  assert.deepEqual(trendsOf([], 24), { order: [], places: new Map() });
  assert.deepEqual(trendsOf([clip(1, "film")], 24).order, [], "работы карусели — не «Тренды»");

  // Сервер отдал бы больше, чем берёт сайт (его TRENDS_MAX), — лишние для посетителя не видны.
  const thirty = Array.from({ length: 30 }, (_, i) => trendClip(i + 1));
  const wide = trendsOf(thirty, 30);
  assert.equal(wide.order.length, 24);
  assert.deepEqual([wide.places.get(24), wide.places.get(25)], ["trend", "over"]);
});

test("порядок по местам: план считают по одному месту, работы другого не двигаются", () => {
  // Вперемешку, как их отдаёт сервер: общий sort, у каждого места — свой порядок.
  const all = [item(1, 10), item(2, 20, { placement: "trends" }), item(3, 30), item(4, 40, { placement: "trends" }), item(5, 50)];
  assert.deepEqual(itemsIn(all, "reel").map((x) => x.id), [1, 3, 5]);
  assert.deepEqual(itemsIn(all, "trends").map((x) => x.id), [2, 4]);

  const plan = planMove(itemsIn(all, "trends"), 4, 0);
  assert.deepEqual(plan.order, [4, 2]);
  assert.deepEqual([...plan.sorts], [[4, 10]], "сосед — тренд 2 (sort 20), а не работа карусели между ними");
  const next = applyMove(all, plan);
  assert.deepEqual(next.map((x) => x.id), [1, 4, 3, 2, 5], "работы карусели на своих местах");
  assert.deepEqual(itemsIn(next, "trends").map((x) => [x.id, x.sort]), [[4, 10], [2, 20]]);
  assert.deepEqual(itemsIn(next, "reel"), itemsIn(all, "reel"));
  // На сервере то же: в каждом месте — порядок экрана.
  for (const placement of ["reel", "trends"]) {
    const own = itemsIn(next, placement);
    assert.deepEqual(serverOrder(own).map((x) => x.id), own.map((x) => x.id), placement);
  }

  // Новая работа и перенесённая встают первыми в своём месте — по его соседям.
  assert.equal(sortForNew(itemsIn(next, "trends")), 0);
  assert.equal(sortForNew(itemsIn(next, "reel")), 0);
  const moved = { ...item(5, 50), placement: "trends", sort: sortForNew(itemsIn(next, "trends")) };
  const after = insertItem(next, moved);
  assert.deepEqual(itemsIn(after, "trends").map((x) => x.id), [5, 4, 2]);
  assert.deepEqual(itemsIn(after, "reel").map((x) => x.id), [1, 3]);
});

test("«Тренды»: панель видит их так же, как первый экран", async () => {
  const site = await import("../../../components/vstudio/home/showreelData.ts");
  // Что сервер отдаёт сайту (showcase.public_showcase): по списку на место, у каждого свой потолок.
  const card = (x) => ({
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
  });
  const payload = (list, limits) => {
    const sent = (placement, limit) => {
      const own = itemsIn(list, placement);
      const ids = new Set(publicOrder(own, limit));
      return own.filter((x) => ids.has(x.id)).map(card);
    };
    return { items: sent("reel", limits.reel), trends: sent("trends", limits.trends), reel_size: 12 };
  };
  const scenes = site.cartoonItems({
    presets: Array.from({ length: 6 }, (_, i) => ({ slug: `s-${i}`, preview_poster: `/c/${i}.jpg`, is_pick: true })),
  });

  const keys = SCENARIOS.map((c) => c.key);
  let seed = 20261014;
  const rnd = (n) => {
    seed = (seed * 1103515245 + 12345) % 2147483648;
    return seed % n;
  };
  let withTrends = 0;
  for (let round = 0; round < 300; round++) {
    const limits = { reel: round % 3 === 0 ? 7 : 48, trends: round % 4 === 0 ? 5 : 24 };
    const list = Array.from({ length: rnd(60) }, (_, i) =>
      clip(i + 1, keys[rnd(keys.length)], {
        ...(rnd(5) === 0 ? PICTURE : {}),
        placement: rnd(3) === 0 ? "trends" : "reel",
        visible: rnd(7) !== 0,
        available: rnd(9) !== 0,
      }),
    );
    const body = payload(list, limits);
    const trends = trendsOf(list, limits.trends);
    assert.deepEqual(
      site.trendItems(body).map((x) => x.id),
      trends.order.map((id) => `vs:${id}`),
      `раунд ${round}: «Тренды»`,
    );
    if (trends.order.length) withTrends++;
    // Карусель на сайте собирается без «Трендов» — так же, как у панели.
    const reel = carousel(list, { limit: limits.reel, size: 12, min: site.REEL_MIN });
    const view = site.buildShowreel(site.studioItems(body), scenes, site.reelSizeOf(body));
    if (reel.studio) assert.deepEqual(view.reel.map((x) => x.id), reel.order.map((id) => `vs:${id}`), `раунд ${round}`);
    else assert.equal(view.source, "cartoon", `раунд ${round}`);
    // Ни одна работа не стоит в обоих местах.
    const inReel = new Set(view.reel.map((x) => x.id));
    assert.ok(site.trendItems(body).every((x) => !inReel.has(x.id)), `раунд ${round}: тренд в карусели`);
  }
  assert.ok(withTrends > 200, "проверены витрины с «Трендами»");
});
