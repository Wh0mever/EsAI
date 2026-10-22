// «Склейка видео»: порядок, пределы, перетаскивание, ссылка ?add=, подписи и ошибки (mergeLogic.ts).
// Запуск (Node 22.6+):  node --experimental-strip-types --test src/components/merge/*.test.mjs
import "../../lib/vstudio/nodeTsHooks.mjs";
import { test } from "node:test";
import assert from "node:assert/strict";

const m = await import("./mergeLogic.ts");
const { MERGE_ERROR_RU, MERGE_FAIL_RU } = await import("./mergeText.ts");

const LIMITS = { min_fragments: 2, max_fragments: 30, max_total_s: 300, retention_days: 30 };
const item = (id, duration_s = 5, extra = {}) => ({
  type: "vstudio",
  id: String(id),
  title: `Ролик ${id}`,
  subtitle: "",
  poster: null,
  url: `/media/${id}.mp4`,
  duration_s,
  width: 1280,
  height: 720,
  available: true,
  ...extra,
});
const ids = (list) => list.map((i) => i.id);

test("moveItem: вверх, вниз, к краю; без перемены — тот же массив", () => {
  const list = [item(1), item(2), item(3), item(4)];
  assert.deepEqual(ids(m.moveItem(list, 2, 1)), ["1", "3", "2", "4"]);
  assert.deepEqual(ids(m.moveItem(list, 0, 3)), ["2", "3", "4", "1"]);
  assert.deepEqual(ids(m.moveItem(list, 3, -5)), ["4", "1", "2", "3"]);
  assert.deepEqual(ids(m.moveItem(list, 1, 99)), ["1", "3", "4", "2"]);
  assert.equal(m.moveItem(list, 2, 2), list);
  assert.equal(m.moveItem(list, 7, 0), list);
  assert.deepEqual(ids(list), ["1", "2", "3", "4"], "исходный список не меняется");
});

test("removeAt убирает одну карточку, повторы ролика остаются", () => {
  const list = [item(1), item(2), item(1)];
  assert.deepEqual(ids(m.removeAt(list, 0)), ["2", "1"]);
  assert.equal(m.removeAt(list, 3), list);
});

test("addRefusal: 30 фрагментов, 300 с с допуском 0,5 с, нечитаемый ролик", () => {
  assert.equal(m.addRefusal([], item(1, 5), LIMITS), null);
  const thirty = Array.from({ length: 30 }, (_, i) => item(i, 1));
  assert.deepEqual(m.addRefusal(thirty, item(99, 1), LIMITS), { code: "too_many_fragments", max: 30 });
  const long = [item(1, 150), item(2, 145)];
  assert.equal(m.addRefusal(long, item(3, 5.5), LIMITS), null, "300,5 с — ещё можно");
  assert.deepEqual(m.addRefusal(long, item(3, 5.6), LIMITS), { code: "too_long", max_s: 300, total_s: 300.6 });
  assert.deepEqual(m.addRefusal([], item(1, null), LIMITS), { code: "source_unreadable" });
  assert.deepEqual(m.addRefusal([], item(1, 0), LIMITS), { code: "source_unreadable" });
});

test("renderBlock: порядок причин как у сервера", () => {
  assert.deepEqual(m.renderBlock([], LIMITS), { code: "too_few_fragments", min: 2 });
  assert.deepEqual(m.renderBlock([item(1)], LIMITS), { code: "too_few_fragments", min: 2 });
  assert.deepEqual(m.renderBlock([item(1), item(2, 5, { available: false })], LIMITS), {
    code: "source_unavailable",
    index: 1,
  });
  assert.deepEqual(m.renderBlock([item(1, null), item(2)], LIMITS), { code: "source_unreadable", index: 0 });
  assert.deepEqual(m.renderBlock([item(1, 200), item(2, 100.6)], LIMITS), {
    code: "too_long",
    total_s: 300.6,
    max_s: 300,
  });
  assert.equal(m.renderBlock([item(1, 200), item(2, 100.5)], LIMITS), null);
  assert.equal(m.renderBlock([item(1), item(1)], LIMITS), null, "один ролик дважды — можно");
});

test("totalDuration и formatDuration", () => {
  assert.equal(m.totalDuration([item(1, 5.04), item(2, 4.98), item(3, null)]), 10);
  assert.equal(m.formatDuration(0), "0:00");
  assert.equal(m.formatDuration(5.4), "0:05");
  assert.equal(m.formatDuration(59.6), "1:00");
  assert.equal(m.formatDuration(312), "5:12");
  assert.equal(m.formatDuration(null), "0:00");
  assert.equal(m.formatDuration(Number.NaN), "0:00");
});

