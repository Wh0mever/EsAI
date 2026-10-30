// Админка, «Возвраты»: разбор отчёта, формат чисел и дат, шкала графика, подложка когорт (retention.ts).
// Запуск (Node 22.6+):  node --experimental-strip-types --test src/app/admin-new/retention/retention.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  COHORT_WEEKS,
  DIRECTIONS_NOTE,
  barAt,
  barTotal,
  chartScale,
  cohortCellTitle,
  historyWarning,
  cohortShade,
  edgeAlign,
  errorText,
  fmtCompact,
  fmtDayFull,
  fmtDayShort,
  fmtDayWeekday,
  fmtNum,
  fmtPct,
  fmtPerUser,
  fmtTime,
  isoDay,
  methodNote,
  parseRetention,
  perUser,
  plural,
  retentionPath,
  shadeBackground,
  share,
  tickIndexes,
  toPeriod,
  windowNote,
  windowOf,
  PEOPLE,
} from "./retention.ts";

// Пробелы ICU (разряды, даты) бывают неразрывными — сравниваем по смыслу.
const sp = (s) => s.replace(/\s/g, " ");

// Ответ в том виде, как его описывает F29_RETENTION_SPEC («API»).
const fullReport = () => ({
  generated_at: "2026-10-28T19:05:00+06:00",
  today: "2026-10-28",
  days: 30,
  exact_since: "2026-10-28",
  history_since: "2026-02-26",
  users_total: 2437,
  kpi: {
    dau: 41,
    wau: 230,
    mau: 640,
    stickiness: 7.4,
    new: 300,
    active: 640,
    returning: 410,
    returning_share: 64.1,
    returned_ever_share: 38.2,
    returned_ever: 931,
  },
  returned_within: [
    { days: 1, base: 2400, returned: 300, share: 12.5 },
    { days: 7, base: 2300, returned: 520, share: 22.6 },
    { days: 30, base: 2100, returned: 700, share: 33.3 },
  ],
  daily: [
    { date: "2026-10-27", active: 30, new: 10, returning: 20 },
    { date: "2026-10-28", active: 41, new: 11, returning: 30 },
  ],
  cohorts: [
    {
      week_start: "2026-10-26",
      size: 50,
      weeks: Array.from({ length: 8 }, (_, i) => ({ k: i + 1, share: null, eligible: 0, returned: 0 })),
    },
    {
      week_start: "2026-10-13",
      size: 120,
      weeks: Array.from({ length: 8 }, (_, i) =>
        i < 2 ? { k: i + 1, share: 20 - i * 5, eligible: 120, returned: 24 - i * 6 } : { k: i + 1, share: null, eligible: 0, returned: 0 }
      ),
    },
  ],
  payers: { paying: 180, repeat: 45, repeat_share: 25 },
});

test("retentionPath / toPeriod: только 30 и 90, остальное — 30, как на сервере", () => {
  assert.equal(retentionPath(30), "manage/retention/?days=30");
  assert.equal(retentionPath(90), "manage/retention/?days=90");
  assert.equal(toPeriod(90), 90);
  assert.equal(toPeriod("90"), 90);
  assert.equal(toPeriod(7), 30);
  assert.equal(toPeriod(undefined), 30);
  assert.equal(toPeriod("abc"), 30);
});

