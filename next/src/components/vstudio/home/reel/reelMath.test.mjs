// Карусель первого экрана: позы кадров, счёт позиции, перетаскивание, ширина кадра, «туман» светлой сцены,
// имена кадров и ряд названий (home/reel/reelMath.ts).
// Запуск (Node 22.6+):  node --experimental-strip-types --test src/components/vstudio/home/reel/*.test.mjs
import "../../../../lib/vstudio/nodeTsHooks.mjs";
import { test } from "node:test";
import assert from "node:assert/strict";

const M = await import("./reelMath.ts");

const ids = (n) => Array.from({ length: n }, (_, i) => `ct:${i}`);
const track = (n, pos = 0) => ({ ids: ids(n), pos });
const near = (a, b, eps = 1e-9) => Math.abs(a - b) <= eps;

/* ---------- позы ---------- */

test("целые места — таблица из макета: сдвиг, поворот, размер, затемнение", () => {
  assert.deepEqual(M.poseAt(0), { x: 0, rot: 0, scale: 1, dim: 0, opacity: 1 });
  assert.deepEqual(M.poseAt(1), { x: 62, rot: 34, scale: 0.78, dim: 0.45, opacity: 1 });
  assert.deepEqual(M.poseAt(-1), M.poseAt(1));
  assert.deepEqual(M.poseAt(2), { x: 104, rot: 40, scale: 0.62, dim: 0.65, opacity: 0.7 });
  // Стоянка невидима, и дальше неё поза не меняется.
  assert.equal(M.poseAt(3).opacity, 0);
  assert.deepEqual(M.poseAt(7), M.poseAt(3));
});

test("стиль места: активный без поворота, соседи повёрнуты к центру вокруг ближнего края", () => {
  assert.deepEqual(M.slotLook(0), {
    transform: "translateX(0%) translateX(0%) rotateY(0deg) scale(1) translateX(0%)",
    opacity: 1,
    zIndex: 10,
    dim: 0,
  });
  // Правый сосед: ось — его левый край (сдвиг −50% … +50%), поворот влево.
  assert.equal(M.slotLook(1).transform, "translateX(62%) translateX(-50%) rotateY(-34deg) scale(0.78) translateX(50%)");
  assert.equal(M.slotLook(-1).transform, "translateX(-62%) translateX(50%) rotateY(34deg) scale(0.78) translateX(-50%)");
  assert.equal(M.slotLook(-2).transform, "translateX(-104%) translateX(50%) rotateY(40deg) scale(0.62) translateX(-50%)");
  assert.deepEqual([0, 1, -1, 2, -2, 3].map((d) => M.slotLook(d).zIndex), [10, 9, 9, 8, 8, 7]);
  assert.deepEqual([1, 2].map((d) => M.slotLook(d).dim), [0.45, 0.65]);
  assert.equal(M.slotLook(2).opacity, 0.7);
});

test("состав цепочки transform одинаков для любого места — браузер ведёт кадр без скачка", () => {
  const shape = (d) => M.slotLook(d).transform.replace(/-?\d+(\.\d+)?/g, "N");
  const all = [-3.4, -3, -2, -1.5, -1, -0.25, 0, 0.5, 1, 2, 2.7, 3].map(shape);
  assert.equal(new Set(all).size, 1);
});

test("между местами поза меняется плавно: за пальцем кадр идёт без рывков", () => {
  let prev = M.poseAt(-3);
  for (let d = -3 + 0.05; d <= 3.0001; d += 0.05) {
    const cur = M.poseAt(d);
    assert.ok(Math.abs(cur.x - prev.x) <= 62 * 0.05 + 1e-6, `x @ ${d}`);
    assert.ok(Math.abs(cur.scale - prev.scale) <= 0.22 * 0.05 + 1e-6, `scale @ ${d}`);
    assert.ok(Math.abs(cur.opacity - prev.opacity) <= 0.7 * 0.05 + 1e-6, `opacity @ ${d}`);
    prev = cur;
  }
  assert.ok(near(M.poseAt(0.5).x, 31) && near(M.poseAt(0.5).scale, 0.89));
});

test("светлая сцена: дальний кадр бледнее, активный и соседи — как в тёмной", () => {
  // Видимые целиком кадры и невидимая стоянка в обеих темах одинаковы.
  assert.equal(M.paperOpacity(M.slotLook(0).opacity), 1);
  assert.equal(M.paperOpacity(M.slotLook(1).opacity), 1);
  assert.equal(M.paperOpacity(M.slotLook(3).opacity), 0);
  // Дальний кадр (в тёмной теме 0.7) на «бумаге» вдвое бледнее; серой плитой ему не дают встать ещё и «туман».
  const far = M.paperOpacity(M.slotLook(2).opacity);
  assert.ok(far > 0.25 && far < 0.45, String(far));
  // Между местами — без скачков и без возврата: кадр, уходящий к краю, только бледнеет.
  let prev = 1;
  for (let d = 1; d <= 3.0001; d += 0.05) {
    const cur = M.paperOpacity(M.slotLook(d).opacity);
    assert.ok(cur <= prev + 1e-9 && prev - cur < 0.1, `opacity @ ${d}`);
    assert.ok(cur <= M.slotLook(d).opacity + 1e-9, `не плотнее тёмной темы @ ${d}`);
    prev = cur;
  }
  assert.equal(M.paperOpacity(1.4), 1);
  assert.equal(M.paperOpacity(-0.2), 0);
});

