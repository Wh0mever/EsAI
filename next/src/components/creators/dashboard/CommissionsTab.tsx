"use client";

import { useCallback, useState } from "react";
import { useTranslation } from "react-i18next";
import ErrorNote from "@/components/creators/shared/ErrorNote";
import LoadMore from "@/components/creators/shared/LoadMore";
import Money from "@/components/creators/shared/Money";
import StatusBadge from "@/components/creators/shared/StatusBadge";
import { listCommissions } from "@/lib/creators/api";
import { fmtDate, fmtPercent } from "@/lib/creators/format";
import { commissionStatusKey } from "@/lib/creators/labels";
import type { Commission, CommissionStatus } from "@/lib/creators/types";
import { Empty, ListSkeleton, Pair } from "./ui";
import { usePagedList } from "./usePagedList";

type Filter = "" | CommissionStatus;

/**
 * «Комиссии» (ТЗ п.34): начисления с оплат рефералов. Суммы и процент — как
 * прислал сервер (комиссия с шестью знаками), страница их не пересчитывает.
 * Покупатель показан маской.
 */
export default function CommissionsTab() {
  const { t, i18n } = useTranslation("creators", { useSuspense: false });
  const lang = i18n.language;
  const [filter, setFilter] = useState<Filter>("");
  const fetchPage = useCallback((page: number) => listCommissions({ status: filter || undefined, page }), [filter]);
  const list = usePagedList<Commission>(fetchPage);

  const chips: { key: Filter; label: string }[] = [
    { key: "", label: t("dash.comm.filter_all", { defaultValue: "Все" }) },
    { key: "accrued", label: t("dash.comm.filter_accrued", { defaultValue: "Начислены" }) },
    { key: "held", label: t("dash.comm.filter_held", { defaultValue: "На проверке" }) },
    { key: "reversed", label: t("dash.comm.filter_reversed", { defaultValue: "Отменены" }) },
    // Аннулированные администратором — отдельный статус сервера (void), в «Отменены» их нет.
    { key: "void", label: t("dash.comm.filter_void", { defaultValue: "Аннулированы" }) },
  ];

  const head = {
    date: t("dash.comm.col_date", { defaultValue: "Дата" }),
    buyer: t("dash.comm.col_buyer", { defaultValue: "Покупатель" }),
    base: t("dash.comm.col_base", { defaultValue: "Сумма заказа" }),
    amount: t("dash.comm.col_amount", { defaultValue: "Комиссия" }),
    status: t("dash.comm.col_status", { defaultValue: "Статус" }),
  };

  // Начисленная комиссия либо ещё в холде (до даты), либо уже доступна к выводу.
  // Отменённая: «возврат платежа» пишем, только если сервер назвал причиной возврат.
  const status = (row: Commission) => {
    const key = commissionStatusKey(row);
    if (key === "hold" && row.available_at) {
      return (
        <span className="inline-flex max-w-full items-center rounded-full border border-status-wait/30 bg-status-wait/10 px-2.5 py-0.5 text-xs font-medium text-status-wait">
          {t("dash.comm.hold_until", { defaultValue: "В холде до {{date}}", date: fmtDate(row.available_at, lang) })}
        </span>
      );
    }
    return <StatusBadge kind="commission" status={key} />;
  };

  return (
    <div className="flex flex-col gap-3">
      <div className="-mx-4 flex gap-1.5 overflow-x-auto px-4 [scrollbar-width:none]" role="group">
        {chips.map((chip) => (
          <button
            key={chip.key || "all"}
            type="button"
            aria-pressed={filter === chip.key}
            onClick={() => setFilter(chip.key)}
            className={`shrink-0 cursor-pointer whitespace-nowrap rounded-full border px-3 py-1.5 text-xs font-medium transition-colors ${
              filter === chip.key
                ? "border-accent bg-accent text-on-accent"
                : "border-border bg-surface text-muted hover:text-foreground"
            }`}
          >
            {chip.label}
          </button>
        ))}
      </div>

      {list.loading ? (
        <ListSkeleton />
      ) : list.error ? (
        <ErrorNote error={list.error} onRetry={list.reload} />
      ) : list.rows.length === 0 ? (
        <Empty>
          {filter
            ? t("dash.comm.empty_filtered", { defaultValue: "Комиссий с таким статусом нет." })
            : t("dash.comm.empty", {
                defaultValue: "Комиссий пока нет. Они появятся после первой оплаты вашего реферала.",
              })}
        </Empty>
      ) : (
        <>
          {/* Телефон и узкий планшет: карточки */}
          <ul className="flex flex-col gap-2 md:hidden">
            {list.rows.map((row) => (
              <li key={row.id} className="rounded-2xl border border-border bg-surface p-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <Money value={row.amount_usdt} className="text-base font-bold text-foreground" />
                  {status(row)}
                </div>
                <dl className="mt-2 flex flex-col gap-1.5">
                  <Pair label={head.date}>{fmtDate(row.date, lang)}</Pair>
                  <Pair label={head.buyer}>
                    <span className="break-all">{row.buyer}</span>
                  </Pair>
                  <Pair label={head.base}>
                    <Money value={row.base_usdt} />
                  </Pair>
                  <Pair label="%">
                    <span className="tabular-nums">{fmtPercent(row.percent)}%</span>
                  </Pair>
                </dl>
              </li>
            ))}
          </ul>

          {/* Шире: таблица */}
          <div className="hidden overflow-hidden rounded-2xl border border-border bg-surface md:block">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-xs text-muted">
                  <th scope="col" className="px-3 py-3 font-medium">{head.date}</th>
                  <th scope="col" className="px-3 py-3 font-medium">{head.buyer}</th>
                  <th scope="col" className="px-3 py-3 text-right font-medium">{head.base}</th>
                  <th scope="col" className="px-3 py-3 text-right font-medium">%</th>
                  <th scope="col" className="px-3 py-3 text-right font-medium">{head.amount}</th>
                  <th scope="col" className="px-3 py-3 font-medium">{head.status}</th>
                </tr>
              </thead>
              <tbody>
                {list.rows.map((row) => (
                  <tr key={row.id} className="border-b border-border last:border-b-0">
                    <td className="whitespace-nowrap px-3 py-3 text-foreground">{fmtDate(row.date, lang)}</td>
                    <td className="break-all px-3 py-3 text-foreground">{row.buyer}</td>
                    <td className="px-3 py-3 text-right text-foreground">
                      <Money value={row.base_usdt} />
                    </td>
                    <td className="px-3 py-3 text-right tabular-nums text-foreground">{fmtPercent(row.percent)}%</td>
                    <td className="px-3 py-3 text-right font-semibold text-foreground">
                      <Money value={row.amount_usdt} />
                    </td>
                    <td className="px-3 py-3">{status(row)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {list.moreError && <ErrorNote error={list.moreError} />}
          <LoadMore shown={list.rows.length} total={list.count} loading={list.loadingMore} onMore={list.loadMore} />
        </>
      )}
    </div>
  );
}
