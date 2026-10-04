"use client";

import { useState } from "react";
import Link from "next/link";
import { adminLog } from "@/lib/creators/adminApi";
import LogChanges from "../_shared/LogChanges";
import { LOG_ACTIONS, logActionLabel } from "../_shared/labels";
import {
  CreatorLink,
  dash,
  dt,
  EmptyRow,
  ErrorBox,
  IdParamChip,
  INPUT_SM,
  MoreButton,
  nf,
  PageTitle,
  ROW,
  Skeleton,
  TableWrap,
  TD,
  TH,
  THEAD_ROW,
  useIdParam,
} from "../_shared/ui";
import { usePagedList } from "../_shared/usePagedList";

/** Журнал ручных действий (ТЗ п.35). Только чтение: записи пишет сервер в той же транзакции, что и действие. */
export default function AdminCreatorsLogPage() {
  const creator = useIdParam("creator");
  const actor = useIdParam("actor");
  const [action, setAction] = useState("");

  const list = usePagedList(adminLog, { creator, action, actor });

  return (
    <div className="space-y-4">
      <PageTitle
        title="Журнал"
        hint={`Кто, что и когда сделал вручную. Записи нельзя изменить или удалить. Найдено: ${nf(list.count)}.`}
      />

      <div className="flex flex-wrap items-center gap-2">
        <select
          value={action}
          onChange={(e) => setAction(e.target.value)}
          className={`${INPUT_SM} max-w-full`}
          aria-label="Действие"
        >
          <option value="">Все действия</option>
          {LOG_ACTIONS.map((item) => (
            <option key={item.key} value={item.key}>
              {item.label}
            </option>
          ))}
        </select>
        <IdParamChip name="creator" label="Creator" />
        <IdParamChip name="actor" label="Сотрудник" />
      </div>

      {list.loading ? (
        <Skeleton />
      ) : list.error ? (
        <ErrorBox error={list.error} />
      ) : (
        <TableWrap minWidth={1180}>
          <thead>
            <tr className={THEAD_ROW}>
              <th className={TH}>Дата</th>
              <th className={TH}>Кто</th>
              <th className={TH}>Действие</th>
              <th className={TH}>Объект</th>
              <th className={TH}>Creator</th>
              <th className={TH}>Было → стало</th>
              <th className={TH}>Причина</th>
              <th className={TH}>IP</th>
            </tr>
          </thead>
          <tbody>
            {list.rows.length === 0 && <EmptyRow colSpan={8}>Записей нет.</EmptyRow>}
            {list.rows.map((row) => (
              <tr key={row.id} className={`${ROW} hover:bg-surface-2`}>
                <td className={`${TD} whitespace-nowrap text-muted`}>{dt(row.created_at)}</td>
                <td className={`${TD} break-all`}>
                  <Link
                    href={`/admin-new/creators/log?actor=${row.actor_id}`}
                    className="hover:text-accent hover:underline"
                    title="Все действия этого сотрудника"
                  >
                    {row.actor_email || `id ${row.actor_id}`}
                  </Link>
                </td>
                <td className={TD}>
                  <div>{logActionLabel(row.action)}</div>
                  <div className="font-mono text-[11px] text-muted-2">{row.action}</div>
                </td>
                <td className={`${TD} break-all text-xs text-muted`}>
                  {row.target_type ? `${row.target_type} #${row.target_id}` : "—"}
                </td>
                <td className={TD}>
                  {row.creator_id ? <CreatorLink id={row.creator_id} name={`#${row.creator_id}`} /> : "—"}
                </td>
                <td className={`${TD} max-w-[320px]`}>
                  <LogChanges before={row.before} after={row.after} />
                </td>
                <td className={`${TD} max-w-[240px] whitespace-pre-wrap break-words text-muted`}>{dash(row.reason)}</td>
                <td className={`${TD} whitespace-nowrap font-mono text-xs text-muted-2`}>{dash(row.ip)}</td>
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
