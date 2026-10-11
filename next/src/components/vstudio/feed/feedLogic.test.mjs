// Лента видеостудии: чистая логика (feed/feedLogic.ts, feed/examples.ts).
// Запуск (Node 22.6+):  node --experimental-strip-types --test src/components/vstudio/feed/*.test.mjs
import "../../../lib/vstudio/nodeTsHooks.mjs";
import { test } from "node:test";
import assert from "node:assert/strict";

const L = await import("./feedLogic.ts");
const X = await import("./examples.ts");

const U = (n) => n.toString(16).padStart(32, "0");

function asset(n, over = {}) {
  return {
    uid: U(n),
    kind: "image",
    source: "upload",
    status: "ready",
    url: `/media/vstudio/1/${U(n)}.jpg`,
    thumb_url: `/media/vstudio/1/${U(n)}_t.jpg`,
    width: 1024,
    height: 768,
    duration_s: null,
    label: "",
    flags: {},
    error_code: null,
    created_at: "2026-09-24T10:00:00Z",
    ...over,
  };
}

function take(n, over = {}) {
  return {
    uid: U(0x1000 + n),
    shot: U(0x500),
    kind: "video",
    status: "running",
    stage: "",
    mode: "t2v",
    charge_state: "reserved",
    credits: { quoted: 100, reserved: 100, charged: 0 },
    effective: { duration: 5, resolution: "720p", aspect_ratio: "16:9", generate_audio: true },
    warnings: [],
    dropped: [],
    result: null,
    error: null,
    eta_s: 120,
    elapsed_s: 10,
    queue_position: null,
    created_at: `2026-09-24T10:0${n}:00Z`,
    submitted_at: null,
    finished_at: null,
    ...over,
  };
}

function shot(over = {}) {
  return {
    uid: U(0x500),
    project: U(0x600),
    kind: "video",
    origin: "composer",
    model: { id: "bytedance/seedance-2.0", name: "Seedance 2.0" },
    prompt_doc: { v: 1, blocks: [[{ t: "text", v: "кот" }]] },
    prompt_text: "кот",
    params: { duration: 5, resolution: "720p", aspect_ratio: "9:16", generate_audio: true },
    inputs: [],
    forked_from: null,
    created_at: "2026-09-24T10:00:00Z",
    takes: [],
    ...over,
  };
}

/* ---------- дубли ---------- */

test("открытые статусы и uid для опроса — без повторов и закрытых", () => {
  assert.equal(L.isOpenStatus("queued"), true);
  assert.equal(L.isOpenStatus("saving"), true);
  assert.equal(L.isOpenStatus("done"), false);
  assert.equal(L.isOpenStatus("lost"), false);
  const list = [take(1), take(2, { status: "done" }), take(3, { status: "queued" }), take(1)];
  assert.deepEqual(L.openTakeUids(list), [U(0x1001), U(0x1003)]);
});

test("дубли кадра: запись стора новее той, что пришла с кадром; порядок по времени", () => {
  const old = take(1, { status: "running" });
  const fresh = { ...old, status: "done" };
  const retry = take(2, { status: "queued" });
  const s = shot({ takes: [old] });
  const merged = L.shotTakes(s, [retry, fresh]);
  assert.deepEqual(
    merged.map((t) => [t.uid, t.status]),
    [
      [U(0x1001), "done"],
      [U(0x1002), "queued"],
    ],
  );
  // Чужой дубль в списке стора (другой кадр) не подмешивается.
  assert.equal(L.shotTakes(s, [take(3, { shot: U(0x999) })]).length, 1);
});

test("index по кадрам и поэлементное сравнение для memo", () => {
  const a = take(1);
  const b = take(2, { shot: U(0x777) });
  const idx = L.indexTakesByShot([a, b]);
  assert.deepEqual(idx.get(U(0x500)), [a]);
  assert.deepEqual(idx.get(U(0x777)), [b]);
  assert.equal(L.sameItems([a, b], [a, b]), true);
  assert.equal(L.sameItems([a, b], [a, { ...b }]), false);
  assert.equal(L.sameItems([a], [a, b]), false);
});