test("parseRetention: полный ответ по спецификации разбирается без потерь", () => {
  const r = parseRetention(fullReport());
  assert.ok(r);
  assert.equal(r.generatedAt, "2026-10-28T19:05:00+06:00");
  assert.equal(r.today, "2026-10-28");
  assert.equal(r.days, 30);
  assert.equal(r.exactSince, "2026-10-28");
  assert.equal(r.historySince, "2026-02-26");
  assert.equal(r.usersTotal, 2437);
  assert.deepEqual(r.kpi, {
    dau: 41,
    wau: 230,
    mau: 640,
    stickiness: 7.4,
    new: 300,
    active: 640,
    returning: 410,
    returningShare: 64.1,
    returnedEverShare: 38.2,
    returnedEver: 931,
  });
  assert.deepEqual(
    r.returnedWithin.map((w) => [w.days, w.base, w.returned, w.share]),
    [
      [1, 2400, 300, 12.5],
      [7, 2300, 520, 22.6],
      [30, 2100, 700, 33.3],
    ]
  );
  assert.deepEqual(r.daily[1], { date: "2026-10-28", active: 41, new: 11, returning: 30 });
  assert.equal(r.cohorts.length, 2);
  assert.equal(r.cohorts[0].weekStart, "2026-10-26");
  assert.equal(r.cohorts[1].weeks.length, COHORT_WEEKS);
  assert.deepEqual(r.cohorts[1].weeks[0], { k: 1, share: 20, eligible: 120, returned: 24 });
  assert.equal(r.cohorts[1].weeks[2].share, null);
  assert.deepEqual(r.payers, { paying: 180, repeat: 45, repeatShare: 25 });
});

test("parseRetention: не объект — null (страница покажет ошибку, а не пустой отчёт)", () => {
  assert.equal(parseRetention(null), null);
  assert.equal(parseRetention(undefined), null);
  assert.equal(parseRetention("<html>502 Bad Gateway</html>"), null);
  assert.equal(parseRetention([fullReport()]), null);
  assert.equal(parseRetention(42), null);
});

test("parseRetention: пустой объект (старый/недописанный сервер) — безопасные пустые значения", () => {
  const r = parseRetention({});
  assert.ok(r);
  assert.equal(r.days, 30);
  assert.equal(r.today, null);
  assert.equal(r.exactSince, null);
  assert.equal(r.generatedAt, null);
  assert.equal(r.usersTotal, 0);
  assert.equal(r.kpi.dau, 0);
  // Доли без данных — null («—»), а не 0%: ноль соврал бы, что никто не вернулся.
  assert.equal(r.kpi.stickiness, null);
  assert.equal(r.kpi.returningShare, null);
  assert.deepEqual(
    r.returnedWithin.map((w) => [w.days, w.share]),
    [
      [1, null],
      [7, null],
      [30, null],
    ]
  );
  assert.deepEqual(r.daily, []);
  assert.deepEqual(r.cohorts, []);
  assert.deepEqual(r.payers, { paying: 0, repeat: 0, repeatShare: null });
});

test("parseRetention: мусор в полях не роняет разбор", () => {
  const r = parseRetention({
    days: "90",
    kpi: "oops",
    users_total: "2437",
    exact_since: "вчера",
    today: "2026-02-31",
    returned_within: { days: 1 },
    daily: [null, 5, { date: "bad" }, { date: "2026-10-01", active: "12", new: -3, returning: "x" }],
    cohorts: [{ week_start: 7 }, { week_start: "2026-10-05", size: 10, weeks: "нет" }],
    payers: null,
  });
  assert.ok(r);
  assert.equal(r.days, 90);
  assert.equal(r.usersTotal, 2437);
  assert.equal(r.exactSince, null);
  assert.equal(r.today, null, "несуществующая дата отброшена");
  assert.equal(r.kpi.mau, 0);
  assert.equal(r.returnedWithin.length, 3);
  assert.deepEqual(r.daily, [{ date: "2026-10-01", active: 12, new: 0, returning: 0 }]);
  assert.equal(r.cohorts.length, 1);
  assert.equal(r.cohorts[0].weeks.length, COHORT_WEEKS);
  assert.ok(r.cohorts[0].weeks.every((w, i) => w.k === i + 1 && w.share === null));
});

test("parseRetention: окна «после регистрации» ищутся по days, а не по месту", () => {
  const r = parseRetention({
    returned_within: [
      { days: 30, base: 5, returned: 1, share: 20 },
      { days: 1, base: 9, returned: 3, share: 33.3 },
    ],
  });
  assert.deepEqual(
    r.returnedWithin.map((w) => [w.days, w.base, w.share]),
    [
      [1, 9, 33.3],
      [7, 0, null],
      [30, 5, 20],
    ]
  );
});

