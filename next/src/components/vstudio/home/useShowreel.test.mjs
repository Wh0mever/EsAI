// Витрина первого экрана: кэш, общий запрос и сбои источников (home/useShowreel.ts).
// Запуск (Node 22.6+):  node --experimental-strip-types --test src/components/vstudio/home/*.test.mjs
import "../../../lib/vstudio/nodeTsHooks.mjs";
import { afterEach, beforeEach, test } from "node:test";
import assert from "node:assert/strict";

const R = await import("./useShowreel.ts");

const realFetch = globalThis.fetch;
const realNow = Date.now;
let calls = [];
/** Что ответит «сервер»: статус и тело по куску адреса. */
let routes = {};

const json = (status, body) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

const showcaseBody = (ids) => ({
  items: ids.map((id) => ({
    id,
    title: `Работа ${id}`,
    category: "film",
    kind: "video",
    model: { id: "bytedance/seedance-2.0", name: "Seedance 2.0" },
    aspect_ratio: "16:9",
    duration_s: 5,
    video_url: `/media/vstudio/${id}.mp4`,
    poster_url: `/media/vstudio/${id}.jpg`,
  })),
});

const presetsBody = (lang, n = 6) => ({
  categories: [{ slug: "tales", title: lang === "en" ? "Tales" : "Сказки", emoji: "" }],
  presets: Array.from({ length: n }, (_, i) => ({
    id: i + 1,
    slug: `scene-${i + 1}`,
    title: `${lang}:${i + 1}`,
    subtitle: "",
    preview_video: `/media/cartoon/${i + 1}.mp4`,
    preview_poster: `/media/cartoon/${i + 1}.jpg`,
    duration: 5,
    aspect_ratio: "16:9",
    category: "tales",
    is_pick: true,
  })),
  popular: [],
});

beforeEach(() => {
  R.resetShowreelCache();
  calls = [];
  routes = {
    "vstudio/showcase/": () => json(200, showcaseBody([1, 2])),
    "cartoon/presets/": (url) => json(200, presetsBody(new URL(url, "http://x").searchParams.get("lang"))),
  };
  globalThis.fetch = async (url) => {
    calls.push(String(url));
    const hit = Object.keys(routes).find((part) => String(url).includes(part));
    const answer = routes[hit];
    if (answer === "offline") throw new TypeError("Failed to fetch");
    return answer(String(url));
  };
});

afterEach(() => {
  R.resetShowreelCache();
  globalThis.fetch = realFetch;
  Date.now = realNow;
});

test("до ответа — загрузка; после — карусель, повторный вызов берёт из кэша", async () => {
  assert.equal(R.peekShowreel("ru").loading, true);
  assert.deepEqual(R.peekShowreel("ru").reel, []);
  assert.equal(R.peekShowreel("ru").source, null);
  await R.loadShowreel("ru");
  const view = R.peekShowreel("ru");
  assert.equal(view.loading, false);
  // Двух роликов студии на карусель мало — она целиком у мультстудии.
  assert.equal(view.source, "cartoon");
  assert.deepEqual(view.reel.map((i) => i.id), [1, 2, 3, 4, 5, 6].map((n) => `ct:scene-${n}`));
  assert.equal(view.cartoonPoster, "/media/cartoon/1.jpg");
  assert.deepEqual(calls, ["/api/vstudio/showcase/", "/api/cartoon/presets/?lang=ru"]);

  await R.loadShowreel("ru");
  assert.equal(calls.length, 2, "свежий кэш — без запросов");
  assert.equal(R.peekShowreel("ru"), view, "тот же объект — подписчики не перерисовываются");
});

test("роликов студии хватает — карусель из них, сцены мультстудии в неё не попадают", async () => {
  routes["vstudio/showcase/"] = () => json(200, showcaseBody([1, 2, 3, 4, 5]));
  await R.loadShowreel("ru");
  const view = R.peekShowreel("ru");
  assert.equal(view.source, "vstudio");
  assert.deepEqual(view.reel.map((i) => i.id), ["vs:1", "vs:2", "vs:3", "vs:4", "vs:5"]);
  // Постер для карточки «Мультстудия» при этом всё равно есть.
  assert.equal(view.cartoonPoster, "/media/cartoon/1.jpg");
});

test("параллельные вызовы делят один запрос", async () => {
  const a = R.loadShowreel("ru");
  const b = R.loadShowreel("ru");
  assert.equal(a, b);
  await Promise.all([a, b]);
  assert.equal(calls.length, 2);
});

