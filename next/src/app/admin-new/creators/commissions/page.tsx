"use client";

import { useState } from "react";
import Money from "@/components/creators/shared/Money";
import {
  adminCommissions,
  adminReleaseCommission,
  adminRestoreCommission,
  adminVoidCommission,
} from "@/lib/creators/adminApi";
import type { AdminCommission } from "@/lib/creators/adminTypes";
import { fmtPercent } from "@/lib/creators/format";
import type { CommissionStatus } from "@/lib/creators/types";
import { COMMISSION_STATUS, PROVIDERS, commissionReason, labelFrom } from "../_shared/labels";
import ReasonDialog from "../_shared/ReasonDialog";
import {
  BTN,
  BTN_DANGER,
  BTN_OK,
  Chips,
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
  StatusPill,
  SuButton,
  SuCaption,
  TableWrap,
  TD,
  TH,
  THEAD_ROW,
  useIdParam,
} from "../_shared/ui";
import { usePagedList } from "../_shared/usePagedList";

type Filter = CommissionStatus | "all";

const FILTERS: { key: Filter; label: string }[] = [
  { key: "all", label: "Все" },
  { key: "accrued", label: "Начисленные" },
  { key: "held", label: "Придержанные" },
  { key: "reversed", label: "Отменённые возвратом" },
  { key: "void", label: "Аннулированные" },
];

type Action = { kind: "void" | "release" | "restore"; row: AdminCommission };

/**
 * Все комиссии. Суммы и курс записаны в строке слепком в момент оплаты — здесь
 * их только показывают; править комиссию нельзя, можно аннулировать, выпустить
 * придержанную или восстановить ошибочно отменённую.
 */