test("dropIndex и shiftFor: куда встанет строка и как расступаются соседи", () => {
  const mids = [50, 150, 250, 350];
  assert.equal(m.dropIndex(mids, 0, 40), 0);
  assert.equal(m.dropIndex(mids, 0, 160), 1);
  assert.equal(m.dropIndex(mids, 0, 999), 3);
  assert.equal(m.dropIndex(mids, 3, 140), 1);
  assert.equal(m.dropIndex(mids, 3, 10), 0);
  assert.equal(m.dropIndex(mids, 2, 260), 2, "на своём месте");
  // Тащим первую строку на третье место: вторая и третья уходят вверх.
  assert.deepEqual([0, 1, 2, 3].map((i) => m.shiftFor(i, 0, 2, 100)), [0, -100, -100, 0]);
  // Тащим последнюю на второе место: вторая и третья уходят вниз.
  assert.deepEqual([0, 1, 2, 3].map((i) => m.shiftFor(i, 3, 1, 100)), [0, 100, 100, 0]);
  assert.deepEqual([0, 1, 2].map((i) => m.shiftFor(i, 1, 1, 100)), [0, 0, 0]);
  // Итог перетаскивания совпадает с moveItem.
  const list = [item("a"), item("b"), item("c"), item("d")];
  assert.deepEqual(ids(m.moveItem(list, 0, m.dropIndex(mids, 0, 260))), ["b", "c", "a", "d"]);
});

test("toLocal сохраняет ключи карточек на тех же местах", () => {
  let n = 0;
  const key = () => `k${++n}`;
  const first = m.toLocal([item(1), item(2)], [], key);
  assert.deepEqual(first.map((i) => i.key), ["k1", "k2"]);
  const again = m.toLocal([item(1), item(2), item(3)], first, key);
  assert.deepEqual(again.map((i) => i.key), ["k1", "k2", "k3"]);
  const swapped = m.toLocal([item(2), item(1)], first, key);
  assert.deepEqual(swapped.map((i) => i.key), ["k4", "k5"], "другой ролик на месте — новый ключ");
});

test("signature и itemRefs: в запрос уходят только type и id", () => {
  const list = [item(1), { ...item(2), type: "cartoon_movie" }];
  assert.deepEqual(m.itemRefs(list), [
    { type: "vstudio", id: "1" },
    { type: "cartoon_movie", id: "2" },
  ]);
  assert.equal(m.signature(list, "16:9", "pad"), "16:9|pad|vstudio:1,cartoon_movie:2");
  assert.notEqual(m.signature(list, "16:9", "pad"), m.signature(list, "9:16", "pad"));
  assert.notEqual(m.signature(list, "16:9", "pad"), m.signature([...list].reverse(), "16:9", "pad"));
});

test("parseAddParam: только свои виды и чистые id; addHref — обратно", () => {
  assert.deepEqual(m.parseAddParam("cartoon_movie:12"), [{ type: "cartoon_movie", id: "12" }]);
  assert.deepEqual(m.parseAddParam("vstudio:66fb577e25374c278ef94b5d729b41c3, chat:7"), [
    { type: "vstudio", id: "66fb577e25374c278ef94b5d729b41c3" },
    { type: "chat", id: "7" },
  ]);
  assert.deepEqual(m.parseAddParam("evil:1,cartoon_movie:../x,cartoon_scene:,chat:1:2,:5"), []);
  assert.deepEqual(m.parseAddParam(null), []);
  assert.equal(m.parseAddParam("chat:1,chat:2,chat:3", 2).length, 2);
  assert.equal(m.addHref([{ type: "cartoon_movie", id: "12" }]), "/merge?add=cartoon_movie%3A12");
  assert.equal(m.addHref([]), "/merge");
  assert.deepEqual(m.parseAddParam(decodeURIComponent("cartoon_movie%3A12")), [{ type: "cartoon_movie", id: "12" }]);
});

test("статусы: что можно править и что идёт", () => {
  assert.ok(m.isEditable(null));
  for (const s of ["draft", "failed", "expired"]) assert.ok(m.isEditable(s), s);
  for (const s of ["queued", "rendering", "ready"]) assert.ok(!m.isEditable(s), s);
  assert.ok(m.isActive("queued") && m.isActive("rendering"));
  assert.ok(!m.isActive("ready") && !m.isActive(null));
  assert.ok(m.isUid("546398e0b07b470f91dc46a356fa0860"));
  assert.ok(!m.isUid("546398E0B07B470F91DC46A356FA0860") && !m.isUid("12") && !m.isUid(null));
});