test("карусель: выбранный дубль, иначе последний", () => {
  const list = [take(1), take(2), take(3)];
  assert.equal(L.pickTakeIndex(list, null), 2);
  assert.equal(L.pickTakeIndex(list, U(0x1001)), 0);
  assert.equal(L.pickTakeIndex(list, U(0xdead)), 2);
  assert.equal(L.pickTakeIndex([], null), -1);
});

test("«Повторить» нельзя, пока дубль идёт, и без модели", () => {
  const model = { id: "bytedance/seedance-2.0" };
  assert.equal(L.retryBlock(shot(), [take(1, { status: "saving" })], model), "open");
  assert.equal(L.retryBlock(shot(), [take(1, { status: "failed" })], model), null);
  // Каталог не загружен (undefined) — не блокируем; модели нет (null) — блок.
  assert.equal(L.retryBlock(shot(), [take(1, { status: "done" })], undefined), null);
  assert.equal(L.retryBlock(shot(), [take(1, { status: "done" })], null), "model");
  assert.equal(L.retryBlock(shot({ model: null }), [], model), "model");
});

test("findModel: undefined — каталог не пришёл, null — модели нет", () => {
  const models = { video: [{ id: "a" }], image: [{ id: "b" }] };
  assert.equal(L.findModel(null, "video", "a"), undefined);
  assert.equal(L.findModel(models, "video", "a").id, "a");
  assert.equal(L.findModel(models, "video", "b"), null);
  assert.equal(L.findModel(models, "image", "b").id, "b");
  assert.equal(L.findModel(models, "video", null), null);
});

/* ---------- статус и время ---------- */

test("подписи статусов §9.6", () => {
  assert.equal(L.statusPhrase(take(1, { status: "queued", queue_position: 0 })).key, "run.status.queued");
  const pos = L.statusPhrase(take(1, { status: "queued", queue_position: 2 }));
  assert.equal(pos.key, "run.status.queuedPos");
  assert.equal(pos.params.n, 3); // позиция 2 — перед вами двое, вы третий
  assert.equal(L.statusPhrase(take(1, { status: "submitting", mode: "t2v" })).key, "run.status.submitting");
  assert.equal(L.statusPhrase(take(1, { status: "submitting", mode: "r2v" })).key, "run.status.submittingRefs");
  assert.equal(L.statusPhrase(take(1, { status: "running" })).ru, "Снимается");
  assert.equal(L.statusPhrase(take(1, { status: "running", kind: "image" })).key, "run.status.runningImage");
  assert.equal(L.statusPhrase(take(1, { status: "saving" })).ru, "Сохраняем…");
  assert.equal(L.statusPhrase(take(1, { status: "done", kind: "image" })).key, "run.status.doneImage");
});

test("подпись lost — только итог: причину называет error.code, а не статус", () => {
  // lost закрывают четыре кода; подпись статуса не должна выбирать за них причину.
  const codes = ["submit_unknown", "provider_timeout", "provider_unreachable", "save_failed"];
  const phrases = codes.map((code) => L.statusPhrase(take(1, { status: "lost", error: { code, message: "", input: null } })));
  for (const p of phrases) assert.deepEqual(p, { key: "run.status.lost", ru: "Не выдано" });
  assert.doesNotMatch(phrases[0].ru, /запуск|сохран|модел/i);
});

test("секундомер и ETA", () => {
  assert.equal(L.formatClock(7), "0:07");
  assert.equal(L.formatClock(84), "1:24");
  assert.equal(L.formatClock(3723), "1:02:03");
  assert.equal(L.formatClock(-5), "0:00");
  assert.equal(L.formatClock(NaN), "0:00");
  assert.deepEqual(L.etaPhrase(150), { key: "run.time.min", ru: "{{n}} мин", params: { n: 3 } });
  assert.deepEqual(L.etaPhrase(40).params, { n: 40 });
  assert.deepEqual(L.etaPhrase(3).params, { n: 5 });
  assert.equal(L.etaPhrase(0), null);
  assert.equal(L.etaPhrase(null), null);
});