test("«туман» светлой сцены: активный и соседи чистые, дальний кадр и стоянка — в нём целиком", () => {
  assert.deepEqual([0, 1, -1, 0.4, -0.99].map(M.paperFog), [0, 0, 0, 0, 0]);
  assert.deepEqual([2, -2, 3, -5].map(M.paperFog), [1, 1, 1, 1]);
  assert.equal(M.paperFog(1.5), 0.5);
  assert.equal(M.paperFog(-1.25), 0.25);
  // За пальцем — без скачков и только гуще к краю.
  let prev = 0;
  for (let d = 0; d <= 3.0001; d += 0.05) {
    const cur = M.paperFog(d);
    assert.ok(cur >= prev - 1e-9 && cur - prev <= 0.05 + 1e-9, `fog @ ${d}`);
    prev = cur;
  }
});

// Где на экране окажется точка дальнего кадра (|d| = 2) на доле f его ширины от ближнего края.
const farPoint = (w, f) => {
  const turn = (40 * Math.PI) / 180;
  const flat = (1.04 - 0.5 + 0.62 * Math.cos(turn) * f) * w;
  const depth = 0.62 * Math.sin(turn) * f * w;
  return (flat * 1500) / (1500 - depth);
};

test("«туман» дальнего кадра: начинается у края соседа и кончается раньше края колонки", () => {
  // Край соседа — тот самый, по которому считается ширина кадра.
  for (const stage of [768, 1192, 1672]) {
    assert.ok(near(M.sideEdge(M.fanWidth(stage)), stage / 2 - 16, 1e-6), String(stage));
  }
  // Обычный экран: между соседом и краем колонки 16 px — от дальнего кадра остаётся кромка,
  // и за 8 px до края колонки его уже нет.
  for (const column of [768, 1036, 1192]) {
    const w = M.fanWidth(column);
    const band = M.fogBand(w, column);
    assert.ok(band.from > 40 && band.from < band.to && band.to < 75, JSON.stringify(band));
    const end = farPoint(w, band.to / 100);
    assert.ok(Math.abs(end - (column / 2 - 8)) < 1.5, `${column}: ${end}`);
    // У края соседа «туман» уже лежит, но кадр под ним ещё виден.
    const at = farPoint(w, band.from / 100);
    assert.ok(at < column / 2 - 16 && at > column / 2 - 16 - 6, `${column}: ${at}`);
  }
  // Широкий экран (1920, колонка 1672, кадр 760): места 88 px — кадр растворяется на 80.
  const wide = M.fogBand(760, 1672);
  assert.ok(Math.abs(farPoint(760, wide.to / 100) - (1672 / 2 - 8)) < 1.5, JSON.stringify(wide));
  assert.ok(wide.to - wide.from > 15, JSON.stringify(wide));
  // Очень широкий: растворяется на 96 px и не дальше — до края колонки далеко.
  const huge = M.fogBand(760, 2400);
  assert.ok(Math.abs(farPoint(760, huge.to / 100) - (M.sideEdge(760) + 96)) < 1.5, JSON.stringify(huge));
  assert.ok(huge.to < 100);
  // Ширина колонки неизвестна — как на самом тесном экране.
  assert.deepEqual(M.fogBand(620, null), M.fogBand(620, 2 * (M.sideEdge(620) + 16)));
  // Колонка уже самих соседей (окно сжали быстрее замера): дальний кадр закрыт сразу за краем соседа.
  const tight = M.fogBand(620, 900);
  assert.equal(tight.from, tight.to);
  assert.ok(Math.abs(farPoint(620, tight.to / 100) - M.sideEdge(620)) < 1.5, JSON.stringify(tight));
  // Кадра ещё нет — вуали нет.
  assert.deepEqual(M.fogBand(0, 1192), { from: 100, to: 100 });
  assert.deepEqual(M.fogBand(-5, null), { from: 100, to: 100 });
});

/* ---------- позиция ---------- */

test("кратчайший путь по кругу", () => {
  assert.equal(M.wrapDelta(10, 12), -2);
  assert.equal(M.wrapDelta(-11, 12), 1);
  assert.equal(M.wrapDelta(3, 12), 3);
  // Ровно полкруга — вперёд.
  assert.equal(M.wrapDelta(6, 12), 6);
  assert.equal(M.wrapDelta(5, 0), 0);
});