test("progressShare и currentFragment", () => {
  assert.equal(m.progressShare(null), 0);
  assert.equal(m.progressShare({ stage: "queued", done: 0, total: 4 }), 0);
  assert.equal(m.progressShare({ stage: "normalizing", done: 2, total: 4 }), 0.05 + 0.425);
  assert.equal(m.progressShare({ stage: "normalizing", done: 9, total: 4 }), 0.9);
  assert.equal(m.progressShare({ stage: "joining", done: 4, total: 4 }), 0.92);
  assert.equal(m.currentFragment({ stage: "normalizing", done: 2, total: 4 }), 3);
  assert.equal(m.currentFragment({ stage: "normalizing", done: 4, total: 4 }), 4);
  assert.equal(m.currentFragment({ stage: "normalizing", done: 0, total: 0 }), 1);
});

test("shortDate, fileDate, aspectRatio", () => {
  const d = new Date(2026, 10, 5, 12, 0, 0);
  assert.equal(m.shortDate(d.toISOString()), "05.11");
  assert.equal(m.shortDate("не дата"), "");
  assert.equal(m.shortDate(null), "");
  assert.equal(m.fileDate(new Date(2026, 0, 9)), "2026-01-09");
  assert.equal(m.aspectRatio("9:16"), 9 / 16);
  assert.equal(m.aspectRatio("1:1"), 1);
  assert.equal(m.aspectRatio(null), 16 / 9);
});

test("refusalText: номер фрагмента с единицы, поле, цена, длина", () => {
  const unavailable = m.refusalText("source_unavailable", { index: 1, type: "vstudio", id: "x" });
  assert.equal(unavailable.key, "merge.err.source_unavailable");
  assert.equal(unavailable.params.n, 2);
  assert.equal(
    m.fillText(unavailable.ru, unavailable.params),
    "Фрагмент №2 недоступен: видео не найдено, удалено или ещё не готово. Уберите его из склейки.",
  );
  const long = m.refusalText("too_long", { total_s: 312, max_s: 300 });
  assert.equal(m.fillText(long.ru, long.params), "Склейка выходит длиннее 5 минут (5:12). Уберите часть фрагментов.");
  assert.equal(m.refusalText("bad_request", { field: "title" }).key, "merge.err.bad_request_title");
  assert.equal(m.refusalText("bad_request", { field: "items", index: 0 }).key, "merge.err.bad_request");
  assert.equal(m.refusalText("bad_request", { field: "zzz" }).key, "merge.err.bad_request");
  const price = m.refusalText("price_changed", { credits: 25 });
  assert.equal(m.fillText(price.ru, price.params), "Цена изменилась: теперь 25 кр. Проверьте и нажмите «Склеить» ещё раз.");
  assert.equal(m.refusalText("too_many_fragments", { max: 30 }).params.max, 30);
  // Неизвестный код — русский текст сервера; без него — общий.
  assert.deepEqual(m.refusalText("something_new", {}, "Текст сервера"), { key: "", ru: "Текст сервера", params: {} });
  assert.equal(m.refusalText("something_new").key, "merge.err.server_error");
  // Номер не пришёл — без «№undefined».
  assert.equal(m.refusalText("source_unavailable", {}, "Текст").ru, "Текст");
  assert.equal(m.refusalText("too_long", {}).key, "merge.err.server_error");
});

test("failureText: коды неудачной склейки", () => {
  const f = m.failureText("fragment_failed", 3);
  assert.equal(f.key, "merge.fail.fragment_failed");
  assert.equal(m.fillText(f.ru, f.params), "Не получилось обработать фрагмент №3 — попробуйте ещё раз или уберите его.");
  assert.equal(m.failureText("join_failed", null).key, "merge.fail.join_failed");
  assert.equal(m.failureText("fragment_failed", null, "Сервер").ru, "Сервер");
  assert.equal(m.failureText("fragment_failed", null).key, "merge.fail.failed");
  assert.equal(m.failureText("unknown_code", null, "Сервер").ru, "Сервер");
  assert.equal(m.failureText(null, null).key, "merge.fail.failed");
});

