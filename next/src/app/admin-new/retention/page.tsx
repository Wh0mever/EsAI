"use client";

import { useEffect, useId, useRef, useState, type KeyboardEvent, type MouseEvent, type PointerEvent } from "react";
import { FiInfo, FiRefreshCw } from "react-icons/fi";
import { fetchData } from "@/tools/fetchData";
import { CARD, Skeleton, btn } from "../vstudio-showcase/parts";
import {
  COHORT_WEEKS,
  DIRECTIONS_NOTE,
  PEOPLE,
  PERIODS,
  barAt,
  barTotal,
  chartScale,
  cohortCellTitle,
  historyWarning,
  cohortShade,
  edgeAlign,
  errorText,
  fmtCompact,
  fmtDayShort,
  fmtDayWeekday,
  fmtNum,
  fmtPct,
  fmtPerUser,
  fmtTime,
  methodNote,
  parseRetention,
  plural,
  retentionPath,
  shadeBackground,
  tickIndexes,
  windowNote,
  windowOf,
  type Cohort,
  type DailyRow,
  type Direction,
  type Period,
  type Retention,
  type ReturnedWithin,
} from "./retention";

/**
 * Возвраты пользователей.
 *
 * Фонд, которому показывали EsAI, спросил не «сколько зарегистрировалось», а
 * «сколько приходит снова»: регистрации покупаются рекламой, а возвраты
 * показывают, нужен ли продукт. Поэтому главное здесь — люди, которые были на
 * сайте ПОЗЖЕ дня своей регистрации, и как быстро они возвращаются.
 *
 * Все определения и цифры считает сервер (core/adminapi, F29_RETENTION_SPEC);
 * страница только раскладывает их по блокам. Разбор ответа и формат — в
 * retention.ts, чтобы его проверял node-тест без браузера.
 */

const DAYS_GEN = ["дня", "дней", "дней"] as const;
const WEEKS = Array.from({ length: COHORT_WEEKS }, (_, i) => i + 1);