test("витрина студии не ответила (404) — первый экран живёт на мультстудии, и наоборот", async () => {
  routes["vstudio/showcase/"] = () => json(404, { detail: "Not found" });
  await R.loadShowreel("ru");
  let view = R.peekShowreel("ru");
  assert.equal(view.loading, false);
  assert.equal(view.source, "cartoon");
  assert.equal(view.reel.length, 6);
  assert.ok(view.reel.every((i) => i.source === "cartoon"));

  R.resetShowreelCache();
  routes["vstudio/showcase/"] = () => json(200, showcaseBody([7]));
  routes["cartoon/presets/"] = "offline";
  await R.loadShowreel("ru");
  view = R.peekShowreel("ru");
  assert.equal(view.loading, false);
  // Сцен нет вовсе — единственный ролик студии лучше пустого экрана.
  assert.equal(view.source, "vstudio");
  assert.deepEqual(view.reel.map((i) => i.id), ["vs:7"]);
  assert.equal(view.cartoonPoster, null);
});

test("оба источника молчат — пустая витрина, а не вечная загрузка; ответ не JSON — тоже", async () => {
  routes["vstudio/showcase/"] = "offline";
  routes["cartoon/presets/"] = "offline";
  await R.loadShowreel("ru");
  assert.deepEqual(R.peekShowreel("ru"), { reel: [], source: null, cartoonPoster: null, trends: [], loading: false });

  R.resetShowreelCache();
  routes["vstudio/showcase/"] = () => new Response("<html>502</html>", { status: 200, headers: { "content-type": "text/html" } });
  routes["cartoon/presets/"] = () => json(200, ["не тот вид"]);
  await R.loadShowreel("ru");
  assert.deepEqual(R.peekShowreel("ru").reel, []);
  assert.equal(R.peekShowreel("ru").loading, false);
});

test("кэш живёт 10 минут; неудачный ответ — 30 секунд; сбой при обновлении не стирает ролики", async () => {
  let now = 1_000_000;
  Date.now = () => now;
  await R.loadShowreel("ru");
  const first = R.peekShowreel("ru");

  now += R.SHOWREEL_TTL_MS - 1;
  await R.loadShowreel("ru");
  assert.equal(calls.length, 2);

  // Срок вышел, а сервер лежит: показываем прежнее.
  now += 2;
  routes["vstudio/showcase/"] = () => json(404, {});
  routes["cartoon/presets/"] = () => json(404, {});
  await R.loadShowreel("ru");
  assert.equal(calls.length, 4);
  assert.equal(R.peekShowreel("ru"), first);

  // Неудачный ответ помним недолго.
  now += R.SHOWREEL_RETRY_MS - 1;
  await R.loadShowreel("ru");
  assert.equal(calls.length, 4);
  now += 2;
  routes["vstudio/showcase/"] = () => json(200, showcaseBody([1, 2, 3, 4, 5]));
  routes["cartoon/presets/"] = () => json(200, presetsBody("ru"));
  await R.loadShowreel("ru");
  assert.equal(calls.length, 6);
  // За это время владелец добрал пять роликов — карусель перешла к студии.
  assert.equal(first.source, "cartoon");
  assert.equal(R.peekShowreel("ru").source, "vstudio");
  assert.equal(R.peekShowreel("ru").reel.length, 5);
});

const THIRTY = Array.from({ length: 30 }, (_, i) => i + 1);

test("размер карусели приходит с витриной: сервер прежней версии его не шлёт — тогда 12", async () => {
  routes["vstudio/showcase/"] = () => json(200, { ...showcaseBody(THIRTY), reel_size: 24 });
  await R.loadShowreel("ru");
  const view = R.peekShowreel("ru");
  assert.equal(view.source, "vstudio");
  assert.deepEqual(view.reel.map((i) => i.id), THIRTY.slice(0, 24).map((n) => `vs:${n}`));

  // Поля нет или в нём не размер — карусель в двенадцать роликов, как была.
  for (const body of [{}, { reel_size: "24" }, { reel_size: 49 }, { reel_size: 4 }, { reel_size: 24.5 }, { reel_size: null }, { reel_size: true }]) {
    R.resetShowreelCache();
    routes["vstudio/showcase/"] = () => json(200, { ...showcaseBody(THIRTY), ...body });
    await R.loadShowreel("ru");
    assert.equal(R.peekShowreel("ru").reel.length, 12, JSON.stringify(body));
  }

  // Размер — потолок: роликов меньше — карусель из тех, что есть.
  R.resetShowreelCache();
  routes["vstudio/showcase/"] = () => json(200, { ...showcaseBody(THIRTY), reel_size: 48 });
  await R.loadShowreel("ru");
  assert.equal(R.peekShowreel("ru").reel.length, 30);
});