test("бесконечная карусель: позиция уходит за границы списка, кадр — по кругу", () => {
  let t = track(12);
  t = M.moveTrack(t, -1);
  assert.equal(t.pos, -1);
  assert.equal(M.activeIndex(t), 11);
  for (let i = 0; i < 14; i++) t = M.moveTrack(t, 1, true);
  assert.equal(t.pos, 13);
  assert.equal(M.activeIndex(t), 1);
  // К кадру по номеру — кратчайшим путём, без перемотки через весь круг.
  assert.equal(M.jumpTrack(t, 11).pos, 11);
  assert.equal(M.jumpTrack(t, 4).pos, 16);
  assert.equal(M.activeIndex(M.jumpTrack(t, 4)), 4);
});

test("короткая карусель (меньше 5 кадров) не замыкается: края держат, сама — возвращается к началу", () => {
  assert.equal(M.isLoop(5), true);
  assert.equal(M.isLoop(4), false);
  const start = track(3);
  // Стрелка и палец за край не ведут — возвращается тот же объект, перерисовки нет.
  assert.equal(M.moveTrack(start, -1), start);
  const end = M.moveTrack(start, 2);
  assert.equal(end.pos, 2);
  assert.equal(M.moveTrack(end, 1), end);
  assert.equal(M.moveTrack(end, 5).pos, 2);
  // Автолистание с последнего кадра — к первому.
  assert.equal(M.moveTrack(end, 1, true).pos, 0);
  assert.equal(M.jumpTrack(start, 2).pos, 2);
  assert.equal(M.jumpTrack(start, 9).pos, 2);
});

test("один кадр или ни одного: листать нечего", () => {
  const one = track(1);
  assert.equal(M.moveTrack(one, 1, true), one);
  assert.equal(M.jumpTrack(one, 0), one);
  assert.equal(M.activeIndex(track(0)), 0);
  assert.deepEqual(M.slotsAround(0, 0, 0), []);
  assert.deepEqual(M.slotsAround(0, 0, 1), [{ v: 0, index: 0, d: 0 }]);
  assert.equal(M.dragShift(-200, 300, 0, 1), 0);
});

test("состав сменился: держимся за кадр, который был в центре, иначе — за его место", () => {
  const t = { ids: ["a", "b", "c", "d", "e", "f"], pos: 8 }; // в центре «c»
  assert.equal(M.syncTrack(t, ["a", "b", "c", "d", "e", "f"]), t);
  assert.deepEqual(M.retrack(t, ["x", "c", "y"]), { ids: ["x", "c", "y"], pos: 1 });
  assert.equal(M.retrack(t, ["x", "y"]).pos, 1);
  assert.equal(M.retrack(t, ["x", "y", "z", "w"]).pos, 2);
  assert.equal(M.retrack(t, []).pos, 0);
  assert.equal(M.retrack({ ids: [], pos: 0 }, ["a"]).pos, 0);
  assert.equal(M.syncTrack(t, ["c"]).pos, 0);
});

test("места в разметке: по пять вокруг активного; у короткой карусели — без повторов", () => {
  const long = M.slotsAround(0, 0, 12);
  assert.deepEqual(long.map((s) => s.v), [-5, -4, -3, -2, -1, 0, 1, 2, 3, 4, 5]);
  assert.deepEqual(long.map((s) => s.index), [7, 8, 9, 10, 11, 0, 1, 2, 3, 4, 5]);
  assert.deepEqual(long.map((s) => s.d), [-5, -4, -3, -2, -1, 0, 1, 2, 3, 4, 5]);
  // На виду только |d| ≤ 2: всё, что дальше, стоит на невидимой стоянке.
  assert.deepEqual(long.filter((s) => M.slotLook(s.d).opacity > 0).map((s) => s.d), [-2, -1, 0, 1, 2]);
  // Пять кадров: на виду все разные, повторы — только на стоянке.
  const five = M.slotsAround(0, 0, 5);
  assert.equal(five.length, 11);
  const seen = five.filter((s) => Math.abs(s.d) <= 2).map((s) => s.index);
  assert.equal(new Set(seen).size, 5);
  // Прыжок через кадр: и ушедший (−2 → −4), и пришедший (4 → 2) уже в разметке — едут, а не возникают.
  const before = new Set(M.slotsAround(0, 0, 12).map((s) => s.v));
  const after = M.slotsAround(2, 0, 12);
  assert.ok(after.filter((s) => Math.abs(s.d) <= 2).every((s) => before.has(s.v)));
  assert.ok(after.some((s) => s.v === -2 && s.d === -4));
  // Короткая — только свои кадры, каждый один раз.
  assert.deepEqual(M.slotsAround(0, 0, 3).map((s) => [s.v, s.d]), [[0, 0], [1, 1], [2, 2]]);
  assert.deepEqual(M.slotsAround(1, 0, 2).map((s) => [s.index, s.d]), [[0, -1], [1, 0]]);
  // Пока тянут: окно идёт за пальцем, d дробное.
  const dragged = M.slotsAround(4, 1.4, 12);
  assert.deepEqual(dragged.map((s) => s.v), [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10]);
  assert.ok(near(dragged[5].d, -0.4));
});

