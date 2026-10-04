"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Money from "@/components/creators/shared/Money";
import { adminCreators } from "@/lib/creators/adminApi";
import { fmtPercent } from "@/lib/creators/format";
import type { CreatorStatus } from "@/lib/creators/types";
import { CREATOR_STATUS } from "../_shared/labels";
import {
  Badge,
  Chips,
  CreatorLink,
  dash,
  EmptyRow,
  ErrorBox,
  INPUT_SM,
  MoreButton,
  nf,
  PageTitle,
  ROW,
  SearchForm,
  Skeleton,
  StatusPill,
  TableWrap,
  TD,
  TH,
  THEAD_ROW,
  ToggleChip,
} from "../_shared/ui";
import { useLevels } from "../_shared/useLevels";
import { usePagedList } from "../_shared/usePagedList";

type Filter = CreatorStatus | "all";

const FILTERS: { key: Filter; label: string }[] = [
  { key: "all", label: "Все" },
  { key: "active", label: "Активные" },
  { key: "blocked", label: "Заблокированные" },
];

/** Все креаторы (ТЗ п.30). Строка ведёт в профиль. */
export default function AdminCreatorsListPage() {
  const router = useRouter();
  const [filter, setFilter] = useState<Filter>("all");
  const [level, setLevel] = useState("");
  const [ready, setReady] = useState(false);
  const [q, setQ] = useState("");
  const { levels } = useLevels();

  const list = usePagedList(adminCreators, {
    status: filter === "all" ? undefined : filter,
    level,
    q,
    ready,
  });

  return (
    <div className="space-y-4">
      <PageTitle title="Все Creators" hint={`Найдено: ${nf(list.count)}. Нажмите на строку, чтобы открыть профиль.`} />

      <div className="flex flex-wrap items-center gap-2">
        <Chips options={FILTERS} value={filter} onChange={setFilter} />
        <select
          value={level}
          onChange={(e) => setLevel(e.target.value)}
          className={INPUT_SM}
          aria-label="Уровень"
        >
          <option value="">Все уровни</option>
          {(levels || []).map((item) => (
            <option key={item.key} value={item.key}>
              {item.title}
            </option>
          ))}
        </select>
        <ToggleChip on={ready} onChange={setReady}>
          Условия уровня выполнены
        </ToggleChip>
        <SearchForm placeholder="Имя, email, username или промокод" onSearch={setQ} />
      </div>

      {ready && (
        <p className="text-xs text-muted-2">
          Это подсказка, кого пора повысить. Уровень сам не меняется — его назначает главный администратор в профиле.
        </p>
      )}

      {list.loading ? (
        <Skeleton />
      ) : list.error ? (
        <ErrorBox error={list.error} />
      ) : (
        <TableWrap minWidth={1180}>
          <thead>
            <tr className={THEAD_ROW}>
              <th className={TH}>Имя</th>
              <th className={TH}>Username</th>
              <th className={TH}>Уровень</th>
              <th className={TH}>Комиссия</th>
              <th className={TH}>Переходы</th>
              <th className={TH}>Регистрации</th>
              <th className={TH}>Платящие</th>
              <th className={TH}>Продажи</th>
              <th className={TH}>Заработок</th>
              <th className={TH}>Creator Credits</th>
              <th className={TH}>Статус</th>
            </tr>
          </thead>
          <tbody>
            {list.rows.length === 0 && <EmptyRow colSpan={11}>Никого не найдено.</EmptyRow>}
            {list.rows.map((row) => (
              <tr
                key={row.id}
                className={`${ROW} cursor-pointer hover:bg-surface-2`}
                onClick={() => router.push(`/admin-new/creators/${row.id}`)}
              >
                <td className={TD}>
                  <span onClick={(e) => e.stopPropagation()}>
                    <CreatorLink id={row.id} name={row.display_name} />
                  </span>
                  <div className="mt-0.5 text-xs text-muted-2">
                    Промокод: <span className="font-mono">{dash(row.code)}</span>
                  </div>
                </td>
                <td className={TD}>
                  <div className="break-all">{dash(row.username)}</div>
                  <div className="break-all text-xs text-muted-2">{dash(row.email)}</div>
                </td>
                <td className={TD}>
                  <div className="whitespace-nowrap">{row.level.title}</div>
                  {row.conditions_met && (
                    <div className="mt-1">
                      <Badge tone="wait" title="Пороги следующего уровня достигнуты. Повышение — только вручную.">
                        условия выполнены
                      </Badge>
                    </div>
                  )}
                </td>
                <td className={`${TD} whitespace-nowrap`}>{fmtPercent(row.percent)}%</td>
                <td className={`${TD} whitespace-nowrap`}>{nf(row.clicks)}</td>
                <td className={`${TD} whitespace-nowrap`}>{nf(row.registrations)}</td>
                <td className={`${TD} whitespace-nowrap`}>{nf(row.paying)}</td>
                <td className={TD}>
                  <Money value={row.sales_usdt} />
                </td>
                <td className={TD}>
                  <Money value={row.earned_usdt} />
                </td>
                <td className={`${TD} whitespace-nowrap`}>{nf(row.credits_granted)}</td>
                <td className={TD}>
                  <StatusPill table={CREATOR_STATUS} status={row.status} />
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
