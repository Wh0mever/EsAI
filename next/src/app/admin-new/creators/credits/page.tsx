"use client";

import { adminCredits } from "@/lib/creators/adminApi";
import { CREDIT_CATEGORY_RU } from "@/lib/creators/labels";
import {
  CreatorLink,
  EmptyRow,
  ErrorBox,
  IdParamChip,
  MoreButton,
  PageTitle,
  ROW,
  Skeleton,
  TD,
  TH,
  THEAD_ROW,
  TableWrap,
  dash,
  dt,
  nf,
  useIdParam,
} from "../_shared/ui";
import { usePagedList } from "../_shared/usePagedList";

/**
 * Все выдачи Creator Credits (ТЗ п.22). Кредиты выдаёт только главный
 * администратор и только вручную — кнопка «Начислить» в профиле креатора.
 */
export default function AdminCreatorsCreditsPage() {
  const creator = useIdParam("creator");
  const list = usePagedList(adminCredits, { creator });

  return (
    <div className="space-y-4">
      <PageTitle
        title="Creator Credits"
        hint={`История начислений, новые сверху. Начислить кредиты можно в профиле креатора. Найдено: ${nf(list.count)}.`}
      />

      <div className="flex flex-wrap items-center gap-2">
        <IdParamChip name="creator" label="Creator" />
      </div>

      {list.loading ? (
        <Skeleton />
      ) : list.error ? (
        <ErrorBox error={list.error} />
      ) : (
        <TableWrap minWidth={900}>
          <thead>
            <tr className={THEAD_ROW}>
              <th className={TH}>Дата</th>
              <th className={TH}>Creator</th>
              <th className={TH}>Количество</th>
              <th className={TH}>Причина</th>
              <th className={TH}>Примечание</th>
              <th className={TH}>Кто выдал</th>
              <th className={TH}>Баланс после</th>
            </tr>
          </thead>
          <tbody>
            {list.rows.length === 0 && <EmptyRow colSpan={7}>Начислений пока не было.</EmptyRow>}
            {list.rows.map((row) => (
              <tr key={row.id} className={`${ROW} hover:bg-surface-2`}>
                <td className={`${TD} whitespace-nowrap text-muted`}>{dt(row.date)}</td>
                <td className={TD}>
                  {row.creator_id ? (
                    <CreatorLink id={row.creator_id} name={row.creator_name} />
                  ) : (
                    <span className="text-muted-2" title="Выдача перенесена при слиянии аккаунтов: у получателя нет профиля креатора">
                      нет профиля
                    </span>
                  )}
                </td>
                <td className={`${TD} whitespace-nowrap font-medium text-status-ok`}>+{nf(row.amount)}</td>
                <td className={TD}>{CREDIT_CATEGORY_RU[row.category || ""] ?? dash(row.category_label)}</td>
                <td className={`${TD} max-w-[280px] whitespace-pre-wrap break-words text-muted`}>{dash(row.note)}</td>
                <td className={`${TD} break-all`}>{dash(row.by_email)}</td>
                <td className={`${TD} whitespace-nowrap`}>{row.balance_after === undefined ? "—" : nf(row.balance_after)}</td>
              </tr>
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
