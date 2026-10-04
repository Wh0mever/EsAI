"use client";

import { useState } from "react";
import {
  adminApproveWithdrawal,
  adminFixTxid,
  adminMarkPaid,
  adminRejectWithdrawal,
  adminReopenWithdrawal,
} from "@/lib/creators/adminApi";
import type { AdminWithdrawal } from "@/lib/creators/adminTypes";
import { fmtUsdt } from "@/lib/creators/format";
import type { CrError } from "@/lib/creators/types";
import ReasonDialog from "./ReasonDialog";
import { BTN, BTN_DANGER, BTN_OK, errText, INPUT, SuButton, SuCaption } from "./ui";

/** TXID сети TRON: 64 шестнадцатеричных символа, допускается приставка 0x (сервер её срежет). */
const TXID_RE = /^(0x)?[0-9a-fA-F]{64}$/;

type Dialog = "reject" | "paid" | "txid" | "reopen" | null;

/**
 * Действия над заявкой на вывод (ТЗ п.26) — все только для главного
 * администратора. Денег панель никуда не отправляет: USDT администратор
 * переводит сам из своего кошелька, а здесь только записывает TXID.
 * Те же кнопки стоят во вкладке «Выплаты» и в профиле креатора.
 */
export default function WithdrawalActions({
  row,
  onChange,
}: {
  row: AdminWithdrawal;
  onChange: (row: AdminWithdrawal) => void;
}) {
  const [dialog, setDialog] = useState<Dialog>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<CrError | null>(null);
  const [txid, setTxid] = useState("");
  // Сервер отказал в отметке (креатор заблокирован или после заявки был возврат),
  // а перевод уже ушёл: показываем флажок «отметить принудительно».
  const [forceOffered, setForceOffered] = useState(false);
  const [force, setForce] = useState(false);

  if (row.status === "rejected") return null;

  const amount = `${fmtUsdt(row.amount_usdt)} USDT`;
  const who = `${row.creator_name}, ${amount}`;
  const txidOk = TXID_RE.test(txid.trim());

  const open = (next: Dialog) => {
    setTxid("");
    setForce(false);
    setForceOffered(false);
    setError(null);
    setDialog(next);
  };

  const done = (res: { ok: true; data: AdminWithdrawal } | { ok: false; error: CrError }): CrError | null => {
    if (!res.ok) return res.error;
    onChange(res.data);
    return null;
  };

  const approve = async () => {
    if (!confirm(`Одобрить вывод ${amount} для ${row.creator_name}?\nПосле одобрения переведите USDT вручную и отметьте заявку выплаченной.`)) return;
    setBusy(true);
    setError(null);
    const res = await adminApproveWithdrawal(row.id);
    setBusy(false);
    if (res.ok) onChange(res.data);
    else setError(res.error);
  };

  const txidField = (
    <label className="block text-sm">
      <span className="text-muted">TXID перевода *</span>
      <input
        value={txid}
        onChange={(e) => setTxid(e.target.value.trim())}
        placeholder="64 шестнадцатеричных символа"
        spellCheck={false}
        autoComplete="off"
        className={`${INPUT} mt-1.5 w-full font-mono`}
      />
      {txid && !txidOk && (
        <span className="mt-1 block text-xs text-rose-300">Некорректный TXID: нужны 64 шестнадцатеричных символа</span>
      )}
    </label>
  );

  return (
    <div className="space-y-1">
      <div className="flex flex-wrap gap-1.5">
        {row.status === "review" && (
          <SuButton className={BTN_OK} disabled={busy} onClick={approve}>
            {busy ? "Сохраняю…" : "Одобрить"}
          </SuButton>
        )}
        {row.status === "approved" && (
          <SuButton className={BTN_OK} onClick={() => open("paid")}>
            Отметить выплаченной
          </SuButton>
        )}
        {(row.status === "review" || row.status === "approved") && (
          <SuButton className={BTN_DANGER} disabled={busy} onClick={() => open("reject")}>
            Отклонить
          </SuButton>
        )}
        {row.status === "paid" && (
          <>
            <SuButton className={BTN} onClick={() => open("txid")}>
              Исправить TXID
            </SuButton>
            <SuButton className={BTN} onClick={() => open("reopen")}>
              Вернуть в работу
            </SuButton>
          </>
        )}
      </div>
      <SuCaption />
      {error && <p className="text-xs text-rose-300">{errText(error)}</p>}

      {dialog === "reject" && (
        <ReasonDialog
          title="Отклонить заявку на вывод"
          description={`${who}. Сумма вернётся в «Доступно к выводу».`}
          reason="required"
          reasonLabel="Причина — её увидит креатор"
          confirmLabel="Отклонить"
          danger
          onClose={() => setDialog(null)}
          onSubmit={async (reason) => done(await adminRejectWithdrawal(row.id, reason))}
        />
      )}

      {dialog === "paid" && (
        <ReasonDialog
          title="Отметить выплаченной"
          description={
            <>
              {who}. Сначала переведите USDT (TRC20) на адрес{" "}
              <span className="break-all font-mono text-xs text-foreground">{row.address}</span>, затем вставьте TXID
              перевода.
            </>
          }
          reason={force ? "required" : "hidden"}
          confirmLabel="Отметить выплаченной"
          canSubmit={txidOk}
          confirmText={`Перевод ${amount} отправлен и TXID верный?`}
          onClose={() => setDialog(null)}
          onSubmit={async (reason) => {
            const res = await adminMarkPaid(row.id, force ? { txid: txid.trim(), force: true, reason } : { txid: txid.trim() });
            if (!res.ok && (res.error.code === "creator_blocked" || res.error.code === "insufficient_available")) {
              setForceOffered(true);
            }
            return done(res);
          }}
        >
          {txidField}
          {forceOffered && (
            <label className="flex items-start gap-2 text-sm">
              <input
                type="checkbox"
                checked={force}
                onChange={(e) => setForce(e.target.checked)}
                className="mt-0.5 accent-accent"
              />
              <span>
                Деньги уже отправлены — отметить принудительно
                <span className="block text-xs text-muted-2">
                  Только если перевод действительно ушёл в сеть. Причина обязательна и попадёт в журнал.
                </span>
              </span>
            </label>
          )}
        </ReasonDialog>
      )}

      {dialog === "txid" && (
        <ReasonDialog
          title="Исправить TXID"
          description={
            <>
              {who}. Сейчас записан: <span className="break-all font-mono text-xs text-foreground">{row.txid || "—"}</span>
            </>
          }
          reason="required"
          confirmLabel="Сохранить TXID"
          canSubmit={txidOk}
          onClose={() => setDialog(null)}
          onSubmit={async (reason) => done(await adminFixTxid(row.id, { txid: txid.trim(), reason }))}
        >
          {txidField}
        </ReasonDialog>
      )}

      {dialog === "reopen" && (
        <ReasonDialog
          title="Вернуть заявку в работу"
          description={`${who}. Используйте, если перевод не прошёл в сети: заявка снова станет «Одобрена», TXID будет снят.`}
          reason="required"
          confirmLabel="Вернуть в работу"
          danger
          onClose={() => setDialog(null)}
          onSubmit={async (reason) => done(await adminReopenWithdrawal(row.id, reason))}
        />
      )}
    </div>
  );
}