test("blockText: подсказка у выключенной кнопки", () => {
  const few = m.blockText({ code: "too_few_fragments", min: 2 });
  assert.equal(few.key, "merge.err.too_few_fragments");
  const gone = m.blockText({ code: "source_unavailable", index: 0 });
  assert.equal(gone.params.n, 1);
  const long = m.blockText({ code: "too_long", total_s: 301, max_s: 300 });
  assert.equal(long.params.total, "5:01");
});

test("тексты: подстановки только известные, у fail нет пустых", () => {
  const allowed = new Set(["n", "max", "credits", "total", "min"]);
  for (const [code, text] of Object.entries({ ...MERGE_ERROR_RU, ...MERGE_FAIL_RU })) {
    assert.ok(text.trim(), code);
    for (const mm of text.matchAll(/\{\{\s*(\w+)\s*\}\}/g)) assert.ok(allowed.has(mm[1]), `${code}: ${mm[1]}`);
  }
});

test("refusalText: минуты ожидания из wait, без них — общий текст", () => {
  assert.equal(m.waitMinutes(61), 2);
  assert.equal(m.waitMinutes(0), null);
  assert.equal(m.waitMinutes("60"), null);
  const slow = m.refusalText("upload_throttled", { wait: 3599 });
  assert.equal(m.fillText(slow.ru, slow.params), "Загрузок за час слишком много — следующую можно через 60 мин.");
  assert.equal(m.refusalText("upload_throttled").key, "merge.err.throttled");
  assert.equal(m.refusalText("copy_dropped", { n: 2 }).key, "merge.err.copy_dropped");
});

test("blockText busy: идёт другая склейка — тем же текстом, что отказ сервера", () => {
  const busy = m.blockText({ code: "busy" });
  assert.equal(busy.key, "merge.err.busy");
  assert.equal(busy.ru, "Уже идёт другая склейка. Дождитесь её окончания и запустите эту.");
  const ready = m.refusalText("too_many_ready", { max: 20 });
  assert.equal(ready.key, "merge.err.too_many_ready");
  assert.match(m.fillText(ready.ru, ready.params), /^Готовых склеек: 20 — /);
});

test("downloadName: имя файла как у сервера, дата окончания по местному времени", () => {
  const finished = new Date(2026, 9, 16, 23, 30).toISOString();
  assert.equal(m.downloadName(finished), "EsAI-merge-2026-10-16.mp4");
  assert.equal(m.downloadName(null, new Date(2026, 0, 2)), "EsAI-merge-2026-01-02.mp4");
  assert.equal(m.downloadName("не дата", new Date(2026, 0, 2)), "EsAI-merge-2026-01-02.mp4");
});

test("isAppleTouch: iPhone, iPad и iPadOS под видом Mac; Android и компьютер — нет", () => {
  assert.equal(m.isAppleTouch("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)", "iPhone", 5), true);
  assert.equal(m.isAppleTouch("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)", "MacIntel", 5), true);
  assert.equal(m.isAppleTouch("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)", "MacIntel", 0), false);
  assert.equal(m.isAppleTouch("Mozilla/5.0 (Linux; Android 14)", "Linux armv8l", 5), false);
  assert.equal(m.isAppleTouch("Mozilla/5.0 (Windows NT 10.0)", "Win32", 0), false);
});

test("appendUnique: «Показать ещё» без повторов карточек", () => {
  const card = (type, id) => ({ type, id });
  const first = [card("chat", "3"), card("chat", "2")];
  // Между загрузками появился новый ролик: страница 2 сдвинулась и повторяет «2».
  const next = m.appendUnique(first, [card("chat", "2"), card("chat", "1"), card("cartoon_scene", "2")]);
  assert.deepEqual(next.map((c) => `${c.type}:${c.id}`), ["chat:3", "chat:2", "chat:1", "cartoon_scene:2"]);
  assert.deepEqual(first.map((c) => c.id), ["3", "2"], "исходный список не меняется");
});

test("insertItem: «В конец» — главное действие, «В начало» — первым; исходный список не меняется", () => {
  const list = [item(1), item(2)];
  assert.deepEqual(ids(m.insertItem(list, item(3))), ["1", "2", "3"], "по умолчанию — в конец");
  assert.deepEqual(ids(m.insertItem(list, item(3), "end")), ["1", "2", "3"]);
  assert.deepEqual(ids(m.insertItem(list, item(3), "start")), ["3", "1", "2"]);
  assert.deepEqual(ids(m.insertItem([], item(9), "start")), ["9"], "в пустую — то же, что в конец");
  assert.deepEqual(ids(list), ["1", "2"]);
  // Порядок уходит на сервер как есть: первый в items — первый в ролике.
  const refs = m.itemRefs(m.insertItem(list, item("u", 4, { type: "upload" }), "start"));
  assert.deepEqual(refs[0], { type: "upload", id: "u" });
});