test("владелец сменил размер, не тронув роликов, — карусель перерисовывается; тот же размер — нет", async () => {
  let now = 1_000_000;
  Date.now = () => now;
  let size = 12;
  routes["vstudio/showcase/"] = () => json(200, { ...showcaseBody(THIRTY), reel_size: size });
  await R.loadShowreel("ru");
  const twelve = R.peekShowreel("ru");
  assert.equal(twelve.reel.length, 12);

  now += R.SHOWREEL_TTL_MS + 1;
  await R.loadShowreel("ru");
  assert.equal(R.peekShowreel("ru"), twelve, "ответ тот же — тот же объект");

  size = 24;
  now += R.SHOWREEL_TTL_MS + 1;
  await R.loadShowreel("ru");
  const wide = R.peekShowreel("ru");
  assert.notEqual(wide, twelve);
  assert.equal(wide.reel.length, 24);
  // Первые двенадцать — те же ролики на тех же местах: карусель дополнилась, а не перемешалась.
  assert.deepEqual(wide.reel.slice(0, 12).map((i) => i.id), twelve.reel.map((i) => i.id));

  size = 5;
  now += R.SHOWREEL_TTL_MS + 1;
  await R.loadShowreel("ru");
  assert.equal(R.peekShowreel("ru").reel.length, 5);
});

test("витрина не ответила при обновлении: размер карусели остаётся прежним, а не падает до 12", async () => {
  let now = 1_000_000;
  Date.now = () => now;
  routes["vstudio/showcase/"] = () => json(200, { ...showcaseBody(THIRTY), reel_size: 24 });
  await R.loadShowreel("ru");
  const wide = R.peekShowreel("ru");
  assert.equal(wide.reel.length, 24);

  // Сбой витрины при том же ответе мультстудии: ничего не изменилось — тот же объект.
  now += R.SHOWREEL_TTL_MS + 1;
  routes["vstudio/showcase/"] = () => json(503, {});
  await R.loadShowreel("ru");
  assert.equal(R.peekShowreel("ru"), wide);

  // Сбой витрины, а сцены мультстудии сменились: карусель собирается заново — с прежними роликами и прежним размером.
  now += R.SHOWREEL_RETRY_MS + 1;
  routes["cartoon/presets/"] = () => json(200, presetsBody("ru", 9));
  await R.loadShowreel("ru");
  const rebuilt = R.peekShowreel("ru");
  assert.notEqual(rebuilt, wide);
  assert.equal(rebuilt.source, "vstudio");
  assert.deepEqual(rebuilt.reel.map((i) => i.id), wide.reel.map((i) => i.id));

  // Витрина не ответила с самого начала — размеру взяться неоткуда: 12 сцен мультстудии, как раньше.
  R.resetShowreelCache();
  routes["cartoon/presets/"] = () => json(200, presetsBody("ru", 20));
  await R.loadShowreel("ru");
  assert.equal(R.peekShowreel("ru").source, "cartoon");
  assert.equal(R.peekShowreel("ru").reel.length, 12);
});

test("вернулась сеть: неудачный ответ перезапрашиваем сразу, удачный — нет", async () => {
  routes["cartoon/presets/"] = () => json(404, {});
  await R.loadShowreel("ru");
  assert.equal(calls.length, 2);
  assert.deepEqual(R.peekShowreel("ru").reel.map((i) => i.id), ["vs:1", "vs:2"]);
  routes["cartoon/presets/"] = () => json(200, presetsBody("ru"));
  await R.loadShowreel("ru", true);
  assert.equal(calls.length, 4);
  assert.equal(R.peekShowreel("ru").source, "cartoon");
  assert.equal(R.peekShowreel("ru").reel.length, 6);
  await R.loadShowreel("ru", true);
  assert.equal(calls.length, 4);
});

test("язык: своя витрина на каждый; пока новая в пути — показываем прежнюю, без заглушек", async () => {
  await R.loadShowreel("ru");
  const ru = R.peekShowreel("ru");
  assert.equal(R.peekShowreel("en"), ru, "новый язык ещё не пришёл — прежние ролики");

  // Ответ на старый язык, пришедший позже, не должен подменить новый.
  let releaseRu;
  const ruSlow = new Promise((resolve) => {
    releaseRu = resolve;
  });
  Date.now = () => realNow() + R.SHOWREEL_TTL_MS + 1;
  const base = routes["cartoon/presets/"];
  routes["cartoon/presets/"] = async (url) => {
    if (url.includes("lang=ru")) await ruSlow;
    return base(url);
  };
  const again = R.loadShowreel("ru");
  await R.loadShowreel("en");
  const en = R.peekShowreel("en");
  assert.equal(en.reel[0].title, "en:1");
  releaseRu();
  await again;
  assert.equal(R.peekShowreel("en"), en);
  assert.equal(R.peekShowreel("ru").reel[0].title, "ru:1");
  assert.ok(calls.includes("/api/cartoon/presets/?lang=en"));
});