/* ---------- перетаскивание ---------- */

test("шаг карусели в пикселях — сдвиг соседа из макета", () => {
  assert.ok(near(M.stepPx(500), 310));
});

test("кадры идут за пальцем: влево — к следующему, не дальше двух мест", () => {
  assert.ok(near(M.dragShift(-155, 310, 0, 12), 0.5));
  assert.ok(near(M.dragShift(155, 310, 0, 12), -0.5));
  assert.equal(M.dragShift(-5000, 310, 0, 12), 2);
  assert.equal(M.dragShift(100, 0, 0, 12), 0);
});

test("за краем короткой карусели кадр тянется туго и недалеко", () => {
  // Первый кадр, тянут вправо (назад): дальше 0.3 места не уходит.
  const back = M.dragShift(310, 310, 0, 3);
  assert.ok(back < 0 && back >= -0.3 - 1e-9, String(back));
  assert.ok(Math.abs(M.dragShift(31, 310, 0, 3)) < 0.1);
  // Внутри — как обычно.
  assert.ok(near(M.dragShift(-155, 310, 0, 3), 0.5));
  const fwd = M.dragShift(-620, 310, 2, 3);
  assert.ok(fwd > 0 && fwd <= 0.3 + 1e-9, String(fwd));
});

test("отпустили палец: короче 40 px — на место, дальше — хотя бы на кадр", () => {
  assert.equal(M.SWIPE_PX, 40);
  assert.equal(M.dragSteps(-39, 310), 0);
  assert.equal(M.dragSteps(-40, 310), 1);
  assert.equal(M.dragSteps(60, 310), -1);
  assert.equal(M.dragSteps(-500, 310), 2);
  assert.equal(M.dragSteps(-5000, 310), 2);
  assert.equal(M.dragSteps(-100, 0), 0);
});

/* ---------- ширина кадра ---------- */

// Где на экране окажется внешний край соседа при кадре шириной w (перспектива 1500).
const neighbourEdge = (w) => {
  const turn = (34 * Math.PI) / 180;
  const flat = (0.62 - 0.5 + 0.78 * Math.cos(turn)) * w;
  const depth = 0.78 * Math.sin(turn) * w;
  return (flat * 1500) / (1500 - depth);
};

test("сосед виден целиком: его внешний край — в 16 px от края колонки", () => {
  for (const stage of [768, 960, 1192, 1672]) {
    assert.ok(near(neighbourEdge(M.fanWidth(stage)), stage / 2 - 16, 1e-6), String(stage));
  }
  assert.equal(M.fanWidth(20), 0);
});

test("ширина кадра: макет, колонка и место над панелью запроса", () => {
  // Широкий высокий экран: потолок макета.
  assert.equal(M.fitWidth(1920, 1672, 900), 760);
  // 1440 с историей слева: колонка 1192 — кадр уже, чтобы соседи были видны целиком.
  const byColumn = M.fitWidth(1440, 1192, 900);
  assert.ok(byColumn > 600 && byColumn < 640, String(byColumn));
  assert.equal(M.fitWidth(1440, 1192, null), byColumn);
  // Места по высоте мало: кадр ужимается, чтобы встать над панелью целиком…
  const byFold = M.fitWidth(1440, 1192, 340);
  assert.equal(byFold, Math.round(((340 - 48) * 16) / 9));
  assert.ok(byFold < byColumn);
  // …но не больше чем до 62% своей ширины.
  assert.equal(M.fitWidth(1440, 1192, 120), Math.round(byColumn * 0.62));
  assert.equal(M.fitWidth(1440, 1192, -50), Math.round(byColumn * 0.62));
  // Планшет 768: 58vw с запасом режется колонкой.
  const tablet = M.fitWidth(768, 768, null);
  assert.ok(tablet <= 0.58 * 768 && tablet > 380, String(tablet));
  // Совсем узко — не меньше разумного минимума.
  assert.equal(M.fitWidth(300, 300, null), 240);
});

/* ---------- названия кадров и их ряд ---------- */

const RU = { film: "Киносцена", ad: "Реклама товара", i2v: "Image → Video" };
const ruName = (key) => RU[key] ?? "";
const clip = (scenario, title = "", subtitle = "Seedance 2.0") => ({ scenario, title, subtitle });

test("имя кадра: сценарий, без него — название работы, иначе модель", () => {
  assert.deepEqual(
    M.reelNames([clip("film", "Ночной переулок"), clip("ad"), clip(null, "Свой ролик"), clip(null), clip(null, "", "")], ruName),
    ["Киносцена", "Реклама товара", "Свой ролик", "Seedance 2.0", ""],
  );
  // Сцены мультстудии сценария не имеют — подписаны своим названием, как раньше.
  assert.deepEqual(M.reelNames([clip(null, "Космос", "Приключение")], ruName), ["Космос"]);
  // Ключ, которого нет в переводах (сервер новее), — как без сценария.
  assert.deepEqual(M.reelNames([clip("drone", "С дрона")], ruName), ["С дрона"]);
  assert.deepEqual(M.reelNames([], ruName), []);
});