test("«дольше обычного» — после 1.5×ETA; полоса никогда не 100 %", () => {
  assert.equal(L.isSlow(180, 120), false);
  assert.equal(L.isSlow(181, 120), true);
  assert.equal(L.isSlow(500, 0), false);
  assert.equal(L.progressShare(0, 100), 0);
  assert.equal(L.progressShare(50, 100), 0.45);
  assert.ok(Math.abs(L.progressShare(100, 100) - 0.9) < 1e-9);
  assert.ok(L.progressShare(10_000, 100) < 0.98);
  assert.ok(L.progressShare(300, 100) > L.progressShare(200, 100));
  assert.equal(L.progressShare(10, 0), null);
});

test("секунды дубля считаются от серверного elapsed_s", () => {
  assert.equal(L.liveElapsed(30, 1000, 4000), 33);
  // Опоры ещё нет (гидратация) — только серверное значение.
  assert.equal(L.liveElapsed(30, 0, 4000), 30);
  // Часы «назад» — не уходим в минус.
  assert.equal(L.liveElapsed(30, 5000, 4000), 30);
});

test("тосты: готово, не получилось; отмена молча", () => {
  assert.equal(L.settledToast(take(1, { status: "done" })).phrase.key, "toast.videoDone");
  assert.equal(L.settledToast(take(1, { status: "done", kind: "image" })).phrase.ru, "Картинка готова");
  const f = L.settledToast(take(1, { status: "failed" }));
  assert.equal(f.tone, "error");
  assert.equal(f.phrase.key, "toast.failed");
  // lost — не «не получилось»: ролик мог быть снят и ждать довоза.
  const lost = L.settledToast(take(1, { status: "lost" }));
  assert.deepEqual([lost.tone, lost.phrase.key, lost.id], ["error", "toast.lost", `vs-take-${U(0x1001)}-lost`]);
  assert.match(lost.phrase.ru, /^Не выдано — кредиты не списаны/);
  assert.equal(L.settledToast(take(1, { status: "canceled" })), null);
  assert.equal(L.settledToast(take(1, { status: "running" })), null);
});

/* ---------- промпт с чипами ---------- */

test("чипы берут метку из inputs кадра: ушло / не учтено / удалено", () => {
  const a = asset(1);
  const b = asset(2);
  const f = asset(3);
  const s = shot({
    prompt_doc: {
      v: 1,
      blocks: [
        [{ t: "ref", asset: a.uid }, { t: "text", v: " идёт к " }, { t: "ref", asset: b.uid }],
        [{ t: "ref", asset: f.uid }, { t: "ref", asset: U(0xbad) }],
      ],
    },
    inputs: [
      { asset: a, slot: "reference", position: 0, role: "героиня", included: true, label: "Image 1" },
      { asset: b, slot: "reference", position: 1, role: "", included: false, label: null },
      { asset: f, slot: "first_frame", position: 0, role: "", included: true, label: "first_frame" },
    ],
  });
  const [first, second] = L.promptSegments(s);
  assert.equal(first.length, 3);
  assert.deepEqual(
    [first[0].state, first[0].n, first[0].role, first[0].thumb],
    ["ok", 1, "героиня", a.thumb_url],
  );
  assert.deepEqual([first[1].kind, first[1].text], ["text", " идёт к "]);
  assert.deepEqual([first[2].state, first[2].n], ["excluded", null]);
  assert.deepEqual([second[0].slot, second[0].state, second[0].n], ["first_frame", "ok", null]);
  assert.equal(second[1].state, "missing");
});

test("пустой документ — показываем prompt_text целиком", () => {
  const s = shot({ prompt_doc: { v: 1, blocks: [[]] }, prompt_text: "@Image 1 идёт по крыше" });
  assert.deepEqual(L.promptSegments(s), [[{ kind: "text", text: "@Image 1 идёт по крыше" }]]);
  assert.equal(L.labelNumber("Image 12"), 12);
  assert.equal(L.labelNumber("first_frame"), null);
  assert.equal(L.labelNumber(null), null);
});

test("длинный промпт сворачивается (но не режется)", () => {
  assert.equal(L.isLongPrompt("коротко"), false);
  assert.equal(L.isLongPrompt("x".repeat(321)), true);
  assert.equal(L.isLongPrompt("a\nb\nc\nd\ne\nf"), true);
  assert.equal(L.isLongPrompt(""), false);
});