test("свои видео: не больше 3 в склейке, повторы считаются, остальные виды не ограничены", () => {
  const up = (id) => item(id, 4, { type: "upload" });
  assert.equal(m.uploadCount([up("a"), item(1), up("a")]), 2);
  const three = [up("a"), up("b"), up("a"), item(1)];
  assert.deepEqual(m.addRefusal(three, up("c"), LIMITS), { code: "too_many_uploads", max: 3 });
  assert.equal(m.addRefusal(three, item(2), LIMITS), null, "чужой вид — можно");
  assert.equal(m.addRefusal([up("a"), up("b")], up("c"), LIMITS), null);
  assert.deepEqual(m.addRefusal([up("a")], up("b"), LIMITS, 1), { code: "too_many_uploads", max: 1 }, "предел с сервера");
  // Предел фрагментов проверяется раньше — как у сервера.
  const thirty = Array.from({ length: 30 }, (_, i) => item(i, 1));
  assert.equal(m.addRefusal(thirty, up("z"), LIMITS).code, "too_many_fragments");
  assert.deepEqual(m.renderBlock([up("a"), up("b"), up("c"), up("d")], LIMITS), { code: "too_many_uploads", max: 3 });
  assert.equal(m.renderBlock([up("a"), up("b"), up("c")], LIMITS), null);
  const block = m.blockText({ code: "too_many_uploads", max: 3 });
  assert.equal(block.key, "merge.err.too_many_uploads");
  assert.equal(m.fillText(block.ru, block.params), "В одной склейке — не больше 3 своих видео.");
  assert.equal(m.refusalText("too_many_uploads").params.max, 3, "max не пришёл — 3");
  assert.ok(m.TABS.includes("upload") && m.isTab("upload"));
});

test("отказы загрузки: тексты сервера (CONTRACT_M §9.6), поле file", () => {
  const server = {
    upload_too_big: "Файл больше 90 МБ. Сожмите или обрежьте видео и загрузите снова.",
    upload_bad_type: "Подходят только видео MP4, MOV или WebM.",
    upload_unreadable: "Файл не читается — возможно, он повреждён. Выберите другое видео.",
    upload_no_video: "В файле нет подходящего видео: нужна одна видеодорожка H.264, HEVC, VP8, VP9, AV1 или MPEG-4.",
    upload_too_short: "Видео короче полсекунды — такое не склеить.",
    upload_too_long: "Видео длиннее 60 секунд. Обрежьте его и загрузите снова.",
    upload_resolution: "Кадр больше 4096 точек по стороне. Уменьшите разрешение и загрузите снова.",
    upload_quota:
      "Место для своих видео занято: хранится до 10 файлов и до 600 МБ. Удалите старые в «Моих файлах» и загрузите снова.",
    upload_unavailable: "Загрузка сейчас недоступна: на сервере не хватает места. Попробуйте позже.",
    upload_not_found: "Видео не найдено.",
    upload_in_use: "Это видео сейчас склеивается — удалить его можно после окончания.",
    upload_frame_rate:
      "В видео больше 120 кадров в секунду — такое не склеить. Сохраните его с частотой 30 или 60 кадров и загрузите снова.",
    upload_busy: "Уже загружается другое видео. Дождитесь окончания и загрузите следующее.",
  };
  for (const [code, text] of Object.entries(server)) {
    const spec = m.refusalText(code, {}, "текст сервера");
    assert.equal(spec.key, `merge.err.${code}`, code);
    assert.equal(spec.ru, text, code);
  }
  const noFile = m.refusalText("bad_request", { field: "file" });
  assert.equal(noFile.key, "merge.err.bad_request_file");
  assert.equal(noFile.ru, "Выберите видео для загрузки.");
});