test("второй ролик того же сценария называется по-своему — двух одинаковых чипов рядом нет", () => {
  const names = M.reelNames(
    [clip("film", "Ночной переулок"), clip("ad"), clip("film", "Погоня"), clip("film", "Киносцена"), clip("film")],
    ruName,
  );
  // Своего названия нет или оно то же, что у сценария, — имя сценария с номером, по порядку появления.
  assert.deepEqual(names, ["Киносцена", "Реклама товара", "Погоня", "Киносцена · 2", "Киносцена · 3"]);
  // Порядок важен: сценарием называется первый, даже если у него есть своё название.
  assert.equal(M.reelNames([clip("i2v", "Юрта у озера")], ruName)[0], "Image → Video");
});

test("большая карусель: несколько роликов сценария без своих названий — «Сценарий · 2», «· 3» по порядку", () => {
  assert.equal(M.NAME_SEP, " · ");
  // Номера идут подряд среди тех, кто назван сценарием: ролик со своим названием счёт не сбивает.
  const reel = [clip("ad"), clip("film"), clip("ad"), clip("ad", "Духи"), clip("film"), clip("ad"), clip("ad", "Реклама товара")];
  assert.deepEqual(M.reelNames(reel, ruName), [
    "Реклама товара",
    "Киносцена",
    "Реклама товара · 2",
    "Духи",
    "Киносцена · 2",
    "Реклама товара · 3",
    "Реклама товара · 4",
  ]);
  // Номер стоит после переведённого имени — на любом языке сайта.
  const EN = { film: "Cinematic scene", ad: "Product ad" };
  const enName = (key) => EN[key] ?? "";
  const served = [clip("film", "Киносцена"), clip("film", "Киносцена"), clip("ad", "Реклама товара"), clip("film", "Киносцена")];
  assert.deepEqual(M.reelNames(served, enName, ruName), ["Cinematic scene", "Cinematic scene · 2", "Product ad", "Cinematic scene · 3"]);
});

test("большая карусель: «Другое» и работы без названия — тоже без одинаковых чипов", () => {
  // «Другое» сценарием не считается: своё название, без него — модель; повторы — с номером.
  const other = [clip(null, "Демо"), clip(null), clip(null), clip(null, "", "Kling 3.0"), clip(null, "Демо"), clip(null), clip(null, "", "")];
  assert.deepEqual(M.reelNames(other, ruName), ["Демо", "Seedance 2.0", "Seedance 2.0 · 2", "Kling 3.0", "Демо · 2", "Seedance 2.0 · 3", ""]);
  // Назвать нечем — пустая строка у каждого: такой чип подписан номером ролика, он и так свой.
  assert.deepEqual(M.reelNames([clip(null, "", ""), clip(null, "", "")], ruName), ["", ""]);
  // Своё название совпало с именем чужого сценария — второй такой чип тоже с номером.
  assert.deepEqual(M.reelNames([clip("ad"), clip("film"), clip("film", "Реклама товара")], ruName), ["Реклама товара", "Киносцена", "Реклама товара · 2"]);
  // Владелец сам назвал работу «Киносцена · 2»: номер берём свободный.
  assert.deepEqual(M.reelNames([clip("film"), clip(null, "Киносцена · 2"), clip("film"), clip("film")], ruName), [
    "Киносцена",
    "Киносцена · 2",
    "Киносцена · 3",
    "Киносцена · 4",
  ]);
  // Сцены мультстудии с разными названиями — как раньше, без номеров.
  assert.deepEqual(M.reelNames([clip(null, "Космос", "Приключение"), clip(null, "Лес", "Приключение")], ruName), ["Космос", "Лес"]);
});

test("48 роликов двенадцати сценариев: каждое имя в ряду одно, первые двенадцать — без номеров", async () => {
  const C = await import("../scenarios.ts");
  const t = (key, options) => options.defaultValue;
  // Как на сервере: работе без своего названия панель ставит русское имя сценария.
  const reel = Array.from({ length: 48 }, (_, i) => {
    const key = C.SCENARIOS[i % 12];
    return clip(key, C.scenarioDefault(key));
  });
  const names = M.reelNames(reel, (key) => C.scenarioLabel(t, key), C.scenarioDefault);
  assert.equal(new Set(names).size, 48);
  assert.deepEqual(names.slice(0, 12), C.SCENARIOS.map((key) => C.scenarioDefault(key)));
  assert.deepEqual(names.slice(12, 15), ["Киносцена · 2", "Реклама товара · 2", "Персонаж · 2"]);
  assert.deepEqual(names.slice(45), ["Анимация · 4", "Реалистичная сцена · 4", "Reels / TikTok · 4"]);
  // Карусель из двенадцати разных сценариев — имена прежние: для неё ничего не изменилось.
  assert.deepEqual(M.reelNames(reel.slice(0, 12), (key) => C.scenarioLabel(t, key), C.scenarioDefault), names.slice(0, 12));
});