/* ---------- входы ---------- */

test("входы: референсы по порядку, потом кадры; «не учтено» и виноватый", () => {
  const a = asset(1);
  const b = asset(2);
  const f = asset(3);
  const dup = asset(4);
  const inputs = [
    { asset: f, slot: "first_frame", position: 0, role: "", included: true, label: "first_frame" },
    { asset: b, slot: "reference", position: 1, role: "", included: false, label: null },
    { asset: a, slot: "reference", position: 0, role: "кот", included: true, label: "Image 1" },
    { asset: dup, slot: "last_frame", position: 0, role: "", included: true, label: "last_frame" },
  ];
  const dropped = [
    { asset: b.uid, slot: "reference", reason: "excluded_by_user" },
    { asset: dup.uid, slot: "last_frame", reason: "duplicate_frame" },
  ];
  const rows = L.inputRows(inputs, dropped, a.uid);
  assert.deepEqual(
    rows.map((r) => [r.input.slot, r.input.asset.uid, r.n, r.excluded, r.reason, r.culprit]),
    [
      ["reference", a.uid, 1, false, null, true],
      ["reference", b.uid, null, true, "excluded_by_user", false],
      ["first_frame", f.uid, null, false, null, false],
      ["last_frame", dup.uid, null, true, "duplicate_frame", false],
    ],
  );
  // Выключенный человеком, но без записи в dropped — всё равно «не учтено».
  const solo = L.inputRows([{ ...inputs[1] }], [], null);
  assert.equal(solo[0].reason, "excluded_by_user");
  assert.deepEqual(L.inputRows(null, null, null), []);
});

/* ---------- сводка и результат ---------- */

test("сводка параметров: итог дубля важнее запрошенного", () => {
  const s = shot();
  const sum = L.paramsSummary(s, { effective: { duration: 8, resolution: "720p", aspect_ratio: "16:9" } });
  assert.deepEqual(sum, { model: "Seedance 2.0", aspect: "16:9", duration: 8, resolution: "720p", audio: true });
  const img = L.paramsSummary(shot({ kind: "image", params: { aspect_ratio: "auto" } }), null);
  assert.deepEqual(img, { model: "Seedance 2.0", aspect: "auto", duration: null, resolution: null, audio: null });
  assert.equal(L.paramsSummary(shot({ model: null }), null).model, null);
});

test("рамка кадра и имя файла", () => {
  assert.equal(L.parseAspect("9:16"), 9 / 16);
  assert.equal(L.parseAspect("21/9"), 21 / 9);
  assert.equal(L.parseAspect("auto"), null);
  assert.equal(L.mediaRatio({ width: 720, height: 1280 }, "16:9", "video"), 720 / 1280);
  assert.equal(L.mediaRatio(null, "9:16", "video"), 9 / 16);
  assert.equal(L.mediaRatio(null, "auto", "image"), 1);
  assert.equal(L.mediaRatio(null, null, "video"), 16 / 9);
  assert.equal(
    L.mediaFilename({ uid: "abcdef0123456789", kind: "video", url: "/media/vstudio/1/x.mp4?v=2" }),
    "esai-video-abcdef01.mp4",
  );
  assert.equal(L.mediaFilename({ uid: "0123456789ab", kind: "image", url: "/media/x.png" }), "esai-image-01234567.png");
  assert.equal(L.mediaFilename({ uid: "0123456789ab", kind: "image", url: null }), "esai-image-01234567.jpg");
});

test("прокрутка: «внизу» и поиск кадра по дублю", () => {
  assert.equal(L.isNearBottom({ scrollTop: 840, clientHeight: 800, scrollHeight: 1800 }), true);
  assert.equal(L.isNearBottom({ scrollTop: 100, clientHeight: 800, scrollHeight: 1800 }), false);
  assert.equal(L.shotDomId("abc"), "vs-shot-abc");
  const t1 = take(1);
  const takes = new Map([[t1.uid, t1]]);
  const s2 = shot({ uid: U(0x502), takes: [take(9, { shot: U(0x502) })] });
  const shots = new Map([[s2.uid, s2]]);
  assert.equal(L.shotOfTake(t1.uid, takes, shots), U(0x500));
  assert.equal(L.shotOfTake(U(0x1009), takes, shots), U(0x502));
  assert.equal(L.shotOfTake(U(0xffff), takes, shots), null);
});

