"use client";

import { useEffect, useMemo, useState, type ReactNode } from "react";
import { FiBarChart2, FiClock, FiRefreshCw } from "react-icons/fi";
import { fetchData } from "@/tools/fetchData";
import { CARD, INPUT, Skeleton, btn } from "../vstudio-showcase/parts";
import {
  LOG_PATH,
  PERIODS,
  creditsText,
  errorText,
  fmtInt,
  logLines,
  marginShare,
  parseLog,
  parseSummary,
  periodRange,
  rangeProblem,
  rangeText,
  summaryPath,
  usdText,
  type LogEntry,
  type Period,
  type Summary,
  type ToolRow,
} from "./creativeAdmin";

const ICON = "h-4 w-4 text-accent";

function CardHeader({ icon, title, children }: { icon: ReactNode; title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div className="flex items-center gap-2">
        {icon}
        <h2 className="text-base font-semibold">{title}</h2>
      </div>
      {children && <div className="flex flex-wrap items-center gap-2">{children}</div>}
    </div>
  );
}

function Failure({ text, onRetry }: { text: string; onRetry: () => void }) {
  return (
    <div className="mt-4 flex flex-col items-start gap-3">
      <div role="alert" className="text-sm text-status-fail">
        {text}
      </div>
      <button type="button" onClick={onRetry} className={btn("plain", "lg")}>
        <FiRefreshCw className="h-4 w-4" aria-hidden />
        Повторить
      </button>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Сводка за период                                                    */
/* ------------------------------------------------------------------ */

type Range = { from: string; to: string };
type Choice = Period | "custom";

function Tile({ label, value, sub }: { label: string; value: string; sub?: ReactNode }) {
  return (
    <div className="rounded-xl border border-border bg-surface-2/50 p-3">
      <div className="text-[11px] uppercase tracking-wide text-muted-2">{label}</div>
      <div className="mt-1 text-xl font-semibold tabular-nums text-foreground">{value}</div>
      {sub && <div className="mt-0.5 text-[11px] text-muted-2">{sub}</div>}
    </div>
  );
}

/**
 * Задачи, кредиты, себестоимость и маржа за период — всего и по
 * инструментам. Период: 7/30/90 дней или свои даты (сервер: до года).
 */
export function SummaryCard() {
  const [choice, setChoice] = useState<Choice>(30);
  const [custom, setCustom] = useState<Range>(() => periodRange(30, new Date()));
  const [applied, setApplied] = useState<Range>(() => periodRange(30, new Date()));
  const [tick, setTick] = useState(0);
  const [report, setReport] = useState<Summary | null>(null);
  const [loaded, setLoaded] = useState<{ key: string; error: string | null } | null>(null);

  const key = `${applied.from}|${applied.to}|${tick}`;
  const loading = loaded?.key !== key;
  const error = loading ? null : (loaded?.error ?? null);
  const customProblem = choice === "custom" ? rangeProblem(custom.from, custom.to) : null;

  useEffect(() => {
    let alive = true;
    (async () => {
      const res = await fetchData<unknown>(summaryPath(applied.from, applied.to), "GET", null, true);
      if (!alive) return;
      const parsed = res.ok ? parseSummary(res.data) : null;
      if (!parsed) {
        setLoaded({ key, error: res.ok ? "Сервер ответил непонятно." : errorText(res, "Сводка не загрузилась") });
        return;
      }
      setReport(parsed);
      setLoaded({ key, error: null });
    })();
    return () => {
      alive = false;
    };
  }, [applied, key]);

  const pick = (p: Period) => {
    setChoice(p);
    setApplied(periodRange(p, new Date()));
  };

  const used = useMemo(
    () => (report ? [...report.byTool].filter((t) => t.jobs > 0).sort((a, b) => b.jobs - a.jobs) : []),
    [report],
  );

  return (
    <section className={`${CARD} p-5`}>
      <CardHeader icon={<FiBarChart2 className={ICON} aria-hidden />} title="Сводка">
        <div role="group" aria-label="Период" className="inline-flex rounded-xl border border-border p-1">
          {PERIODS.map((d) => (
            <button
              key={d}
              type="button"
              aria-pressed={choice === d}
              onClick={() => pick(d)}
              className={`cursor-pointer rounded-lg px-3 py-1.5 text-xs transition-colors ${
                choice === d ? "bg-accent text-on-accent" : "text-muted hover:text-foreground"
              }`}
            >
              {d} дней
            </button>
          ))}
          <button
            type="button"
            aria-pressed={choice === "custom"}
            onClick={() => setChoice("custom")}
            className={`cursor-pointer rounded-lg px-3 py-1.5 text-xs transition-colors ${
              choice === "custom" ? "bg-accent text-on-accent" : "text-muted hover:text-foreground"
            }`}
          >
            Свои даты
          </button>
        </div>
      </CardHeader>

      {choice === "custom" && (
        <form
          className="mt-3 flex flex-wrap items-end gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            if (!customProblem) setApplied({ ...custom });
          }}
        >
          <label className="flex flex-col gap-1 text-xs text-muted">
            С
            <input
              type="date"
              value={custom.from}
              max={custom.to || undefined}
              onChange={(e) => setCustom((r) => ({ ...r, from: e.target.value }))}
              className={INPUT}
            />
          </label>
          <label className="flex flex-col gap-1 text-xs text-muted">
            По
            <input
              type="date"
              value={custom.to}
              min={custom.from || undefined}
              onChange={(e) => setCustom((r) => ({ ...r, to: e.target.value }))}
              className={INPUT}
            />
          </label>
          <button type="submit" disabled={Boolean(customProblem)} className={btn("primary")}>
            Показать
          </button>
          {customProblem && <span className="pb-1.5 text-xs text-status-fail">{customProblem}</span>}
        </form>
      )}

      {report && (
        <p className="mt-2 text-xs text-muted-2">
          Период: <span className="text-foreground">{rangeText(report.from, report.to)}</span>
        </p>
      )}

      {!report && loading && (
        <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-5" aria-busy="true">
          {[0, 1, 2, 3, 4].map((i) => (
            <Skeleton key={i} className="h-20" />
          ))}
        </div>
      )}

      {error && <Failure text={error} onRetry={() => setTick((t) => t + 1)} />}

      {report && !error && (
        <div className={`transition-opacity ${loading ? "opacity-60" : ""}`} aria-busy={loading}>
          <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-5">
            <Tile
              label="Задачи"
              value={fmtInt(report.jobs.total)}
              sub={`готово ${fmtInt(report.jobs.done)} · идут ${fmtInt(report.jobs.open)}`}
            />
            <Tile
              label="Без результата"
              value={fmtInt(report.jobs.failed + report.jobs.nsfw + report.jobs.lost + report.jobs.canceled)}
              sub={`ошибка ${report.jobs.failed} · запрет ${report.jobs.nsfw} · потеряно ${report.jobs.lost} · отмена ${report.jobs.canceled}`}
            />
            <Tile label="Списано" value={creditsText(report.creditsCharged)} sub="за готовые работы" />
            <Tile
              label="Себестоимость"
              value={usdText(report.costUsd)}
              sub={`выручка ≈${usdText(report.revenueUsd)}`}
            />
            <Tile
              label="Маржа ≈"
              value={usdText(report.marginUsd)}
              sub={marginShare(report) ? `${marginShare(report)} от выручки` : "выручку не посчитать"}
            />
          </div>

          {used.length === 0 ? (
            <p className="mt-4 text-sm text-muted">За этот период задач не было.</p>
          ) : (
            <div className="mt-4 overflow-x-auto">
              <table className="w-full min-w-[640px] text-sm">
                <thead>
                  <tr className="border-b border-border text-left text-[11px] uppercase tracking-wide text-muted-2">
                    <th scope="col" className="py-2 pr-3 font-medium">
                      Инструмент
                    </th>
                    <th scope="col" className="px-2 py-2 text-right font-medium">
                      Задач
                    </th>
                    <th scope="col" className="px-2 py-2 text-right font-medium">
                      Готово
                    </th>
                    <th scope="col" className="px-2 py-2 text-right font-medium">
                      Кредиты
                    </th>
                    <th scope="col" className="px-2 py-2 text-right font-medium">
                      Выручка ≈
                    </th>
                    <th scope="col" className="px-2 py-2 text-right font-medium">
                      Себестоимость
                    </th>
                    <th scope="col" className="py-2 pl-2 text-right font-medium">
                      Маржа ≈
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {used.map((t) => {
                    const share = marginShare(t);
                    const negative = t.marginUsd !== null && Number(t.marginUsd) < 0;
                    return (
                      <tr key={t.id} className="border-b border-border last:border-0">
                        <td className="py-2 pr-3 text-foreground">{t.name}</td>
                        <td className="px-2 py-2 text-right tabular-nums">{fmtInt(t.jobs)}</td>
                        <td className="px-2 py-2 text-right tabular-nums text-muted">{fmtInt(t.done)}</td>
                        <td className="px-2 py-2 text-right tabular-nums">{creditsText(t.credits)}</td>
                        <td className="px-2 py-2 text-right tabular-nums text-muted">{usdText(t.revenueUsd)}</td>
                        <td className="px-2 py-2 text-right tabular-nums text-muted">{usdText(t.costUsd)}</td>
                        <td
                          className={`py-2 pl-2 text-right tabular-nums ${negative ? "text-status-fail" : "text-foreground"}`}
                        >
                          {usdText(t.marginUsd)}
                          {share && <span className="block text-[11px] text-muted-2">{share}</span>}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          <p className="mt-3 text-[11px] text-muted-2">
            Кредиты, себестоимость и маржа — только по готовым работам. Себестоимость — наша оценка по формуле
            инструмента в момент запуска; с фактическим списанием у исполнителя пока не сверяется. Выручка — списанные
            кредиты × цена самого дешёвого кредита сейчас
            {report.creditUsd ? ` (${usdText(report.creditUsd)})` : ""}, то есть оценка снизу.
          </p>
        </div>
      )}
    </section>
  );
}

/* ------------------------------------------------------------------ */
/* Журнал изменений                                                    */
/* ------------------------------------------------------------------ */

const LOG_PAGE = 20;

const fmtWhen = (iso: string): string => {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
};

/** Кто, когда и что поменял: режим, наценки, рубильники инструментов. */
export function LogCard({ tools, defaultPct, reload }: { tools: ToolRow[]; defaultPct: string; reload: number }) {
  const [tick, setTick] = useState(0);
  const [items, setItems] = useState<LogEntry[] | null>(null);
  const [loaded, setLoaded] = useState<{ key: string; error: string | null } | null>(null);
  const [shown, setShown] = useState(LOG_PAGE);

  const key = `${reload}|${tick}`;
  const loading = loaded?.key !== key;
  const error = loading ? null : (loaded?.error ?? null);

  useEffect(() => {
    let alive = true;
    (async () => {
      const res = await fetchData<unknown>(LOG_PATH, "GET", null, true);
      if (!alive) return;
      const parsed = res.ok ? parseLog(res.data) : null;
      if (!parsed) {
        setLoaded({ key, error: res.ok ? "Сервер ответил непонятно." : errorText(res, "Журнал не загрузился") });
        return;
      }
      setItems(parsed);
      setLoaded({ key, error: null });
    })();
    return () => {
      alive = false;
    };
  }, [key]);

  const names = useMemo(() => Object.fromEntries(tools.map((t) => [t.id, t.name])), [tools]);

  return (
    <section className={`${CARD} p-5`}>
      <CardHeader icon={<FiClock className={ICON} aria-hidden />} title="Журнал изменений">
        <button
          type="button"
          onClick={() => setTick((t) => t + 1)}
          disabled={loading}
          className={btn("plain")}
          aria-label="Обновить журнал"
        >
          <FiRefreshCw className={`h-3.5 w-3.5 ${loading ? "motion-safe:animate-spin" : ""}`} aria-hidden />
          Обновить
        </button>
      </CardHeader>

      {!items && loading && (
        <div className="mt-4 space-y-2" aria-busy="true">
          <Skeleton className="h-12" />
          <Skeleton className="h-12" />
        </div>
      )}

      {error && <Failure text={error} onRetry={() => setTick((t) => t + 1)} />}

      {items && !error && items.length === 0 && <p className="mt-4 text-sm text-muted">Изменений пока не было.</p>}

      {items && !error && items.length > 0 && (
        <>
          <ol className="mt-4 divide-y divide-border">
            {items.slice(0, shown).map((entry, i) => {
              const lines = logLines(entry, { names, defaultPct });
              return (
                <li key={`${entry.at}-${i}`} className="flex flex-col gap-1 py-3 sm:flex-row sm:gap-4">
                  <div className="shrink-0 text-xs text-muted sm:w-44">
                    <time dateTime={entry.at} className="tabular-nums">
                      {fmtWhen(entry.at)}
                    </time>
                    <div className="break-all text-muted-2">{entry.actor || "—"}</div>
                  </div>
                  <ul className="min-w-0 flex-1 space-y-0.5 text-sm">
                    {lines.length === 0 && <li className="text-muted-2">—</li>}
                    {lines.map((line, j) => (
                      <li key={j} className="break-words">
                        <span className="text-muted">{line.label}:</span>{" "}
                        <span className="text-muted-2 line-through decoration-muted-2/60">{line.before}</span>
                        <span className="text-muted-2"> → </span>
                        <span className="text-foreground">{line.after}</span>
                      </li>
                    ))}
                  </ul>
                </li>
              );
            })}
          </ol>
          {items.length > shown && (
            <button type="button" onClick={() => setShown((n) => n + LOG_PAGE)} className={`${btn("plain")} mt-2`}>
              Показать ещё ({items.length - shown})
            </button>
          )}
        </>
      )}
    </section>
  );
}