test("кадр назван одной моделью — заголовком на кадре её не повторяем, с номером тоже", () => {
  assert.equal(M.namedByModel("Seedance 2.0", clip(null)), true);
  assert.equal(M.namedByModel("Seedance 2.0 · 2", clip(null)), true);
  // Имя сценария и своё название — заголовок.
  assert.equal(M.namedByModel("Киносцена", clip("film")), false);
  assert.equal(M.namedByModel("Киносцена · 2", clip("film")), false);
  assert.equal(M.namedByModel("Свой ролик", clip(null, "Свой ролик")), false);
  // Своё название, которое начинается с имени модели, — всё равно своё.
  assert.equal(M.namedByModel("Seedance 2.0 · Ночь", clip(null, "Seedance 2.0 · Ночь")), false);
  // Название, равное модели, заголовком не писали и раньше.
  assert.equal(M.namedByModel("Seedance 2.0", clip(null, "Seedance 2.0")), true);
  // Модели нет — сравнивать не с чем.
  assert.equal(M.namedByModel("", clip(null, "", "")), false);
  assert.equal(M.namedByModel("Свой ролик", clip(null, "Свой ролик", "")), false);
});

test("название, которое работе поставил сервер, — не своё: на другом языке русское имя сценария не всплывает", async () => {
  // Панель и команда съёмки подписывают работу русским именем сценария. На английском оно не
  // равно переводу — и второй ролик сценария выходил с чипом «Киносцена» среди английских.
  const EN = { film: "Cinematic scene", ad: "Product ad" };
  const enName = (key) => EN[key] ?? "";
  const reel = [clip("film", "Киносцена"), clip("ad", "Реклама товара"), clip("film", "Киносцена"), clip("film", "Погоня")];
  assert.deepEqual(M.reelNames(reel, enName, ruName), ["Cinematic scene", "Product ad", "Cinematic scene · 2", "Погоня"]);
  // Без имён сервера — как раньше (так видно, что сверка идёт именно с ними).
  assert.deepEqual(M.reelNames(reel, enName), ["Cinematic scene", "Product ad", "Киносцена", "Погоня"]);
  // Чужое имя сценария — уже своё название: «Реклама товара» у киносцены владелец набрал сам.
  assert.deepEqual(M.reelNames([clip("film"), clip("film", "Реклама товара")], enName, ruName), ["Cinematic scene", "Реклама товара"]);
  // По-русски оба имени совпадают — ничего не меняется.
  assert.deepEqual(M.reelNames(reel, ruName, ruName), ["Киносцена", "Реклама товара", "Киносцена · 2", "Погоня"]);

  // Имена сервера карусель берёт из scenarios.ts — у каждого сценария оно есть и равно русскому названию.
  const C = await import("../scenarios.ts");
  const t = (key, options) => options.defaultValue;
  for (const key of C.SCENARIOS) assert.equal(C.scenarioDefault(key), C.scenarioLabel(t, key), key);
  assert.equal(C.scenarioDefault("film"), "Киносцена");
  // «Другое» и незнакомый ключ своего имени для подписи не дают.
  for (const none of ["other", "social", "", null, undefined, "toString"]) assert.equal(C.scenarioDefault(none), "", String(none));
});

test("лента телефона: пока она едет к выбранному кадру, часы карусели ждут именно его", () => {
  // Нажали чип десятого ролика, активный — первый: ждём десятый.
  const target = M.jumpTarget(9, 0);
  assert.equal(target, 9);
  // Лента в начале пути ещё раз встала на прежний кадр, потом задержалась на соседнем — часы стоят.
  assert.equal(M.jumpDone(target, 0), false);
  assert.equal(M.jumpDone(target, 1), false);
  assert.equal(M.jumpDone(target, 9), true);
  // Нажали чип кадра, который и так в центре: ехать некуда, часы не трогаем.
  assert.equal(M.jumpTarget(3, 3), null);
  assert.equal(M.jumpDone(null, 3), false);
  // С последнего кадра карусель сама возвращается к первому — это тоже переход.
  assert.equal(M.jumpTarget(0, 11), 0);
  assert.equal(M.jumpDone(0, 0), true);
  // Запасной срок длиннее самой долгой прокрутки, но заметно короче интервала карусели.
  assert.ok(M.JUMP_MS >= 1000 && M.JUMP_MS < M.REEL_INTERVAL_MS / 2);
});

/* ---------- большая карусель: что живёт в разметке ---------- */