test("parseRetention: дни — по возрастанию, дубли отброшены; returning без поля = active − new", () => {
  const r = parseRetention({
    daily: [
      { date: "2026-10-03", active: 5, new: 2 },
      { date: "2026-10-01", active: 7, new: 1, returning: 6 },
      { date: "2026-10-03", active: 99, new: 0, returning: 99 },
    ],
  });
  assert.deepEqual(
    r.daily.map((d) => [d.date, d.active, d.new, d.returning]),
    [
      ["2026-10-01", 7, 1, 6],
      ["2026-10-03", 5, 2, 3],
    ]
  );
});

test("parseRetention: когорты — от новых к старым; недели по k, лишние и чужие отброшены", () => {
  const r = parseRetention({
    cohorts: [
      { week_start: "2026-09-01", size: 3, weeks: [{ k: 2, share: 33.3, eligible: 3, returned: 1 }, { k: 9, share: 50 }] },
      { week_start: "2026-10-06", size: 4, weeks: [{ share: 25, eligible: 4, returned: 1 }] },
    ],
  });
  assert.deepEqual(
    r.cohorts.map((c) => c.weekStart),
    ["2026-10-06", "2026-09-01"]
  );
  // Без k неделя берётся по месту в списке.
  assert.equal(r.cohorts[0].weeks[0].share, 25);
  const old = r.cohorts[1].weeks;
  assert.equal(old.length, COHORT_WEEKS);
  assert.equal(old[0].share, null);
  assert.equal(old[1].share, 33.3);
  assert.ok(old.every((w) => w.k <= COHORT_WEEKS));
});

test("share / isoDay: доля в 0…100 с 1 знаком, даты только настоящие", () => {
  assert.equal(share(12.345), 12.3);
  assert.equal(share("7.25"), 7.3);
  assert.equal(share(140), 100);
  assert.equal(share(-1), 0);
  assert.equal(share(null), null);
  assert.equal(share(undefined), null);
  assert.equal(share("abc"), null);
  assert.equal(isoDay("2026-10-28"), "2026-10-28");
  assert.equal(isoDay("2026-10-28T10:00:00+06:00"), "2026-10-28");
  assert.equal(isoDay("2026-13-01"), null);
  assert.equal(isoDay("28.10.2026"), null);
  assert.equal(isoDay(20261028), null);
});

test("errorText: слова сервера, нет связи, 404 = бэкенд ещё не обновлён", () => {
  assert.equal(errorText({ status: 0 }), "Нет связи с сервером. Проверьте интернет и повторите.");
  assert.equal(errorText({ status: 403, data: { detail: "Недостаточно прав." } }), "Недостаточно прав.");
  assert.match(errorText({ status: 404, data: "<html>" }), /обновить бэкенд/);
  assert.equal(errorText({ status: 500, data: null }), "Не удалось загрузить отчёт (HTTP 500)");
  assert.match(errorText({ status: 200, data: "<html>" }), /непонятном виде/);
});

test("fmtNum / fmtPct / fmtCompact: разряды, запятая, «—» вместо пустой доли", () => {
  assert.equal(sp(fmtNum(2437)), "2 437");
  assert.equal(fmtNum(0), "0");
  assert.equal(fmtPct(12.5), "12,5%");
  assert.equal(fmtPct(40), "40%");
  assert.equal(fmtPct(0), "0%");
  assert.equal(fmtPct(null), "—");
  assert.equal(fmtCompact(950), "950");
  assert.equal(sp(fmtCompact(1200)), "1,2 тыс.");
});

