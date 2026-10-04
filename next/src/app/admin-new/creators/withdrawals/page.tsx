"use client";

import { useState } from "react";
import { adminWithdrawals } from "@/lib/creators/adminApi";
import type { WithdrawalStatus } from "@/lib/creators/types";
import WithdrawalRow, { WITHDRAWAL_COLUMNS } from "../_shared/WithdrawalRow";
import {
  Chips,
  EmptyRow,
  ErrorBox,
  IdParamChip,
  MoreButton,
  PageTitle,
  Skeleton,
  TH,
  THEAD_ROW,
  TableWrap,
  nf,
  useIdParam,
} from "../_shared/ui";
import { usePagedList } from "../_shared/usePagedList";

type Filter = WithdrawalStatus | "all";

const FILTERS: { key: Filter; label: string }[] = [
  { key: "review", label: "На проверке" },
  { key: "approved", label: "Одобренные" },
  { key: "paid", label: "Выплаченные" },
  { key: "rejected", label: "Отклонённые" },
  { key: "all", label: "Все" },
];

/**
 * Заявки на вывод (ТЗ п.26). Панель денег не отправляет: администратор сам
 * переводит USDT (TRC20) на адрес из заявки и записывает сюда TXID.
 */
export default function AdminCreatorsWithdrawalsPage() {
  const creator = useIdParam("creator");
  const [filter, setFilter] = useState<Filter>("review");

  const list = usePagedList(adminWithdrawals, { status: filter === "all" ? undefined : filter, creator });

  return (
    <div className="space-y-4">
      <PageTitle
        title="Выплаты"
        hint={`Только USDT, сеть TRC20, комиссия с выплаты не удерживается. Перевод делается вручную, сюда вносится TXID. Найдено: ${nf(list.count)}.`}
      />

      <div className="flex flex-wrap items-center gap-2">
        <Chips options={FILTERS} value={filter} onChange={setFilter} />
        <IdParamChip name="creator" label="Creator" />
      </div>

      {list.loading ? (
        <Skeleton />
      ) : list.error ? (
        <ErrorBox error={list.error} />
      ) : (
        <TableWrap minWidth={1280}>
          <thead>
            <tr className={THEAD_ROW}>
              {WITHDRAWAL_COLUMNS.map((title) => (
                <th key={title} className={TH}>
                  {title}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {list.rows.length === 0 && <EmptyRow colSpan={WITHDRAWAL_COLUMNS.length}>Заявок на вывод нет.</EmptyRow>}
            {list.rows.map((row) => (
              <WithdrawalRow key={row.id} row={row} onChange={list.replace} />
            ))}
          </tbody>
        </TableWrap>
      )}

      <MoreButton
        shown={list.rows.length}
        total={list.count}
        loading={list.loadingMore}
        onMore={list.more}
        error={list.moreError}
      />
    </div>
  );
}