test("saveRetryDelay: повторяем только проходящие сбои и не бесконечно", () => {
  assert.equal(m.transientSaveError("network"), true);
  assert.equal(m.transientSaveError("source_unavailable"), false);
  assert.equal(m.saveRetryDelay("network", 0), 3000);
  assert.equal(m.saveRetryDelay("server_error", 1), 10000);
  assert.equal(m.saveRetryDelay("throttled", 0, 42), 42000, "сервер сказал, сколько ждать");
  assert.equal(m.saveRetryDelay("throttled", 2, "x"), 30000);
  assert.equal(m.saveRetryDelay("network", m.SAVE_RETRY_MS.length), 0);
  assert.equal(m.saveRetryDelay("too_long", 0), 0);
  assert.equal(m.saveRetryDelay("source_unavailable", 0), 0);
});

test("склейку не удалили: текст у её строки — тот же, что у сервера; уже нет — не отказ (MA_FIX4)", () => {
  const busy = m.deleteRefusal({ code: "audio_busy", data: {}, message: "Звук для этой склейки ещё делается — дождитесь его." });
  assert.deepEqual(busy, { key: "merge.err.audio_busy", ru: MERGE_ERROR_RU.audio_busy, params: {} });
  assert.equal(busy.ru, "Звук для этой склейки ещё делается — дождитесь его.");
  assert.equal(m.deleteRefusal({ code: "render_in_progress", data: {}, message: "" }).key, "merge.err.render_in_progress");
  assert.equal(m.deleteRefusal({ code: "project_not_found", data: {}, message: "Склейка не найдена." }), null);
  assert.equal(m.deleteRefusal({ code: "network", data: {}, message: "" }).key, "merge.err.network");
  // Незнакомый код — русский текст сервера, а не пустая строка.
  assert.deepEqual(m.deleteRefusal({ code: "brand_new", data: {}, message: "Новый отказ." }), { key: "", ru: "Новый отказ.", params: {} });
});

test("отказ удаления у строки снимается, когда сервер показал, что причины больше нет (MA_FIX5, V4 money W1)", () => {
  const X = "a".repeat(32);
  const Y = "b".repeat(32);
  const busy = { id: X, code: "audio_busy" };
  // Звук ещё делается — отказ правда; доделался — снят.
  assert.equal(m.deleteRefusalStale(busy, X, { status: "draft", pending: true }), false);
  assert.equal(m.deleteRefusalStale(busy, X, { status: "draft", pending: false }), true);
  assert.equal(m.deleteRefusalStale(busy, X, { pending: false }), true, "ответ про звук без склейки (опрос звука)");
  // Старый сервер без audio в ответе — не знаем, отказ остаётся.
  assert.equal(m.deleteRefusalStale(busy, X, { status: "draft", pending: undefined }), false);
  assert.equal(m.deleteRefusalStale(busy, X, { status: "draft" }), false);
  // Ответ про другую склейку или отказа нет.
  assert.equal(m.deleteRefusalStale(busy, Y, { status: "draft", pending: false }), false);
  assert.equal(m.deleteRefusalStale(null, X, { status: "draft", pending: false }), false);
  // «Идёт» — пока склейка в очереди или склеивается.
  const running = { id: X, code: "render_in_progress" };
  assert.equal(m.deleteRefusalStale(running, X, { status: "rendering", pending: false }), false);
  assert.equal(m.deleteRefusalStale(running, X, { status: "queued" }), false);
  assert.equal(m.deleteRefusalStale(running, X, { status: "ready" }), true);
  assert.equal(m.deleteRefusalStale(running, X, { pending: false }), false, "статус не пришёл");
  // Связь, лимит — до ✕ или следующей попытки.
  for (const code of ["network", "throttled", "server_error"]) {
    assert.equal(m.deleteRefusalStale({ id: X, code }, X, { status: "draft", pending: false }), false, code);
  }
});

test("открытую склейку после отказа удаления открываем снова, только если ничего другого не открыли (MA_FIX5, V4 frontend W2)", () => {
  const ok = { closedAt: 7, epoch: 7, openId: null, dirty: false };
  assert.equal(m.reopenAfterRefusal(ok), true);
  // «Новая склейка» или другая склейка за время запроса — эпоха сдвинулась.
  assert.equal(m.reopenAfterRefusal({ ...ok, epoch: 8 }), false);
  // В пустом редакторе добавили ролик, и он уже сохранился новой склейкой.
  assert.equal(m.reopenAfterRefusal({ ...ok, openId: "c".repeat(32) }), false);
  // Добавили, но ещё в паузе автосохранения.
  assert.equal(m.reopenAfterRefusal({ ...ok, dirty: true }), false);
  // Удаляли не открытую склейку — возвращать нечего.
  assert.equal(m.reopenAfterRefusal({ ...ok, closedAt: -1, epoch: -1 }), false);
});