test("даты: «13 окт», «28 окт 2026», день недели; дата сервера не сдвигается часовым поясом", () => {
  assert.equal(fmtDayShort("2026-10-13"), "13 окт");
  assert.equal(fmtDayShort("2026-05-04"), "4 мая");
  // Регрессия: «г.» года срезался и с конца «авг.» — выходило «31 ав».
  assert.equal(fmtDayShort("2026-08-31"), "31 авг");
  assert.equal(fmtDayFull("2026-08-03"), "3 авг 2026");
  assert.equal(fmtDayFull("2026-10-28"), "28 окт 2026");
  assert.equal(fmtDayWeekday("2026-10-28"), "ср, 28 окт");
  // Непонятное показываем как пришло, а не «Invalid Date».
  assert.equal(fmtDayShort("bad"), "bad");
  assert.equal(fmtTime("2026-10-28T19:05:00+06:00"), "19:05");
  assert.equal(fmtTime("2026-10-28T13:05:00Z"), "19:05");
  assert.equal(fmtTime(null), null);
  assert.equal(fmtTime("nonsense"), null);
});

test("plural: 1 человек, 2 человека, 5/11/12 человек", () => {
  const f = (n) => `${n} ${plural(n, PEOPLE)}`;
  assert.equal(f(1), "1 человек");
  assert.equal(f(21), "21 человек");
  assert.equal(f(2), "2 человека");
  assert.equal(f(34), "34 человека");
  assert.equal(f(5), "5 человек");
  assert.equal(f(11), "11 человек");
  assert.equal(f(12), "12 человек");
  assert.equal(f(112), "112 человек");
  const days = ["день", "дня", "дней"];
  assert.equal(plural(1, days), "день");
  assert.equal(plural(7, days), "дней");
});

test("methodNote: текст из спецификации; без exact_since — «с момента выкладки»", () => {
  assert.equal(
    methodNote("2026-10-28"),
    "Человек считается активным в день, если заходил на сайт (вход или продление сессии), тратил кредиты, " +
      "оплачивал или что-то создавал. Точный учёт каждого захода — с 28 окт 2026; до этого — по входам, " +
      "продлениям сессии (не чаще раза в 12 часов), тратам, оплатам и созданным проектам. " +
      "Сотрудники, тестовый аккаунт, заблокированные и объединённые аккаунты не учитываются."
  );
  assert.match(methodNote("2026-10-28", "2026-02-26"), /Данные о заходах есть с 26 февр\.? 2026\. Сотрудники/);
  const pending = methodNote(null);
  assert.match(pending, /Точный учёт каждого захода — с момента выкладки; до этого — по входам/);
  assert.doesNotMatch(pending, /null|undefined/);
});

test("chartScale: круглые деления, шаг не меньше 1 человека", () => {
  assert.deepEqual(chartScale(0), { top: 1, ticks: [0, 1] });
  assert.deepEqual(chartScale(1), { top: 1, ticks: [0, 1] });
  assert.deepEqual(chartScale(3), { top: 3, ticks: [0, 1, 2, 3] });
  assert.deepEqual(chartScale(9), { top: 10, ticks: [0, 2, 4, 6, 8, 10] });
  assert.deepEqual(chartScale(37), { top: 40, ticks: [0, 10, 20, 30, 40] });
  assert.deepEqual(chartScale(41), { top: 50, ticks: [0, 10, 20, 30, 40, 50] });
  assert.deepEqual(chartScale(100), { top: 100, ticks: [0, 20, 40, 60, 80, 100] });
  assert.deepEqual(chartScale(1234), { top: 1250, ticks: [0, 250, 500, 750, 1000, 1250] });
  assert.deepEqual(chartScale(NaN), { top: 1, ticks: [0, 1] });
  assert.deepEqual(chartScale(-5), { top: 1, ticks: [0, 1] });
  // На любом пике: верх не ниже пика, деления целые, их не больше шести.
  for (let peak = 1; peak <= 5000; peak += 7) {
    const s = chartScale(peak);
    assert.ok(s.top >= peak && s.ticks.length <= 6 && s.ticks.every(Number.isInteger), `пик ${peak}`);
    assert.equal(s.ticks.at(-1), s.top);
  }
});

