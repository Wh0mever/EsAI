"use client";

import { useState } from "react";
import { adminPublications } from "@/lib/creators/adminApi";
import { NETWORK_RU } from "@/lib/creators/labels";
import type { PublicationStatus } from "@/lib/creators/types";
import { PUBLICATION_STATUS, labelFrom } from "../_shared/labels";
import PublicationActions from "../_shared/PublicationActions";
import {
  Chips,
  CreatorLink,
  EmptyRow,
  ErrorBox,
  ExtLink,
  IdParamChip,
  MoreButton,
  PageTitle,
  ROW,
  Skeleton,
  StatusPill,
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

type Filter = PublicationStatus | "all";

const FILTERS: { key: Filter; label: string }[] = [
  { key: "review", label: "На проверке" },
  { key: "approved", label: "Подтверждённые" },
  { key: "rejected", label: "Отклонённые" },
  { key: "all", label: "Все" },
];

/** Публикации креаторов на проверку (ТЗ п.17). В прогресс уровня идут только подтверждённые. */
export default function AdminCreatorsPublicationsPage() {
  const creator = useIdParam("creator");
  const [filter, setFilter] = useState<Filter>("review");

  const list = usePagedList(adminPublications, { status: filter === "all" ? undefined : filter, creator });

  return (
    <div className="space-y-4">
      <PageTitle
        title="Публикации"
        hint={`Откройте ссылку, убедитесь, что публикация настоящая, и подтвердите или отклоните её. Найдено: ${nf(list.count)}.`}
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
        <TableWrap minWidth={980}>
          <thead>
            <tr className={THEAD_ROW}>
              <th className={TH}>Дата</th>
              <th className={TH}>Creator</th>
              <th className={TH}>Соцсеть</th>
              <th className={TH}>Ссылка</th>
              <th className={TH}>Описание</th>
              <th className={TH}>Статус</th>
              <th className={TH}>Действия</th>
            </tr>
          </thead>
          <tbody>
            {list.rows.length === 0 && <EmptyRow colSpan={7}>Публикаций нет.</EmptyRow>}
            {list.rows.map((row) => (
              <tr key={row.id} className={`${ROW} hover:bg-surface-2`}>
                <td className={`${TD} whitespace-nowrap text-muted`}>{dt(row.created_at)}</td>
                <td className={TD}>
                  <CreatorLink id={row.creator_id} name={row.creator_name} />
                </td>
                <td className={`${TD} whitespace-nowrap`}>{labelFrom(NETWORK_RU, row.network)}</td>
                <td className={`${TD} max-w-[260px]`}>
                  <ExtLink href={row.url}>Открыть</ExtLink>
                  <div className="mt-0.5 break-all text-xs text-muted-2">{row.url}</div>
                </td>
                <td className={`${TD} max-w-[240px] whitespace-pre-wrap break-words text-muted`}>
                  {dash(row.description)}
                </td>
                <td className={TD}>
                  <StatusPill table={PUBLICATION_STATUS} status={row.status} />
                  {row.decided_at && (
                    <div className="mt-1 text-xs text-muted-2">
                      {dt(row.decided_at)}
                      <br />
                      {dash(row.decided_by_email)}
                    </div>
                  )}
                  {row.reject_reason && (
                    <div className="mt-1 max-w-[220px] break-words text-xs text-rose-300">Причина: {row.reject_reason}</div>
                  )}
                </td>
                <td className={TD}>
                  <PublicationActions row={row} onChange={list.replace} />
                </td>
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