export default function AdminRetentionPage() {
  const [days, setDays] = useState<Period>(30);
  const [tick, setTick] = useState(0);
  const [report, setReport] = useState<Retention | null>(null);
  // Загрузка выводится из ключа запроса, а не ставится флагом в эффекте:
  // так и смена периода, и «Повторить» включают её сами, без лишнего рендера.
  const [loaded, setLoaded] = useState<{ key: string; error: string | null } | null>(null);

  const key = `${days}:${tick}`;
  const loading = loaded?.key !== key;
  const error = loading ? null : (loaded?.error ?? null);

  useEffect(() => {
    let alive = true;
    (async () => {
      const res = await fetchData<unknown>(retentionPath(days), "GET", null, true);
      if (!alive) return;
      const parsed = res.ok ? parseRetention(res.data) : null;
      if (!parsed) {
        setLoaded({ key, error: errorText(res) });
        return;
      }
      setReport(parsed);
      setLoaded({ key, error: null });
    })();
    return () => {
      alive = false;
    };
  }, [days, key]);

  const updated = report ? fmtTime(report.generatedAt) : null;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Возвраты пользователей</h1>
          <p className="mt-1 max-w-2xl text-sm text-muted">
            Кто приходит на сайт снова — после дня своей регистрации, и как быстро.
            {report && <> Всего пользователей: {fmtNum(report.usersTotal)}.</>}
          </p>
        </div>
        <div role="group" aria-label="Период" className="inline-flex rounded-xl border border-border p-1">
          {PERIODS.map((d) => (
            <button
              key={d}
              type="button"
              aria-pressed={days === d}
              onClick={() => setDays(d)}
              className={`cursor-pointer rounded-lg px-3 py-1.5 text-sm transition-colors ${
                days === d ? "bg-accent text-on-accent" : "text-muted hover:text-foreground"
              }`}
            >
              {d} дней
            </button>
          ))}
        </div>
      </div>

      {!report && loading && (
        <div className="space-y-4" aria-busy="true">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
            {[0, 1, 2, 3, 4, 5].map((i) => (
              <Skeleton key={i} className="h-28" />
            ))}
          </div>
          <Skeleton className="h-40" />
          <Skeleton className="h-72" />
        </div>
      )}

      {error && (
        <div className={`${CARD} flex flex-col items-start gap-3 p-6`}>
          <div className="text-sm text-status-fail">{error}</div>
          <button type="button" onClick={() => setTick((t) => t + 1)} className={btn("plain", "lg")}>
            <FiRefreshCw className="h-4 w-4" aria-hidden />
            Повторить
          </button>
        </div>
      )}

      {report && !error && (
        // При смене периода прежний отчёт остаётся на месте, только бледнеет:
        // без скелетона и прыжка вёрстки, пока едут новые цифры.
        <div className={`space-y-6 transition-opacity ${loading ? "opacity-60" : ""}`} aria-busy={loading}>
          <Kpis report={report} />
          {historyWarning(report.historySince, report.today) && (
            <p role="status" className={`${CARD} flex items-start gap-2 p-4 text-sm text-status-fail`}>
              <FiInfo className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
              <span>{historyWarning(report.historySince, report.today)}</span>
            </p>
          )}
          <ReturnedAfterJoin report={report} />
          {report.directions && <Directions rows={report.directions} days={report.days} />}
          <DailyChart key={`${report.days}:${report.daily.length}`} rows={report.daily} />
          <CohortTable cohorts={report.cohorts} />
          <RepeatPurchases report={report} />

          <div className="space-y-2 text-xs text-muted-2">
            <p className="flex max-w-3xl items-start gap-2">
              <FiInfo className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
              <span>{methodNote(report.exactSince, report.historySince)}</span>
            </p>
            {updated && (
              <p className="pl-5">Отчёт пересчитывается не чаще раза в 5 минут; этот посчитан в {updated}.</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Плитки                                                              */
/* ------------------------------------------------------------------ */

function Tile({ label, value, extra, hint }: { label: string; value: string; extra?: string; hint: string }) {
  return (
    <div className={`${CARD} p-4`}>
      <div className="text-sm text-muted">{label}</div>
      <div className="mt-1 flex flex-wrap items-baseline gap-x-2">
        <span className="text-3xl font-bold">{value}</span>
        {extra && <span className="text-sm font-medium text-accent">{extra}</span>}
      </div>
      <div className="mt-1 text-xs text-muted-2">{hint}</div>
    </div>
  );
}

function Kpis({ report }: { report: Retention }) {
  const k = report.kpi;
  const period = `${report.days} дней`;
  return (
    <section aria-label="Главные цифры" className="grid grid-cols-2 gap-3 md:grid-cols-3">
      <Tile label="Активны сегодня" value={fmtNum(k.dau)} hint="DAU — были на сайте или что-то делали сегодня" />
      <Tile label="За 7 дней" value={fmtNum(k.wau)} hint="WAU — разных людей за 7 дней, включая сегодня" />
      <Tile label="За 30 дней" value={fmtNum(k.mau)} hint="MAU — разных людей за 30 дней, включая сегодня" />
      <Tile
        label="Вернулись за период"
        value={fmtNum(k.returning)}
        extra={fmtPct(k.returningShare)}
        hint={`от ${fmtNum(k.active)} активных за ${period} — заходили позже дня своей регистрации`}
      />
      <Tile label="Новые за период" value={fmtNum(k.new)} hint={`зарегистрировались за ${period}`} />
      <Tile
        label="Стикинесс DAU/MAU"
        value={fmtPct(k.stickiness)}
        hint="средний DAU за 30 дней ÷ MAU: какая часть месячной аудитории заходит каждый день"
      />
    </section>
  );
}

function ReturnedAfterJoin({ report }: { report: Retention }) {
  const k = report.kpi;
  return (
    <section className={`${CARD} p-5`}>
      <h2 className="text-base font-semibold">Вернулись после регистрации</h2>
      <p className="mt-1 text-xs text-muted-2">
        Среди зарегистрировавшихся не меньше N дней назад — доля тех, кто пришёл снова в следующие N дней
        после дня регистрации.
      </p>
      <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
        {report.returnedWithin.map((w) => (
          <div key={w.days} className="rounded-xl bg-surface-2 p-4">
            <div className="text-sm text-muted">
              В течение {w.days} {plural(w.days, DAYS_GEN)}
            </div>
            <div className="mt-1 text-2xl font-bold">{fmtPct(w.share)}</div>
            <div className="mt-1 text-xs text-muted-2">
              {w.base ? `вернулись ${fmtNum(w.returned)} из ${fmtNum(w.base)}` : "пока некого считать"}
            </div>
          </div>
        ))}
      </div>
      <p className="mt-4 text-sm text-muted">
        Хотя бы раз возвращались:{" "}
        <span className="font-semibold text-foreground">{fmtPct(k.returnedEverShare)}</span> (
        {fmtNum(k.returnedEver)} {plural(k.returnedEver, PEOPLE)})
      </p>
    </section>
  );
}

/* ------------------------------------------------------------------ */
/* По направлениям                                                     */
/* ------------------------------------------------------------------ */

const DIRECTION_COLUMNS = [
  "Людей",
  "Генераций",
  "На человека",
  "Повторили (2+ дня)",
  "Вернулись к направлению, 7 дн",
  "Вернулись к направлению, 30 дн",
  "Вернулись на сайт, 30 дн",
  "Платили",
];

function DirectionCell({ main, note }: { main: string; note?: string }) {
  return (
    <td className="py-2 pl-4 text-right align-top tabular-nums">
      <div>{main}</div>
      {note && <div className="text-xs whitespace-nowrap text-muted-2">{note}</div>}
    </td>
  );
}

function DirectionRow({ row, groupLabel, period }: { row: Direction; groupLabel?: string; period: string }) {
  const back = (w: ReturnedWithin) => <DirectionCell main={fmtPct(w.share)} note={windowNote(w)} />;
  return (
    <tr className="border-t border-border">
      <th
        scope="row"
        className={`sticky left-0 z-[1] bg-surface py-2 pr-3 text-left align-top whitespace-nowrap ${
          groupLabel ? "pl-4 font-normal text-muted" : "font-semibold text-foreground"
        }`}
      >
        {groupLabel && <span className="sr-only">{groupLabel}: </span>}
        {row.label}
      </th>
      <DirectionCell main={fmtNum(row.users)} note={`${period}: ${fmtNum(row.activePeriod)}`} />
      <DirectionCell main={fmtNum(row.generations)} note={`${period}: ${fmtNum(row.generationsPeriod)}`} />
      <DirectionCell main={fmtPerUser(row.perUser)} />
      <DirectionCell main={fmtPct(row.repeatShare)} note={`${fmtNum(row.repeat)} чел.`} />
      {back(windowOf(row.returnedDirection, 7))}
      {back(windowOf(row.returnedDirection, 30))}
      {back(windowOf(row.returnedSite, 30))}
      <DirectionCell main={fmtPct(row.paidShare)} note={`${fmtNum(row.paid)} чел.`} />
    </tr>
  );
}

/**
 * Какие сценарии удерживают людей: группы «Видео», «Изображения», «Текст» и под
 * ними мультстудия, видеостудия, чат. Дополнительная строка в ячейке «Людей» и
 * «Генераций» — за выбранный период: остальные столбцы считаются за всё время.
 */
function Directions({ rows, days }: { rows: Direction[]; days: number }) {
  return (
    <section className={`${CARD} p-5`}>
      <h2 className="text-base font-semibold">По направлениям</h2>
      <p className="mt-1 max-w-3xl text-xs text-muted-2">{DIRECTIONS_NOTE}</p>

      {rows.every((r) => r.users === 0) ? (
        <p className="mt-4 text-sm text-muted">Генераций пока не было.</p>
      ) : (
        // Прокрутка вбок — внутри карточки, как у таблицы когорт; relative — по той же причине.
        <div className="relative -mx-5 mt-4 overflow-x-auto px-5">
          <table className="w-full min-w-[52rem] text-sm">
            <caption className="sr-only">Возвраты и повторные генерации по направлениям</caption>
            <thead>
              <tr className="text-xs text-muted-2">
                <th scope="col" className="sticky left-0 z-[1] bg-surface pb-2 pr-3 text-left align-bottom font-medium">
                  Направление
                </th>
                {DIRECTION_COLUMNS.map((title) => (
                  <th key={title} scope="col" className="pb-2 pl-4 text-right align-bottom font-medium">
                    {title}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <DirectionRow
                  key={row.key}
                  row={row}
                  groupLabel={row.parent ? rows.find((r) => r.key === row.parent)?.label : undefined}
                  period={`за ${days} дн`}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function RepeatPurchases({ report }: { report: Retention }) {
  const p = report.payers;
  const cells = [
    { label: "Платили", value: fmtNum(p.paying) },
    { label: "Платили 2+ раза", value: fmtNum(p.repeat) },
    { label: "Доля повторных", value: fmtPct(p.repeatShare) },
  ];
  return (
    <section className={`${CARD} p-5`}>
      <h2 className="text-base font-semibold">Повторные покупки</h2>
      <p className="mt-1 text-xs text-muted-2">Успешные оплаты за всё время, без тестовых.</p>
      <div className="mt-4 grid grid-cols-3 gap-3">
        {cells.map((c) => (
          <div key={c.label} className="rounded-xl bg-surface-2 p-3 sm:p-4">
            <div className="text-xs text-muted sm:text-sm">{c.label}</div>
            <div className="mt-1 text-xl font-bold sm:text-2xl">{c.value}</div>
          </div>
        ))}
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ */
/* График «Активные по дням»                                           */
/* ------------------------------------------------------------------ */

/**
 * Столбик на день: снизу вернувшиеся (золото — о них страница), сверху новые
 * (серым, второй план). Без библиотек: div-ы с высотой в процентах шкалы.
 * Подсказка — по наведению мышью, по тапу (повторный тап или тап мимо
 * закрывает) и стрелками с клавиатуры; числа дублирует таблица «Числа по дням».
 */
function DailyChart({ rows }: { rows: DailyRow[] }) {
  const [active, setActive] = useState<number | null>(null);
  // Тип указателя последнего нажатия: мышь показывает подсказку наведением,
  // а палец — тапом, и тот же тап должен уметь её закрыть.
  const pointer = useRef<string>("mouse");
  const titleId = useId();

  const n = rows.length;
  const peak = rows.reduce((m, r) => Math.max(m, barTotal(r)), 0);
  const scale = chartScale(peak);
  const ticks = tickIndexes(n);
  // На 90 днях столбики в пару пикселей: зазор и скругление уменьшаем, иначе от столбика ничего не останется.
  const dense = n > 45;
  const gap = dense ? 1 : 2;
  const radius = dense ? "rounded-t-[2px]" : "rounded-t-[4px]";
  const current = active !== null && active < n ? rows[active] : null;
  const pct = (v: number) => (v / scale.top) * 100;

  const barFrom = (e: PointerEvent<HTMLDivElement> | MouseEvent<HTMLDivElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    return barAt(e.clientX - rect.left, rect.width, n);
  };

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (!n) return;
    let next: number | null;
    if (e.key === "ArrowLeft") next = active === null ? n - 1 : Math.max(0, active - 1);
    else if (e.key === "ArrowRight") next = active === null ? n - 1 : Math.min(n - 1, active + 1);
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = n - 1;
    else if (e.key === "Escape") next = null;
    else return;
    e.preventDefault();
    setActive(next);
  };

  const readout = current
    ? `${fmtDayWeekday(current.date)}: активных ${fmtNum(current.active)}, вернувшихся ${fmtNum(
        current.returning
      )}, новых ${fmtNum(current.new)}`
    : "";

  return (
    <section className={`${CARD} p-5`}>
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-2">
        <h2 id={titleId} className="text-base font-semibold">
          Активные по дням
        </h2>
        <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted" aria-label="Легенда">
          <li className="inline-flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-[3px] bg-accent" aria-hidden />
            Вернувшиеся
          </li>
          <li className="inline-flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-[3px] bg-muted-2" aria-hidden />
            Новые
          </li>
        </ul>
      </div>
      <p className="mt-1 text-xs text-muted-2">
        Столбик — все, кто был активен в этот день: снизу вернувшиеся (зарегистрировались раньше), сверху новые
        (зарегистрировались в этот день). Наведите или нажмите на столбик, чтобы увидеть числа.
      </p>

      {n === 0 ? (
        <p className="mt-6 text-sm text-muted">За период данных нет.</p>
      ) : (
        <div className="mt-4 grid grid-cols-[auto_minmax(0,1fr)] gap-x-2">
          {/* Ось Y: круглые деления, линии сетки — волосяные и тише данных. */}
          <div className={`relative h-48 sm:h-60 ${scale.top >= 1000 ? "w-12" : "w-7"}`} aria-hidden>
            {scale.ticks.map((t) => (
              <span
                key={t}
                className="absolute right-0 translate-y-1/2 text-[11px] leading-none tabular-nums text-muted-2"
                style={{ bottom: `${pct(t)}%` }}
              >
                {fmtCompact(t)}
              </span>
            ))}
          </div>

          <div
            role="group"
            aria-labelledby={titleId}
            aria-roledescription="график"
            aria-describedby={`${titleId}-keys`}
            tabIndex={0}
            className="relative h-48 cursor-crosshair touch-pan-y rounded-md outline-none focus-visible:ring-2 focus-visible:ring-accent/60 sm:h-60"
            onPointerDown={(e) => {
              pointer.current = e.pointerType;
            }}
            onPointerMove={(e) => {
              if (e.pointerType !== "touch") setActive(barFrom(e));
            }}
            onPointerLeave={(e) => {
              // У пальца pointerleave приходит сразу после касания — подсказку
              // тапа он закрывать не должен.
              if (e.pointerType !== "touch") setActive(null);
            }}
            onClick={(e) => {
              const i = barFrom(e);
              if (pointer.current === "touch") setActive((prev) => (prev === i ? null : i));
              else setActive(i);
            }}
            onKeyDown={onKeyDown}
            onBlur={() => setActive(null)}
          >
            {scale.ticks.map((t) => (
              <div
                key={t}
                className={`pointer-events-none absolute inset-x-0 border-t ${t === 0 ? "border-border-strong" : "border-border"}`}
                style={{ bottom: `${pct(t)}%` }}
                aria-hidden
              />
            ))}

            <div className="absolute inset-0 flex items-stretch" style={{ gap }} aria-hidden>
              {rows.map((r, i) => {
                const topIsNew = r.new > 0;
                return (
                  <div
                    key={r.date}
                    className={`flex min-w-0 flex-1 flex-col items-center justify-end rounded-sm ${
                      i === active ? "bg-foreground/[0.07]" : ""
                    }`}
                  >
                    {r.new > 0 && (
                      <div
                        className={`w-full max-w-6 bg-muted-2 ${radius}`}
                        style={{ height: `${pct(r.new)}%`, minHeight: 2 }}
                      />
                    )}
                    {r.returning > 0 && (
                      <div
                        className={`w-full max-w-6 bg-accent ${topIsNew ? "" : radius}`}
                        // Зазор цвета фона между частями столбика — вместо обводки.
                        style={{ height: `${pct(r.returning)}%`, minHeight: 2, marginTop: topIsNew ? gap : 0 }}
                      />
                    )}
                  </div>
                );
              })}
            </div>

            {peak === 0 && (
              <p className="pointer-events-none absolute inset-0 flex items-center justify-center text-sm text-muted">
                За период активности не было.
              </p>
            )}

            {current && active !== null && (
              <div
                className="pointer-events-none absolute top-1 z-10 w-44 rounded-xl border border-border-strong bg-surface-3 p-3 text-xs shadow-lg"
                // Подсказка не вылезает за край графика ни на телефоне, ни на крайних днях.
                style={{ left: `clamp(0px, calc(${((active + 0.5) / n) * 100}% - 5.5rem), calc(100% - 11rem))` }}
                aria-hidden
              >
                <div className="text-muted">{fmtDayWeekday(current.date)}</div>
                <div className="mt-1 flex items-baseline gap-1.5">
                  <span className="text-base font-semibold text-foreground">{fmtNum(current.active)}</span>
                  <span className="text-muted">активных</span>
                </div>
                <TipRow swatch="bg-accent" value={current.returning} label="вернувшиеся" />
                <TipRow swatch="bg-muted-2" value={current.new} label="новые" />
              </div>
            )}
          </div>

          <div aria-hidden />
          <div className="relative mt-1.5 h-4" aria-hidden>
            {ticks.map((i, idx) => {
              const align = edgeAlign(i, n);
              const left = align === "start" ? i / n : align === "end" ? (i + 1) / n : (i + 0.5) / n;
              const shift = align === "start" ? "0" : align === "end" ? "-100%" : "-50%";
              // На телефоне подписей вдвое меньше; последний день (сегодня) остаётся всегда.
              const narrowHidden = (ticks.length - 1 - idx) % 2 === 1;
              return (
                <span
                  key={i}
                  className={`absolute top-0 whitespace-nowrap text-[11px] leading-none text-muted-2 ${
                    narrowHidden ? "max-sm:hidden" : ""
                  }`}
                  style={{ left: `${left * 100}%`, transform: `translateX(${shift})` }}
                >
                  {fmtDayShort(rows[i].date)}
                </span>
              );
            })}
          </div>
        </div>
      )}

      <p id={`${titleId}-keys`} className="sr-only">
        Стрелки влево и вправо — переход по дням, Esc — закрыть подсказку.
      </p>
      <p className="sr-only" aria-live="polite">
        {readout}
      </p>

      {n > 0 && (
        <details className="mt-4">
          <summary className="cursor-pointer text-xs text-muted hover:text-foreground">Числа по дням</summary>
          <div className="mt-2 max-h-72 overflow-auto">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-surface text-xs uppercase text-muted-2">
                <tr>
                  <th scope="col" className="pb-2 text-left font-medium">
                    День
                  </th>
                  <th scope="col" className="pb-2 text-right font-medium">
                    Активных
                  </th>
                  <th scope="col" className="pb-2 text-right font-medium">
                    Вернувшихся
                  </th>
                  <th scope="col" className="pb-2 text-right font-medium">
                    Новых
                  </th>
                </tr>
              </thead>
              <tbody>
                {[...rows].reverse().map((r) => (
                  <tr key={r.date} className="border-t border-border">
                    <th scope="row" className="py-1.5 pr-3 text-left font-normal text-muted">
                      {fmtDayWeekday(r.date)}
                    </th>
                    <td className="py-1.5 text-right tabular-nums">{fmtNum(r.active)}</td>
                    <td className="py-1.5 text-right tabular-nums">{fmtNum(r.returning)}</td>
                    <td className="py-1.5 text-right tabular-nums">{fmtNum(r.new)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}
    </section>
  );
}

function TipRow({ swatch, value, label }: { swatch: string; value: number; label: string }) {
  return (
    <div className="mt-1 flex items-center gap-1.5">
      <span className={`h-0.5 w-3 rounded-full ${swatch}`} aria-hidden />
      <span className="font-medium tabular-nums text-foreground">{fmtNum(value)}</span>
      <span className="text-muted">{label}</span>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Когорты                                                             */
/* ------------------------------------------------------------------ */

/**
 * Строка — неделя регистрации, столбец — k-я неделя после регистрации каждого
 * человека (не календарная). Пустая ячейка — неделя ещё ни у кого не прошла:
 * ноль там соврал бы, что никто не вернулся.
 */
function CohortTable({ cohorts }: { cohorts: Cohort[] }) {
  return (
    <section className={`${CARD} p-5`}>
      <h2 className="text-base font-semibold">Удержание по неделям</h2>
      <p className="mt-1 text-xs text-muted-2">
        Строка — люди, зарегистрировавшиеся за неделю (с понедельника). Ячейка — какая доля из них была на сайте
        на 1-й, 2-й … 8-й неделе после своей регистрации; считаем только тех, у кого эта неделя уже прошла.
        Пусто — она ещё не прошла ни у кого.
      </p>

      {cohorts.every((c) => c.size === 0) ? (
        <p className="mt-4 text-sm text-muted">За последние 12 недель регистраций не было.</p>
      ) : (
        // Прокрутка вбок — внутри карточки: на телефоне 9 столбцов не помещаются,
        // а страница целиком ездить не должна. relative обязателен: без него
        // sr-only подписи пустых ячеек (position: absolute) отсчитываются от
        // страницы, обходят обрезку блока и растягивают её вбок на телефоне.
        <div className="relative -mx-5 mt-4 overflow-x-auto px-5">
          <table className="w-full min-w-[40rem] border-separate border-spacing-1 text-sm">
            <caption className="sr-only">Доля вернувшихся по неделям после регистрации</caption>
            <thead>
              <tr className="text-xs text-muted-2">
                <th scope="col" className="sticky left-0 z-[1] bg-surface pb-1 pr-2 text-left font-medium">
                  Неделя регистрации
                </th>
                {WEEKS.map((k) => (
                  <th key={k} scope="col" className="pb-1 text-center font-medium whitespace-nowrap">
                    Неделя {k}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {cohorts.map((c) => (
                <tr key={c.weekStart}>
                  <th scope="row" className="sticky left-0 z-[1] bg-surface pr-2 text-left font-normal whitespace-nowrap">
                    <div className="text-foreground">с {fmtDayShort(c.weekStart)}</div>
                    <div className="text-xs tabular-nums text-muted-2">{fmtNum(c.size)} чел.</div>
                  </th>
                  {c.weeks.map((w) => {
                    const shade = cohortShade(w.share);
                    const title = cohortCellTitle(w, c.size);
                    return (
                      <td
                        key={w.k}
                        title={title}
                        className={`h-10 min-w-14 rounded-md text-center text-xs tabular-nums ${
                          shade && shade.alpha === 0 ? "text-muted-2" : ""
                        }`}
                        style={
                          shade
                            ? {
                                background: shadeBackground(shade.alpha),
                                // На яркой подложке светлый текст тёмной темы не читается — берём тёмный.
                                color: shade.strong ? "var(--on-accent)" : undefined,
                              }
                            : undefined
                        }
                      >
                        {shade ? (
                          fmtPct(w.share)
                        ) : c.size === 0 ? (
                          <span className="text-muted-2" aria-label={title}>
                            —
                          </span>
                        ) : (
                          <span className="sr-only">{title}</span>
                        )}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