test("tickIndexes: последний день подписан всегда; 30 и 90 столбиков — не больше 6 подписей", () => {
  assert.deepEqual(tickIndexes(0), []);
  assert.deepEqual(tickIndexes(1), [0]);
  const t30 = tickIndexes(30);
  assert.equal(t30.at(-1), 29);
  assert.ok(t30.length <= 6);
  assert.deepEqual(t30, [4, 9, 14, 19, 24, 29]);
  const t90 = tickIndexes(90);
  assert.equal(t90.at(-1), 89);
  assert.ok(t90.length <= 6);
  assert.deepEqual(t90, [14, 29, 44, 59, 74, 89]);
});

test("edgeAlign / barAt: подсказка у краёв не вылезает; столбик под пальцем", () => {
  assert.equal(edgeAlign(0, 30), "start");
  assert.equal(edgeAlign(15, 30), "center");
  assert.equal(edgeAlign(29, 30), "end");
  assert.equal(edgeAlign(0, 1), "center");
  assert.equal(barAt(0, 300, 30), 0);
  assert.equal(barAt(299.9, 300, 30), 29);
  assert.equal(barAt(305, 300, 30), 29, "за правым краем — последний");
  assert.equal(barAt(-4, 300, 30), 0);
  assert.equal(barAt(150, 300, 90), 45);
  assert.equal(barAt(10, 0, 30), null);
  assert.equal(barAt(10, 300, 0), null);
});

test("barTotal: столбик не ниже active, даже если части разошлись", () => {
  assert.equal(barTotal({ date: "2026-10-01", active: 10, new: 3, returning: 7 }), 10);
  assert.equal(barTotal({ date: "2026-10-01", active: 5, new: 3, returning: 7 }), 10);
  assert.equal(barTotal({ date: "2026-10-01", active: 12, new: 3, returning: 7 }), 12);
});

test("cohortShade: null — пустая ячейка; ярче с долей; на яркой подложке текст тёмный", () => {
  assert.equal(cohortShade(null), null);
  assert.deepEqual(cohortShade(0), { alpha: 0, strong: false });
  const small = cohortShade(4);
  const mid = cohortShade(20);
  const full = cohortShade(100);
  assert.ok(small.alpha > 0.08 && small.alpha < mid.alpha && mid.alpha < full.alpha);
  assert.equal(full.alpha, 0.9);
  assert.equal(small.strong, false);
  assert.equal(full.strong, true);
  // Монотонно по всей шкале: ячейка с большей долей никогда не бледнее.
  let prev = -1;
  for (let p = 0; p <= 100; p += 0.5) {
    const a = cohortShade(p).alpha;
    assert.ok(a >= prev, `доля ${p}`);
    prev = a;
  }
  assert.equal(cohortShade(250).alpha, 0.9);
  assert.equal(shadeBackground(0), "transparent");
  assert.equal(shadeBackground(0.42), "color-mix(in srgb, var(--accent) 42%, transparent)");
});

test("cohortCellTitle: пустая — «неделя ещё не прошла»; частично прошедшая — из скольких", () => {
  assert.equal(cohortCellTitle({ k: 3, share: null, eligible: 0, returned: 0 }, 40), "неделя ещё не прошла");
  assert.equal(cohortCellTitle({ k: 1, share: 25, eligible: 40, returned: 10 }, 40), "Неделя 1: вернулись 10 из 40 (25%)");
  assert.equal(
    cohortCellTitle({ k: 2, share: 20, eligible: 30, returned: 6 }, 40),
    "Неделя 2: вернулись 6 из 30 (20%). У остальных 10 неделя ещё не прошла"
  );
});

test("страница: путь отчёта и токен, без сторонних библиотек графиков", () => {
  // Отрендерить страницу в node-тесте нечем, поэтому сторожим сам источник.
  const page = readFileSync(new URL("./page.tsx", import.meta.url), "utf8");
  assert.match(page, /^"use client";/);
  assert.match(page, /fetchData<unknown>\(\s*retentionPath\(days\),\s*"GET",\s*null,\s*true\s*\)/);
  assert.match(page, /parseRetention\(/);
  assert.doesNotMatch(page, /from "(recharts|chart\.js|d3|victory|@nivo[^"]*)"/);
  assert.match(page, /Возвраты пользователей/);
  assert.match(page, /methodNote\(/);
  // Регрессия (телефон 375 px): у блока прокрутки таблицы когорт без relative
  // sr-only подписи пустых ячеек вылезали из обрезки и растягивали страницу вбок.
  assert.match(page, /className="relative [^"]*overflow-x-auto/);
});

