"use client";

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import ErrorNote from "@/components/creators/shared/ErrorNote";
import { getCredits } from "@/lib/creators/api";
import { fmtDate, fmtInt } from "@/lib/creators/format";
import { creditCategoryLabel } from "@/lib/creators/labels";
import type { CrError, Credits, CreditGrant, CreditSpend } from "@/lib/creators/types";
import { Empty, ListSkeleton } from "./ui";

type Row = CreditGrant | CreditSpend;
/** Ответ вместе с тем, для какого запроса он пришёл (с расходами или без) и какой попытки. */
type Loaded = { full: boolean; attempt: number; data: Credits | null; error: CrError | null };

/** Сервер отдаёт историю без страниц — последние 100 строк. */
const HISTORY_LIMIT = 100;

const isSpend = (row: Row): row is CreditSpend => row.kind === "spend";

/**
 * «Creator Credits» (ТЗ п.19, 22): выдано, осталось, использовано и история.
 * Кредиты выдаёт только администратор и только вручную — кнопки «запросить»
 * нет. Вывести, перевести или обменять их нельзя, поэтому таких действий в
 * разделе тоже нет.
 */
export default function CreditsTab() {
  const { t, i18n } = useTranslation("creators", { useSuspense: false });
  const lang = i18n.language;
  const [full, setFull] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<Loaded | null>(null);

  useEffect(() => {
    let alive = true;
    (async () => {
      const res = await getCredits(full);
      if (!alive) return;
      setState(res.ok ? { full, attempt, data: res.data, error: null } : { full, attempt, data: null, error: res.error });
    })();
    return () => {
      alive = false;
    };
  }, [full, attempt]);

  const fresh = state && state.full === full && state.attempt === attempt ? state : null;
  // Пока догружается история с расходами, три числа сверху остаются на месте.
  const totals = fresh?.data ?? state?.data ?? null;

  const head = {
    date: t("dash.credits.col_date", { defaultValue: "Дата" }),
    amount: t("dash.credits.col_amount", { defaultValue: "Количество" }),
    reason: t("dash.credits.col_reason", { defaultValue: "Причина" }),
    note: t("dash.credits.col_note", { defaultValue: "Примечание" }),
  };
  const spentLabel = t("dash.credits.spent", { defaultValue: "Использовано" });

  const amount = (row: Row) => (
    <span className={`font-semibold tabular-nums ${isSpend(row) ? "text-muted" : "text-status-ok"}`}>
      {/* У расхода минус уже в числе, выдаче ставим плюс. */}
      {isSpend(row) ? fmtInt(row.amount, lang) : `+${fmtInt(row.amount, lang)}`}
    </span>
  );
  const reason = (row: Row) => (isSpend(row) ? spentLabel : creditCategoryLabel(t, row.category, row.category_label));
  const note = (row: Row) =>
    isSpend(row)
      ? t("dash.credits.remaining_after", { defaultValue: "Остаток {{n}}", n: fmtInt(row.remaining_after, lang) })
      : row.note;
  const rowKey = (row: Row) => `${isSpend(row) ? "spend" : "grant"}:${row.id}`;

  return (
    <div className="flex flex-col gap-3">
      {totals && (
        <div className="grid grid-cols-3 gap-1.5 sm:gap-3">
          {(
            [
              [t("dash.credits.granted", { defaultValue: "Выдано" }), totals.granted],
              [t("dash.credits.remaining", { defaultValue: "Осталось" }), totals.remaining],
              [spentLabel, totals.spent],
            ] as const
          ).map(([label, value]) => (
            <div key={label} className="min-w-0 rounded-2xl border border-border bg-surface px-3 py-2.5 sm:p-4">
              <div className="break-words text-xs text-muted">{label}</div>
              <div className="truncate text-lg font-bold tabular-nums text-foreground sm:text-2xl">
                {fmtInt(value, lang)}
              </div>
            </div>
          ))}
        </div>
      )}

      <p className="text-sm text-muted">
        {t("dash.credits.about", {
          defaultValue:
            "Creator Credits — кредиты для создания контента в EsAI. Их нельзя вывести, перевести другому пользователю или обменять на USDT.",
        })}
      </p>

      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-lg font-semibold text-foreground">{t("dash.credits.history", { defaultValue: "История" })}</h2>
        <label className="inline-flex cursor-pointer items-center gap-2 text-sm text-foreground">
          <input
            type="checkbox"
            checked={full}
            onChange={(e) => setFull(e.target.checked)}
            className="h-4 w-4 cursor-pointer accent-[var(--accent)]"
          />
          {t("dash.credits.show_spends", { defaultValue: "Показать расходы" })}
        </label>
      </div>

      {!fresh ? (
        <ListSkeleton />
      ) : fresh.error || !fresh.data ? (
        fresh.error && <ErrorNote error={fresh.error} onRetry={() => setAttempt((n) => n + 1)} />
      ) : fresh.data.results.length === 0 ? (
        <Empty>
          {t("dash.credits.empty", {
            defaultValue: "Начислений пока нет. Creator Credits выдаёт администратор EsAI.",
          })}
        </Empty>
      ) : (
        <>
          {/* Телефон: карточки */}
          <ul className="flex flex-col gap-2 sm:hidden">
            {fresh.data.results.map((row) => (
              <li key={rowKey(row)} className="rounded-2xl border border-border bg-surface p-4">
                <div className="flex items-baseline justify-between gap-3">
                  <span className="min-w-0 break-words text-sm font-medium text-foreground">{reason(row)}</span>
                  <span className="shrink-0 text-base">{amount(row)}</span>
                </div>
                {note(row) && <p className="mt-1 break-words text-sm text-muted">{note(row)}</p>}
                <div className="mt-1 text-xs text-muted-2">{fmtDate(row.date, lang)}</div>
              </li>
            ))}
          </ul>

          {/* Шире: таблица (ТЗ п.22) */}
          <div className="hidden overflow-hidden rounded-2xl border border-border bg-surface sm:block">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-xs text-muted">
                  <th scope="col" className="px-4 py-3 font-medium">{head.date}</th>
                  <th scope="col" className="px-4 py-3 text-right font-medium">{head.amount}</th>
                  <th scope="col" className="px-4 py-3 font-medium">{head.reason}</th>
                  <th scope="col" className="px-4 py-3 font-medium">{head.note}</th>
                </tr>
              </thead>
              <tbody>
                {fresh.data.results.map((row) => (
                  <tr key={rowKey(row)} className="border-b border-border align-top last:border-b-0">
                    <td className="whitespace-nowrap px-4 py-3 text-foreground">{fmtDate(row.date, lang)}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-right">{amount(row)}</td>
                    <td className="px-4 py-3 text-foreground">{reason(row)}</td>
                    <td className="break-words px-4 py-3 text-muted">{note(row)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {fresh.data.count >= HISTORY_LIMIT && (
            <p className="text-xs text-muted">
              {t("dash.credits.limit_note", {
                defaultValue: "Показаны последние {{n}} записей.",
                n: fmtInt(HISTORY_LIMIT, lang),
              })}
            </p>
          )}
        </>
      )}
    </div>
  );
}