test("сцена с 48 кадрами: в разметке те же одиннадцать мест, круг замыкается", () => {
  const big = M.slotsAround(0, 0, 48);
  assert.deepEqual(big.map((s) => s.index), [43, 44, 45, 46, 47, 0, 1, 2, 3, 4, 5]);
  // Сколько бы кадров ни было и куда бы ни ушла позиция — мест столько же, сколько у двенадцати.
  for (const count of [5, 12, 13, 24, 48]) {
    for (const pos of [0, 1, count - 1, count, -1, 7 * count + 3, -1000]) {
      const slots = M.slotsAround(pos, 0, count);
      assert.equal(slots.length, 2 * M.REACH + 1, `${count} @ ${pos}`);
      assert.deepEqual(slots.map((s) => s.d), [-5, -4, -3, -2, -1, 0, 1, 2, 3, 4, 5], `${count} @ ${pos}`);
      assert.ok(slots.every((s) => s.index === M.mod(s.v, count)), `${count} @ ${pos}`);
    }
  }
  // Пока тянут пальцем — тоже одиннадцать.
  assert.equal(M.slotsAround(40, -1.6, 48).length, 11);

  // Круг: назад с первого — последний, полный оборот возвращает на место.
  let t = track(48);
  assert.equal(M.activeIndex(M.moveTrack(t, -1)), 47);
  for (let i = 0; i < 48; i++) t = M.moveTrack(t, 1, true);
  assert.deepEqual([t.pos, M.activeIndex(t)], [48, 0]);
  // К далёкому кадру — кратчайшей дорогой: до 25-го вперёд, до 26-го уже назад.
  assert.equal(M.jumpTrack(track(48), 47).pos, -1);
  assert.equal(M.jumpTrack(track(48), 24).pos, 24);
  assert.equal(M.jumpTrack(track(48), 25).pos, -23);
  assert.equal(M.activeIndex(M.jumpTrack(track(48, 100), 30)), 30);
});

test("лента телефона: до двенадцати кадров живёт целиком, длиннее — только кадры рядом с активным", () => {
  const live = (active, aim, count) =>
    Array.from({ length: count }, (_, i) => i).filter((i) => M.stripLive(i, active, aim, count));
  assert.deepEqual([M.STRIP_WHOLE, M.STRIP_NEAR], [12, 2]);
  // Короткая лента — как раньше: живые все, где бы ни стоял активный и куда бы она ни ехала.
  for (const count of [1, 2, 5, 12]) {
    for (const active of [0, count - 1]) {
      assert.equal(live(active, null, count).length, count, `${count} @ ${active}`);
      assert.equal(live(active, 0, count).length, count, `${count} @ ${active}`);
    }
  }
  // Длинная: активный, по два соседа с каждой стороны — и всё.
  assert.deepEqual(live(20, null, 48), [18, 19, 20, 21, 22]);
  assert.deepEqual(live(0, null, 48), [0, 1, 2]);
  assert.deepEqual(live(6, null, 13), [4, 5, 6, 7, 8]);
  // С последнего кадра карусель сама вернётся к первому — он готов заранее.
  assert.deepEqual(live(47, null, 48), [0, 45, 46, 47]);
  assert.deepEqual(live(46, null, 48), [44, 45, 46, 47]);
  // Лента едет к далёкому кадру: он и его соседи оживают сразу, кадры по дороге — нет.
  assert.deepEqual(live(0, 30, 48), [0, 1, 2, 28, 29, 30, 31, 32]);
  assert.deepEqual(live(47, 0, 48), [0, 1, 2, 45, 46, 47]);
  // Активный кадр живой всегда, а живых — не больше десяти, сколько бы кадров ни было.
  let most = 0;
  for (let active = 0; active < 48; active++) {
    assert.equal(M.stripLive(active, active, null, 48), true);
    for (const aim of [null, ...Array.from({ length: 48 }, (_, i) => i)]) {
      most = Math.max(most, live(active, aim, 48).length);
    }
  }
  assert.equal(most, 10);
});