test("меню: «Возвраты» с FiRepeat сразу после «Воронки»", () => {
  const shell = readFileSync(new URL("../AdminShell.tsx", import.meta.url), "utf8");
  const funnel = shell.indexOf('{ href: "/admin-new/funnel"');
  const retention = shell.indexOf('{ href: "/admin-new/retention", label: "Возвраты", icon: FiRepeat }');
  assert.ok(funnel > 0 && retention > funnel, "пункт есть и стоит после «Воронки»");
  const between = shell.slice(funnel, retention);
  assert.equal(between.split("\n").length, 2, "между ними нет других пунктов");
});


test("historyWarning: без загруженной истории доли занижены — говорим об этом", () => {
  const warn = "История заходов ещё не загружена — доли возвратов пока занижены.";
  assert.equal(historyWarning(null, "2026-10-28"), warn);
  assert.equal(historyWarning("2026-10-25", "2026-10-28"), warn);
  assert.equal(historyWarning("2026-09-28", "2026-10-28"), null);
  assert.equal(historyWarning("2026-02-26", "2026-10-28"), null);
  assert.equal(historyWarning("2026-10-25", null), null);
});

test("cohortCellTitle: неделя без регистраций — не «ещё не прошла»", () => {
  assert.equal(
    cohortCellTitle({ k: 1, share: null, eligible: 0, returned: 0 }, 0),
    "в эту неделю никто не регистрировался"
  );
});

// Строка в том виде, как её отдаёт core/adminapi/retention.py (F30, раздел R).
const directionRow = (over = {}) => ({
  key: "video",
  group: "video",
  label: "Видео",
  parent: null,
  users: 120,
  generations: 660,
  per_user: 5.5,
  repeat: 30,
  repeat_share: 25,
  returned_direction: [
    { days: 1, base: 100, returned: 10, share: 10 },
    { days: 7, base: 90, returned: 18, share: 20 },
    { days: 30, base: 40, returned: 12, share: 30 },
  ],
  returned_site: [
    { days: 1, base: 100, returned: 20, share: 20 },
    { days: 7, base: 90, returned: 27, share: 30 },
    { days: 30, base: 40, returned: 16, share: 40 },
  ],
  paid: 24,
  paid_share: 20,
  active_period: 50,
  generations_period: 200,
  ...over,
});

test("parseRetention: «По направлениям» разбираются без потерь, порядок сервера сохраняется", () => {
  const r = parseRetention({
    directions: [
      directionRow(),
      directionRow({ key: "cartoon_scene", label: "Мультстудия", parent: "video" }),
      directionRow({ key: "text", group: "text", label: "Текст" }),
    ],
  });
  assert.deepEqual(
    r.directions.map((d) => [d.key, d.group, d.label, d.parent]),
    [
      ["video", "video", "Видео", null],
      ["cartoon_scene", "video", "Мультстудия", "video"],
      ["text", "text", "Текст", null],
    ]
  );
  assert.deepEqual(r.directions[0], {
    key: "video",
    group: "video",
    label: "Видео",
    parent: null,
    users: 120,
    generations: 660,
    perUser: 5.5,
    repeat: 30,
    repeatShare: 25,
    returnedDirection: [
      { days: 1, base: 100, returned: 10, share: 10 },
      { days: 7, base: 90, returned: 18, share: 20 },
      { days: 30, base: 40, returned: 12, share: 30 },
    ],
    returnedSite: [
      { days: 1, base: 100, returned: 20, share: 20 },
      { days: 7, base: 90, returned: 27, share: 30 },
      { days: 30, base: 40, returned: 16, share: 40 },
    ],
    paid: 24,
    paidShare: 20,
    activePeriod: 50,
    generationsPeriod: 200,
  });
});

