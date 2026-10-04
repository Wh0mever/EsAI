"use client";

import { useCallback } from "react";
import { useTranslation } from "react-i18next";
import ErrorNote from "@/components/creators/shared/ErrorNote";
import LoadMore from "@/components/creators/shared/LoadMore";
import Money from "@/components/creators/shared/Money";
import { listReferrals } from "@/lib/creators/api";
import { fmtDate, fmtInt } from "@/lib/creators/format";
import { sourceLabel } from "@/lib/creators/labels";
import type { Referral } from "@/lib/creators/types";
import { Empty, ListSkeleton, Pair } from "./ui";
import { usePagedList } from "./usePagedList";

/**
 * «Рефералы» (ТЗ п.34): приглашённые люди. Кабинет получает только маску
 * пользователя — ни почты, ни id. Заказы, продажи и комиссию считает сервер;
 * привязку здесь изменить нельзя — это делает только администратор.
 */
export default function ReferralsTab() {
  const { t, i18n } = useTranslation("creators", { useSuspense: false });
  const lang = i18n.language;
  const fetchPage = useCallback((page: number) => listReferrals({ page }), []);
  const list = usePagedList<Referral>(fetchPage);

  const head = {
    user: t("dash.refs.col_user", { defaultValue: "Пользователь" }),
    date: t("dash.refs.col_date", { defaultValue: "Дата" }),
    source: t("dash.refs.col_source", { defaultValue: "Источник" }),
    paying: t("dash.refs.col_paying", { defaultValue: "Платит" }),
    orders: t("dash.refs.col_orders", { defaultValue: "Заказы" }),
    sales: t("dash.refs.col_sales", { defaultValue: "Продажи" }),
    commission: t("dash.refs.col_commission", { defaultValue: "Комиссия" }),
  };
  const yes = t("dash.refs.paying_yes", { defaultValue: "Да" });
  const no = t("dash.refs.paying_no", { defaultValue: "Нет" });

  const paying = (row: Referral) =>
    row.is_paying ? (
      <span className="font-semibold text-status-ok" role="img" aria-label={yes}>
        ✓
      </span>
    ) : (
      <span className="text-muted" role="img" aria-label={no}>
        —
      </span>
    );

  if (list.loading) return <ListSkeleton />;
  if (list.error) return <ErrorNote error={list.error} onRetry={list.reload} />;
  if (list.rows.length === 0) {
    return (
      <Empty>{t("dash.refs.empty", { defaultValue: "Пока никто не зарегистрировался по вашей ссылке." })}</Empty>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {/* Телефон и узкий планшет: карточки */}
      <ul className="flex flex-col gap-2 md:hidden">
        {list.rows.map((row) => (
          <li key={row.id} className="rounded-2xl border border-border bg-surface p-4">
            <div className="flex items-baseline justify-between gap-3">
              <span className="min-w-0 break-all text-sm font-semibold text-foreground">{row.user}</span>
              <span className="shrink-0 text-xs text-muted-2">{fmtDate(row.bound_at, lang)}</span>
            </div>
            <dl className="mt-2 flex flex-col gap-1.5">
              <Pair label={head.source}>{sourceLabel(t, row.source)}</Pair>
              <Pair label={head.paying}>{paying(row)}</Pair>
              <Pair label={head.orders}>
                <span className="tabular-nums">{fmtInt(row.orders, lang)}</span>
              </Pair>
              <Pair label={head.sales}>
                <Money value={row.sales_usdt} />
              </Pair>
              <Pair label={head.commission}>
                <Money value={row.commission_usdt} className="font-semibold" />
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
              <th scope="col" className="px-3 py-3 font-medium">{head.user}</th>
              <th scope="col" className="px-3 py-3 font-medium">{head.date}</th>
              <th scope="col" className="px-3 py-3 font-medium">{head.source}</th>
              <th scope="col" className="px-3 py-3 text-center font-medium">{head.paying}</th>
              <th scope="col" className="px-3 py-3 text-right font-medium">{head.orders}</th>
              <th scope="col" className="px-3 py-3 text-right font-medium">{head.sales}</th>
              <th scope="col" className="px-3 py-3 text-right font-medium">{head.commission}</th>
            </tr>
          </thead>
          <tbody>
            {list.rows.map((row) => (
              <tr key={row.id} className="border-b border-border last:border-b-0">
                <td className="break-all px-3 py-3 font-medium text-foreground">{row.user}</td>
                <td className="whitespace-nowrap px-3 py-3 text-foreground">{fmtDate(row.bound_at, lang)}</td>
                <td className="px-3 py-3 text-foreground">{sourceLabel(t, row.source)}</td>
                <td className="px-3 py-3 text-center">{paying(row)}</td>
                <td className="px-3 py-3 text-right tabular-nums text-foreground">{fmtInt(row.orders, lang)}</td>
                <td className="px-3 py-3 text-right text-foreground">
                  <Money value={row.sales_usdt} />
                </td>
                <td className="px-3 py-3 text-right font-semibold text-foreground">
                  <Money value={row.commission_usdt} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {list.moreError && <ErrorNote error={list.moreError} />}
      <LoadMore shown={list.rows.length} total={list.count} loading={list.loadingMore} onMore={list.loadMore} />
    </div>
  );
}
