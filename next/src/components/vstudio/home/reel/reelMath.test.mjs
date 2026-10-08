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
  // Своего названия нет или оно то же, что у сценария, — остаётся имя сценария.
  assert.deepEqual(names, ["Киносцена", "Реклама товара", "Погоня", "Киносцена", "Киносцена"]);
  // Порядок важен: сценарием называется первый, даже если у него есть своё название.
  assert.equal(M.reelNames([clip("i2v", "Юрта у озера")], ruName)[0], "Image → Video");
});

test("название, которое работе поставил сервер, — не своё: на другом языке русское имя сценария не всплывает", async () => {
  // Панель и команда съёмки подписывают работу русским именем сценария. На английском оно не
  // равно переводу — и второй ролик сценария выходил с чипом «Киносцена» среди английских.
  const EN = { film: "Cinematic scene", ad: "Product ad" };
  const enName = (key) => EN[key] ?? "";
  const reel = [clip("film", "Киносцена"), clip("ad", "Реклама товара"), clip("film", "Киносцена"), clip("film", "Погоня")];
  assert.deepEqual(M.reelNames(reel, enName, ruName), ["Cinematic scene", "Product ad", "Cinematic scene", "Погоня"]);
  // Без имён сервера — как раньше (так видно, что сверка идёт именно с ними).
  assert.deepEqual(M.reelNames(reel, enName), ["Cinematic scene", "Product ad", "Киносцена", "Погоня"]);
  // Чужое имя сценария — уже своё название: «Реклама товара» у киносцены владелец набрал сам.
  assert.deepEqual(M.reelNames([clip("film"), clip("film", "Реклама товара")], enName, ruName), ["Cinematic scene", "Реклама товара"]);
  // По-русски оба имени совпадают — ничего не меняется.
  assert.deepEqual(M.reelNames(reel, ruName, ruName), ["Киносцена", "Реклама товара", "Киносцена", "Погоня"]);

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