test("parseRetention: старый сервер без ключа directions — блока нет, остальной отчёт цел", () => {
  const r = parseRetention(fullReport());
  assert.equal(r.directions, null);
  assert.equal(r.kpi.dau, 41);
  assert.equal(parseRetention({}).directions, null);
  assert.equal(parseRetention({ directions: "нет" }).directions, null);
  assert.equal(parseRetention({ directions: { key: "video" } }).directions, null);
  assert.equal(parseRetention({ directions: [] }).directions, null);
});

test("parseRetention: мусор в строках направлений не роняет разбор", () => {
  const r = parseRetention({
    directions: [
      null,
      7,
      { label: "без ключа" },
      { key: "no-label" },
      { key: "video", label: "Видео", users: "12", per_user: "abc", repeat_share: 140, parent: "" },
      { key: "video", label: "Дубль", users: 99 },
    ],
  });
  assert.equal(r.directions.length, 1);
  const [row] = r.directions;
  assert.equal(row.users, 12);
  assert.equal(row.generations, 0);
  assert.equal(row.perUser, null);
  assert.equal(row.repeatShare, 100);
  assert.equal(row.parent, null);
  assert.equal(row.group, "video");
  assert.deepEqual(
    row.returnedSite.map((w) => [w.days, w.share]),
    [
      [1, null],
      [7, null],
      [30, null],
    ]
  );
});

test("perUser / fmtPerUser: больше 100 — не доля, один знак всегда, «—» вместо пустого", () => {
  assert.equal(perUser(5.54), 5.5);
  assert.equal(perUser("2.5"), 2.5);
  assert.equal(perUser(137.25), 137.3);
  assert.equal(perUser(-1), null);
  assert.equal(perUser(null), null);
  assert.equal(perUser(undefined), null);
  assert.equal(perUser(""), null);
  assert.equal(fmtPerUser(2.5), "2,5");
  assert.equal(fmtPerUser(3), "3,0");
  assert.equal(fmtPerUser(null), "—");
});

test("windowOf / windowNote: окно по дням; пустая база — «некого считать», а не «0 из 0»", () => {
  const list = [
    { days: 7, base: 90, returned: 18, share: 20 },
    { days: 30, base: 0, returned: 0, share: null },
  ];
  assert.equal(windowOf(list, 7).returned, 18);
  assert.deepEqual(windowOf(list, 1), { days: 1, base: 0, returned: 0, share: null });
  assert.equal(windowNote(list[0]), "18 из 90");
  assert.equal(windowNote(list[1]), "некого считать");
});

test("DIRECTIONS_NOTE: простыми словами — что считаем, с какой даты, что такое повтор", () => {
  assert.match(DIRECTIONS_NOTE, /только успешные генерации/);
  assert.match(DIRECTIONS_NOTE, /данные с 28 июня/);
  assert.match(DIRECTIONS_NOTE, /в 2 и более разных дня/);
});

test("страница: блок «По направлениям» — сразу после «Вернулись после регистрации», только если он есть", () => {
  const page = readFileSync(new URL("./page.tsx", import.meta.url), "utf8");
  const after = page.indexOf("<ReturnedAfterJoin report={report} />");
  const block = page.indexOf("{report.directions && <Directions rows={report.directions}");
  const chart = page.indexOf("<DailyChart key=");
  assert.ok(after > 0 && block > after && chart > block, "порядок блоков");
  assert.match(page, /По направлениям/);
  for (const title of ["Людей", "Генераций", "На человека", "Повторили (2+ дня)", "Вернулись на сайт, 30 дн", "Платили"]) {
    assert.ok(page.includes(`"${title}"`), title);
  }
  // Таблица шире телефона: прокрутка только внутри карточки, у двух таблиц одинаково.
  const scroll = page.match(/className="relative -mx-5 mt-4 overflow-x-auto px-5"/g);
  assert.equal(scroll.length, 2);
});