test("лента телефона: кадр под пальцем живой сразу, не дожидаясь, пока лента встанет", () => {
  // Как их считает ReelStrip: от активного и от того, к которому едут или который под пальцем.
  const live = (spot, aim, count) =>
    Array.from({ length: count }, (_, i) => i).filter((i) => M.stripLive(i, spot.centered, aim ?? spot.passing, count));

  // 48 роликов, лента стоит на первом. Три быстрых смахивания: встать между ними лента
  // не успевает, и активным всё это время остаётся первый кадр.
  let spot = M.STRIP_START;
  assert.deepEqual(live(spot, null, 48), [0, 1, 2]);
  for (const seen of [1, 2, 3]) {
    spot = M.stripSeen(spot, null, seen, 48);
    assert.equal(spot.centered, 0, "ролик и часы ждут, пока лента встанет");
    // Кадр в центре и оба соседа, чьи края видны, — с картинкой, а не пустой рамкой.
    for (const i of [seen - 1, seen, seen + 1]) assert.ok(live(spot, null, 48).includes(i), `${i} при ${seen}`);
  }
  assert.deepEqual(live(spot, null, 48), [0, 1, 2, 3, 4, 5]);

  // Лента встала на четвёртом кадре: он активный, живые снова считаются только от него.
  spot = M.stripSettled(spot, 3);
  assert.deepEqual(spot, { centered: 3, passing: null });
  assert.deepEqual(live(spot, null, 48), [1, 2, 3, 4, 5]);

  // Нажали чип 31-го ролика: лента едет сама — кадры по дороге ничего не грузят.
  for (const seen of [4, 9, 17, 29]) {
    spot = M.stripSeen(spot, 30, seen, 48);
    assert.equal(spot.passing, null, `по дороге, кадр ${seen}`);
    assert.deepEqual(live(spot, 30, 48), [1, 2, 3, 4, 5, 28, 29, 30, 31, 32]);
  }
  // Доехала. Рядом с кадром, мимо которого раньше вели пальцем, живых не осталось.
  spot = M.stripSettled(spot, 30);
  assert.deepEqual(live(spot, null, 48), [28, 29, 30, 31, 32]);

  // Смахнули и, не дав ленте встать, нажали чип: дальше кадр под пальцем не в счёт.
  const swiped = M.stripSeen(M.STRIP_START, null, 4, 48);
  assert.deepEqual(swiped, { centered: 0, passing: 4 });
  assert.deepEqual(M.stripSeen(swiped, 20, 5, 48), { centered: 0, passing: null });
  // Ленту в пути перехватили пальцем (цели больше нет) — снова следим за кадром под ним.
  assert.deepEqual(M.stripSeen({ centered: 0, passing: null }, null, 17, 48), { centered: 0, passing: 17 });

  // Живых по-прежнему не больше десяти, где бы ни был активный и какой бы кадр ни был под пальцем.
  let most = 0;
  for (let centered = 0; centered < 48; centered++) {
    for (let seen = 0; seen < 48; seen++) {
      most = Math.max(most, live(M.stripSeen({ centered, passing: null }, null, seen, 48), null, 48).length);
    }
  }
  assert.equal(most, 10);

  // Лента до двенадцати кадров живёт целиком: следить не за чем, и состояние не меняется
  // (тот же объект — лишней перерисовки нет).
  for (const count of [2, 5, 12]) assert.equal(M.stripSeen(M.STRIP_START, null, 1, count), M.STRIP_START, String(count));
  assert.equal(M.stripSeen(M.STRIP_START, null, 1, 13).passing, 1);
  // Повторный сигнал о том же кадре и остановка на уже активном — тоже без перерисовки.
  assert.equal(M.stripSeen(swiped, null, 4, 48), swiped);
  assert.equal(M.stripSettled(M.STRIP_START, 0), M.STRIP_START);
});

test("ряд названий: активный чип — посередине, у краёв ряд упирается", () => {
  // Ряд 1300 в окне 400: чип 500…600 встаёт по центру.
  assert.equal(M.railScroll(500, 100, 400, 1300), 350);
  // Первый чип: левее начала ряд не уходит.
  assert.equal(M.railScroll(16, 90, 400, 1300), 0);
  // Последний: правее конца — тоже.
  assert.equal(M.railScroll(1190, 94, 400, 1300), 900);
  // Всё помещается — ряд стоит.
  assert.equal(M.railScroll(700, 120, 1400, 1300), 0);
  assert.equal(M.railScroll(700, 120, 1300, 1300), 0);
  // Дробные размеры (масштаб страницы) — целое число пикселей.
  assert.equal(M.railScroll(500.4, 99.3, 399.5, 1300.2), 350);
});

test("ряд названий: стрелки по краям — только у длинного ряда и только туда, где есть продолжение", () => {
  const none = { prev: false, next: false };
  // До двенадцати названий ряд остаётся каким был: стрелок нет, даже если он не помещается.
  assert.equal(M.RAIL_WHOLE, 12);
  for (const count of [2, 5, 12]) {
    for (const fade of ["none", "start", "mid", "end"]) assert.deepEqual(M.railArrows(count, fade), none, `${count} ${fade}`);
  }
  // Длинный ряд: в начале листать можно только вперёд, в конце — только назад.
  for (const count of [13, 24, 48]) {
    assert.deepEqual(M.railArrows(count, "start"), { prev: false, next: true }, String(count));
    assert.deepEqual(M.railArrows(count, "mid"), { prev: true, next: true }, String(count));
    assert.deepEqual(M.railArrows(count, "end"), { prev: true, next: false }, String(count));
    // Поместился целиком (очень широкий экран) — листать нечего.
    assert.deepEqual(M.railArrows(count, "none"), none, String(count));
  }
});

test("вертикальный ролик узнаём по записи пропорций", () => {
  assert.equal(M.isPortrait("9:16"), true);
  assert.equal(M.isPortrait("3:4"), true);
  assert.equal(M.isPortrait(" 2 : 3 "), true);
  assert.equal(M.isPortrait("16:9"), false);
  assert.equal(M.isPortrait("1:1"), false);
  assert.equal(M.isPortrait("21/9"), false);
  // Что не разобрать — не вертикальное: кадр заполнит рамку, как раньше.
  for (const odd of ["", "auto", "9x16", "0:16", "16:", "portrait"]) assert.equal(M.isPortrait(odd), false, odd);
});