/* ---------- «Тренды» ---------- */

/** Ответ витрины с «Трендами»: свой список рядом с items, та же карточка. */
const withTrends = (reelIds, trendIds) => ({ ...showcaseBody(reelIds), trends: showcaseBody(trendIds).items });

test("«Тренды» приходят тем же ответом витрины, своим списком — в карусель не попадают", async () => {
  assert.deepEqual(R.peekShowreel("ru").trends, [], "пока витрина в пути — пусто");
  routes["vstudio/showcase/"] = () => json(200, withTrends([1, 2, 3, 4, 5], [11, 12]));
  await R.loadShowreel("ru");
  const view = R.peekShowreel("ru");
  assert.deepEqual(view.reel.map((i) => i.id), ["vs:1", "vs:2", "vs:3", "vs:4", "vs:5"]);
  assert.deepEqual(view.trends.map((i) => i.id), ["vs:11", "vs:12"]);
  assert.equal(calls.length, 2, "отдельного запроса за «Трендами» нет");

  // Сервер прежней версии ключа не присылает — «Трендов» нет, карусель та же.
  R.resetShowreelCache();
  routes["vstudio/showcase/"] = () => json(200, showcaseBody([1, 2, 3, 4, 5]));
  await R.loadShowreel("ru");
  assert.deepEqual(R.peekShowreel("ru").trends, []);
  assert.equal(R.peekShowreel("ru").reel.length, 5);
});

test("«Тренды» не зависят от карусели: ролики студии ушли мультстудии, а «Тренды» на месте", async () => {
  routes["vstudio/showcase/"] = () => json(200, withTrends([1], [11, 12, 13]));
  await R.loadShowreel("ru");
  const view = R.peekShowreel("ru");
  assert.equal(view.source, "cartoon");
  assert.deepEqual(view.trends.map((i) => i.id), ["vs:11", "vs:12", "vs:13"]);
});

test("владелец поменял «Тренды», не тронув карусели, — витрина перерисовывается; тот же ответ — нет", async () => {
  let now = 1_000_000;
  Date.now = () => now;
  let trends = [11, 12];
  routes["vstudio/showcase/"] = () => json(200, withTrends([1, 2, 3, 4, 5], trends));
  await R.loadShowreel("ru");
  const first = R.peekShowreel("ru");

  now += R.SHOWREEL_TTL_MS + 1;
  await R.loadShowreel("ru");
  assert.equal(R.peekShowreel("ru"), first, "ответ тот же — тот же объект");

  trends = [12, 11, 13];
  now += R.SHOWREEL_TTL_MS + 1;
  await R.loadShowreel("ru");
  const next = R.peekShowreel("ru");
  assert.notEqual(next, first);
  assert.deepEqual(next.trends.map((i) => i.id), ["vs:12", "vs:11", "vs:13"]);
  assert.deepEqual(next.reel.map((i) => i.id), first.reel.map((i) => i.id));
});

test("витрина не ответила при обновлении: «Тренды» остаются прежними, а не пропадают", async () => {
  let now = 1_000_000;
  Date.now = () => now;
  routes["vstudio/showcase/"] = () => json(200, withTrends([1, 2, 3, 4, 5], [11, 12]));
  await R.loadShowreel("ru");
  const before = R.peekShowreel("ru");

  now += R.SHOWREEL_TTL_MS + 1;
  routes["vstudio/showcase/"] = () => json(503, {});
  routes["cartoon/presets/"] = () => json(200, presetsBody("ru", 9));
  await R.loadShowreel("ru");
  const after = R.peekShowreel("ru");
  assert.notEqual(after, before, "сцены мультстудии сменились — витрина собрана заново");
  assert.deepEqual(after.trends.map((i) => i.id), ["vs:11", "vs:12"]);

  // Витрина не ответила с самого начала — «Трендов» нет, но и не вечная загрузка.
  R.resetShowreelCache();
  await R.loadShowreel("ru");
  assert.deepEqual(R.peekShowreel("ru").trends, []);
  assert.equal(R.peekShowreel("ru").loading, false);
});
