"use client";

import Money from "@/components/creators/shared/Money";
import type { AdminWithdrawal } from "@/lib/creators/adminTypes";
import { cmpDec } from "@/lib/creators/format";
import { WITHDRAWAL_STATUS } from "./labels";
import WithdrawalActions from "./WithdrawalActions";
import { Badge, CopyValue, CreatorLink, ROW, StatusPill, TD, d, dash, dt } from "./ui";

/** Заголовки таблицы выплат — одни и те же во вкладке «Выплаты» и в профиле креатора. */
export const WITHDRAWAL_COLUMNS = ["Дата заявки", "Creator", "Сумма", "Адрес", "Статус", "TXID", "Баланс креатора", "Действия"];

/** Заявка в работе: по ней ещё предстоит решение или перевод. */
const isOpen = (row: AdminWithdrawal) => row.status === "review" || row.status === "approved";

/**
 * Строка заявки на вывод. Красным — заявки, по которым платить нельзя: после
 * заявки пришёл возврат (covered: false) или креатора заблокировали.
 */
export default function WithdrawalRow({
  row,
  onChange,
}: {
  row: AdminWithdrawal;
  onChange: (row: AdminWithdrawal) => void;
}) {
  const uncovered = row.covered === false && isOpen(row);
  const blocked = row.creator_status === "blocked";
  const alarm = uncovered || (blocked && isOpen(row));
  const hasDebt = cmpDec(row.balance?.debt, "0") > 0;

  return (
    <tr className={`${ROW} ${alarm ? "bg-status-fail/10" : "hover:bg-surface-2"}`}>
      <td className={`${TD} whitespace-nowrap text-muted`}>{dt(row.created_at)}</td>
      <td className={TD}>
        <CreatorLink id={row.creator_id} name={row.creator_name} />
        <div className="break-all text-xs text-muted-2">{dash(row.email)}</div>
        {blocked && <div className="mt-1 text-xs text-status-fail">Креатор заблокирован</div>}
      </td>
      <td className={TD}>
        <Money value={row.amount_usdt} className="font-medium" />
        <div className="text-xs text-muted-2">{row.network || "TRC20"}</div>
      </td>
      <td className={`${TD} max-w-[230px]`}>
        <CopyValue value={row.address} />
        {row.address_changed_at && (
          <div className="mt-1">
            <Badge tone="wait" title="Когда креатор последний раз менял адрес выплат. Свежая смена — повод перепроверить.">
              адрес изменён {d(row.address_changed_at)}
            </Badge>
          </div>
        )}
      </td>
      <td className={`${TD} max-w-[220px]`}>
        <StatusPill table={WITHDRAWAL_STATUS} status={row.status} />
        {row.approved_at && (
          <div className="mt-1 text-xs text-muted-2">
            одобрил: {dash(row.approved_by_email)}
            <br />
            {dt(row.approved_at)}
          </div>
        )}
        {row.paid_at && (
          <div className="mt-1 text-xs text-muted-2">
            выплатил: {dash(row.paid_by_email)}
            <br />
            {dt(row.paid_at)}
          </div>
        )}
        {row.status === "rejected" && (
          <div className="mt-1 break-words text-xs text-rose-300">
            {row.rejected_at ? `${dt(row.rejected_at)} · ` : ""}
            {row.reject_reason === "creator_blocked" ? "креатор заблокирован" : dash(row.reject_reason)}
          </div>
        )}
      </td>
      <td className={`${TD} max-w-[230px]`}>
        <CopyValue value={row.txid} />
      </td>
      <td className={`${TD} text-xs`}>
        <div className="whitespace-nowrap">
          <span className="text-muted-2">доступно:</span> <Money value={row.balance?.available} />
        </div>
        <div className={`whitespace-nowrap ${hasDebt ? "text-status-fail" : ""}`}>
          <span className={hasDebt ? "" : "text-muted-2"}>долг:</span> <Money value={row.balance?.debt} />
        </div>
        {uncovered && (
          <div className="mt-1 max-w-[180px] text-status-fail">После заявки был возврат — платить нечем</div>
        )}
      </td>
      <td className={TD}>
        <WithdrawalActions row={row} onChange={onChange} />
      </td>
    </tr>
  );
}