test("панель запроса выросла: кто стоял на самом низу ленты, остаётся внизу; остальных не двигаем", () => {
  // Колонка была 800 px, стала 560 (поле запроса развернули): до этого лента стояла у самого низа.
  assert.equal(L.keepsBottom({ scrollTop: 1000, clientHeight: 560, scrollHeight: 1800 }, 800), true);
  // «На самом низу» считается по старой высоте, с запасом на дробные пиксели прокрутки — не больше.
  assert.equal(L.keepsBottom({ scrollTop: 1000 - L.PINNED_BOTTOM_PX, clientHeight: 560, scrollHeight: 1800 }, 800), true);
  assert.equal(L.keepsBottom({ scrollTop: 1000 - L.PINNED_BOTTOM_PX - 1, clientHeight: 560, scrollHeight: 1800 }, 800), false);
  // Отлистал на 100 px вверх — посмотреть начало последнего ролика. Для автопрокрутки к готовому
  // результату это ещё «внизу», но докрутка сдвинула бы ленту разом на эти 100 px: не двигаем.
  const up100 = { scrollTop: 900, clientHeight: 560, scrollHeight: 1800 };
  assert.equal(L.keepsBottom(up100, 800), false);
  // Прокрутка у него та же, а «внизу» ли он, зависит от высоты колонки: панель выросла — до низа
  // уже 340 px; свернулась — снова 100. Поэтому лента пересчитывает это при каждой смене высоты.
  assert.equal(L.isNearBottom(up100), false);
  assert.equal(L.isNearBottom({ ...up100, clientHeight: 800 }), true);
  // Человек листает старые кадры — панель растёт поверх низа ленты, а то, на что он смотрит, стоит на месте.
  assert.equal(L.keepsBottom({ scrollTop: 100, clientHeight: 560, scrollHeight: 1800 }, 800), false);
  // Ленту не прокручивали (один кадр, всё помещалось): верх остаётся на виду.
  assert.equal(L.keepsBottom({ scrollTop: 0, clientHeight: 560, scrollHeight: 700 }, 800), false);
  // Колонка выросла (поле свернули) или не изменилась — низ браузер держит сам.
  assert.equal(L.keepsBottom({ scrollTop: 1000, clientHeight: 800, scrollHeight: 1800 }, 560), false);
  assert.equal(L.keepsBottom({ scrollTop: 1000, clientHeight: 800, scrollHeight: 1800 }, 800), false);
  // Первый замер: прежней высоты ещё нет.
  assert.equal(L.keepsBottom({ scrollTop: 1000, clientHeight: 800, scrollHeight: 1800 }, 0), false);
});

/* ---------- примеры ---------- */

test("примеры: 4 штуки, один сценарий — одна сцена, текст → prompt_doc", () => {
  assert.equal(X.VS_EXAMPLES.length, 4);
  assert.equal(new Set(X.VS_EXAMPLES.map((e) => e.id)).size, 4);
  assert.ok(X.VS_EXAMPLES.some((e) => e.kind === "image"));
  for (const e of X.VS_EXAMPLES) {
    // Короткие: «до ~150 слов» Seedance с запасом.
    assert.ok(e.prompt.split(/\s+/).length < 60, e.id);
    assert.ok(e.params.aspect_ratio);
  }
  assert.deepEqual(X.exampleDoc("раз\n\nдва"), {
    v: 1,
    blocks: [[{ t: "text", v: "раз" }], [], [{ t: "text", v: "два" }]],
  });
  assert.deepEqual(X.exampleDoc("a\r\nb").blocks.length, 2);
});