export default function AdminCreatorsCommissionsPage() {
  const creator = useIdParam("creator");
  const [filter, setFilter] = useState<Filter>("all");
  const [provider, setProvider] = useState("");
  const [action, setAction] = useState<Action | null>(null);
  const [clearRefund, setClearRefund] = useState(false);

  const list = usePagedList(adminCommissions, {
    creator,
    status: filter === "all" ? undefined : filter,
    provider,
  });

  const open = (kind: Action["kind"], row: AdminCommission) => {
    setClearRefund(false);
    setAction({ kind, row });
  };

  const about = (row: AdminCommission) =>
    `${row.creator_name}: комиссия ${row.amount_usdt} USDT по заказу ${row.order_id || `#${row.payment_id}`}.`;

  return (
    <div className="space-y-4">
      <PageTitle title="Комиссии" hint={`Найдено: ${nf(list.count)}. Новые сверху.`} />

      <div className="flex flex-wrap items-center gap-2">
        <Chips options={FILTERS} value={filter} onChange={setFilter} />
        <select
          value={provider}
          onChange={(e) => setProvider(e.target.value)}
          className={INPUT_SM}
          aria-label="Платёжная система"
        >
          <option value="">Все способы оплаты</option>
          {Object.entries(PROVIDERS).map(([key, label]) => (
            <option key={key} value={key}>
              {label}
            </option>
          ))}
        </select>
        <IdParamChip name="creator" label="Creator" />
      </div>

      {list.loading ? (
        <Skeleton />
      ) : list.error ? (
        <ErrorBox error={list.error} />
      ) : (
        <TableWrap minWidth={1480}>
          <thead>
            <tr className={THEAD_ROW}>
              <th className={TH}>Дата</th>
              <th className={TH}>Creator</th>
              <th className={TH}>Покупатель</th>
              <th className={TH}>Заказ</th>
              <th className={TH}>Оплачено</th>
              <th className={TH}>Курс к USD</th>
              <th className={TH}>База, USD</th>
              <th className={TH}>Уровень · %</th>
              <th className={TH}>Комиссия</th>
              <th className={TH}>Статус</th>
              <th className={TH}>Сроки</th>
              <th className={TH}>Действия</th>
            </tr>
          </thead>
          <tbody>
            {list.rows.length === 0 && <EmptyRow colSpan={12}>Комиссий нет.</EmptyRow>}
            {list.rows.map((row) => {
              const canVoid = row.status === "accrued" || row.status === "held";
              const canRelease = row.status === "held";
              const canRestore = row.status === "reversed" || (row.status === "void" && row.reason === "admin_void");
              return (
                <tr key={row.id} className={`${ROW} hover:bg-surface-2`}>
                  <td className={`${TD} whitespace-nowrap text-muted`}>{dt(row.created_at)}</td>
                  <td className={TD}>
                    <CreatorLink id={row.creator_id} name={row.creator_name} />
                  </td>
                  <td className={TD}>
                    <div className="break-all">{dash(row.buyer_email)}</div>
                    <div className="text-xs text-muted-2">id {row.buyer_pk}</div>
                  </td>
                  <td className={`${TD} max-w-[200px]`}>
                    <div className="break-all font-mono text-xs">{dash(row.order_id)}</div>
                    <div className="text-xs text-muted-2">
                      платёж #{row.payment_id}
                      {row.part ? ` · часть ${row.part}` : ""}
                    </div>
                  </td>
                  <td className={TD}>
                    <div className="whitespace-nowrap">
                      {row.paid_amount} {row.paid_currency}
                    </div>
                    <div className="text-xs text-muted-2">{labelFrom(PROVIDERS, row.provider)}</div>
                  </td>
                  <td className={TD}>
                    <div className="whitespace-nowrap tabular-nums">{row.rate_to_usd}</div>
                    <div className="text-xs text-muted-2">{dash(row.rate_source)}</div>
                  </td>
                  <td className={`${TD} whitespace-nowrap tabular-nums`}>{row.base_usd}</td>
                  <td className={TD}>
                    <div className="whitespace-nowrap font-mono text-xs">{row.level_key}</div>
                    <div className="text-xs text-muted-2">{fmtPercent(row.percent)}%</div>
                  </td>
                  <td className={TD}>
                    <Money value={row.amount_usdt} className="font-medium" />
                  </td>
                  <td className={`${TD} max-w-[200px]`}>
                    <StatusPill table={COMMISSION_STATUS} status={row.status} />
                    {row.reason && <div className="mt-1 break-words text-xs text-muted">{commissionReason(row.reason)}</div>}
                  </td>
                  <td className={`${TD} text-xs text-muted`}>
                    <div className="whitespace-nowrap">доступна: {dt(row.available_at)}</div>
                    {row.reversed_at && <div className="whitespace-nowrap">отменена: {dt(row.reversed_at)}</div>}
                  </td>
                  <td className={TD}>
                    {canVoid || canRelease || canRestore ? (
                      <div className="flex flex-col items-start gap-1.5">
                        {canRelease && (
                          <SuButton className={BTN_OK} onClick={() => open("release", row)}>
                            Выпустить
                          </SuButton>
                        )}
                        {canRestore && (
                          <SuButton className={BTN} onClick={() => open("restore", row)}>
                            Восстановить
                          </SuButton>
                        )}
                        {canVoid && (
                          <SuButton className={BTN_DANGER} onClick={() => open("void", row)}>
                            Аннулировать
                          </SuButton>
                        )}
                        <SuCaption />
                      </div>
                    ) : (
                      <span className="text-muted-2">—</span>
                    )}
                  </td>
                </tr>
              );
            })}
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

      {action?.kind === "void" && (
        <ReasonDialog
          title="Аннулировать комиссию"
          description={`${about(action.row)} Она перестанет считаться в заработке креатора.`}
          reason="required"
          confirmLabel="Аннулировать"
          danger
          onClose={() => setAction(null)}
          onSubmit={async (reason) => {
            const res = await adminVoidCommission(action.row.id, reason);
            if (!res.ok) return res.error;
            list.replace(res.data);
            return null;
          }}
        />
      )}

      {action?.kind === "release" && (
        <ReasonDialog
          title="Выпустить придержанную комиссию"
          description={`${about(action.row)} Она станет начисленной и пойдёт в баланс креатора.`}
          reason="optional"
          confirmLabel="Выпустить"
          onClose={() => setAction(null)}
          onSubmit={async (reason) => {
            const res = await adminReleaseCommission(action.row.id, reason);
            if (!res.ok) return res.error;
            list.replace(res.data);
            return null;
          }}
        />
      )}

      {action?.kind === "restore" && (
        <ReasonDialog
          title="Восстановить комиссию"
          description={`${about(action.row)} Используйте, если её отменили по ошибке.`}
          reason="required"
          confirmLabel="Восстановить"
          onClose={() => setAction(null)}
          onSubmit={async (reason) => {
            const res = await adminRestoreCommission(action.row.id, { reason, clear_admin_refund: clearRefund });
            if (!res.ok) return res.error;
            list.replace(res.data);
            return null;
          }}
        >
          <label className="flex items-start gap-2 text-sm">
            <input
              type="checkbox"
              checked={clearRefund}
              onChange={(e) => setClearRefund(e.target.checked)}
              className="mt-0.5 accent-accent"
            />
            <span>
              Снять ручную отметку возврата
              <span className="block text-xs text-muted-2">
                Нужно, если платёж отметили возвращённым вручную по ошибке: без этого комиссию по нему не восстановить.
              </span>
            </span>
          </label>
        </ReasonDialog>
      )}
    </div>
  );
}