test("сценарий ложится в пустой запрос и поверх нетронутой заготовки, свой текст не затирает", () => {
  const starters = ["Кино-сцена: [кто] в [где].", "Постер: [сюжет].\nВторая строка."];
  const typed = (v) => ({ v: 1, blocks: [[{ t: "text", v }]] });
  // Пусто (и одни пробелы) — можно.
  assert.equal(X.starterReplaceable(null, starters), true);
  assert.equal(X.starterReplaceable({ v: 1, blocks: [[]] }, starters), true);
  assert.equal(X.starterReplaceable(typed("  "), starters), true);
  // В запросе стоит заготовка, как её положил чип, — другой чип её заменит.
  assert.equal(X.starterReplaceable(X.exampleDoc(starters[0]), starters), true);
  assert.equal(X.starterReplaceable(X.exampleDoc(starters[1]), starters), true);
  // Редактор мог порезать тот же текст на узлы и добавить пустой абзац в конце.
  assert.equal(
    X.starterReplaceable({ v: 1, blocks: [[{ t: "text", v: "Кино-сцена: " }, { t: "text", v: "[кто] в [где]." }], []] }, starters),
    true,
  );
  // Заготовку поправили под себя — это уже текст человека.
  assert.equal(X.starterReplaceable(typed("Кино-сцена: рыбак в лодке."), starters), false);
  assert.equal(X.starterReplaceable(typed("мой сценарий"), starters), false);
  // Тег материала — тоже своё, даже без единой буквы и рядом с заготовкой.
  const ref = { t: "ref", asset: "0123456789abcdef0123456789abcdef" };
  assert.equal(X.starterReplaceable({ v: 1, blocks: [[ref]] }, starters), false);
  assert.equal(X.starterReplaceable({ v: 1, blocks: [[{ t: "text", v: starters[0] }, ref]] }, starters), false);
});

test("пример не ставит пропорцию, которой нет у модели (иначе invalid_param)", () => {
  const m = (id, aspects) => ({ id, caps: { aspect_ratios: aspects } });
  const models = {
    video: [m("v1", ["16:9", "9:16"]), m("v2", ["16:9"])],
    image: [m("i1", ["1:1", "3:4"]), m("i2", ["1:1"])],
  };
  // Тот же вид: смотрим на выбранную модель.
  assert.equal(L.exampleAspect("9:16", models, "video", "v1"), "9:16");
  assert.equal(L.exampleAspect("9:16", models, "video", "v2"), null);
  // Другой вид (модель выберет редьюсер) — только если умеют все модели вида.
  assert.equal(L.exampleAspect("16:9", models, "video", null), "16:9");
  assert.equal(L.exampleAspect("3:4", models, "image", null), null);
  assert.equal(L.exampleAspect("1:1", models, "image", null), "1:1");
  // Каталог не пришёл или пропорции нет — не трогаем параметры.
  assert.equal(L.exampleAspect("16:9", null, "video", "v1"), null);
  assert.equal(L.exampleAspect(undefined, models, "video", "v1"), null);
  assert.equal(L.COMPOSER_FILLED_EVENT, "vstudio:composer-filled");
});

test("resultScrollTop: высокий результат встаёт верхом, невысокий — лента идёт к низу", () => {
  const m = { clientHeight: 555, scrollHeight: 2000 };
  // Карточка помещается целиком — к самому низу, как раньше.
  assert.equal(L.resultScrollTop(1500, 500, m), 2000 - 555);
  // Не помещается — её верх с зазором, чтобы ролик был виден с начала.
  assert.equal(L.resultScrollTop(1100, 900, m), 1100 - L.RESULT_TOP_GAP_PX);
  // Граница: карточка плюс зазор ровно в высоту колонки — ещё «помещается».
  assert.equal(L.resultScrollTop(1445, 555 - L.RESULT_TOP_GAP_PX, m), 2000 - 555);
  assert.equal(L.resultScrollTop(1444, 556 - L.RESULT_TOP_GAP_PX, m), 1444 - L.RESULT_TOP_GAP_PX);
  // Дальше низа и выше нуля не уезжаем.
  assert.equal(L.resultScrollTop(1900, 900, m), 2000 - 555);
  assert.equal(L.resultScrollTop(5, 900, m), 0);
  // Лента короче колонки — крутить некуда.
  assert.equal(L.resultScrollTop(0, 900, { clientHeight: 800, scrollHeight: 600 }), 0);
});
