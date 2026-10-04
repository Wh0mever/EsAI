"use client";

import { useCallback, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { FiCheck, FiCopy, FiExternalLink } from "react-icons/fi";
import ErrorNote from "@/components/creators/shared/ErrorNote";
import LoadMore from "@/components/creators/shared/LoadMore";
import Money from "@/components/creators/shared/Money";
import StatusBadge from "@/components/creators/shared/StatusBadge";
import { listWithdrawals, requestWithdrawal, setPayoutAddress } from "@/lib/creators/api";
import { errorText } from "@/lib/creators/errors";
import { cmpDec, fmtDate, fmtUsdt, isTronAddressShape } from "@/lib/creators/format";
import type { CrError, Iso, Me, Withdrawal } from "@/lib/creators/types";
import { BTN_GHOST, BTN_PRIMARY, CARD, Empty, INPUT, ListSkeleton, Note, Pair } from "./ui";
import { useCopy } from "./useCopy";
import { usePagedList } from "./usePagedList";

type Props = {
  me: Me;
  blocked: boolean;
  /** Баланс или заявка изменились — перечитать кабинет. */
  onChanged: () => void;
  onAddressSaved: (saved: { payout_address: string; payout_address_changed_at: Iso | null }) => void;
};

/** Сумма заявки: целое или до двух знаков после точки — так её принимает сервер. */
const AMOUNT_RE = /^\d+(\.\d{1,2})?$/;
const TXID_RE = /^[0-9a-fA-F]{64}$/;

/** "TAbcdefgh…wxyz": адрес целиком в таблицу на телефоне не помещается. */
const shortAddress = (address: string) =>
  address.length > 12 ? `${address.slice(0, 4)}…${address.slice(-4)}` : address;

/**
 * «Выплаты» (ТЗ п.23–28): доступная сумма, адрес USDT TRC20, заявка на вывод и
 * история с TXID. Страница денег никуда не отправляет и ничего не считает:
 * заявку проверяет и оплачивает администратор вручную. Комиссии с вывода нет —
 * сколько запрошено, столько и придёт.
 */
export default function PayoutsTab({ me, blocked, onChanged, onAddressSaved }: Props) {
  const { t, i18n } = useTranslation("creators", { useSuspense: false });
  const lang = i18n.language;
  const fetchPage = useCallback((page: number) => listWithdrawals({ page }), []);
  const list = usePagedList<Withdrawal>(fetchPage);
  const [created, setCreated] = useState(false);
  const { money, open_withdrawal: open } = me;

  const belowMin = cmpDec(money.available, money.min_payout) < 0;

  // Форма недоступна — показываем ОДНУ причину вместо неё.
  let reason: ReactNode = null;
  if (blocked) {
    reason = <Note tone="fail" size="sm">{errorText(t, { code: "creator_blocked" })}</Note>;
  } else if (!money.payouts_enabled) {
    reason = <Note tone="wait" size="sm">{errorText(t, { code: "payouts_disabled" })}</Note>;
  } else if (open) {
    reason = (
      <div className="flex flex-col gap-1.5">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-semibold text-foreground">
            {t("dash.payouts.open", { defaultValue: "Заявка на вывод {{amount}} USDT", amount: fmtUsdt(open.amount_usdt) })}
          </span>
          <StatusBadge kind="withdrawal" status={open.status} />
        </div>
        <div className="text-xs text-muted">{fmtDate(open.created_at, lang)}</div>
        <div className="break-all font-mono text-xs text-muted">{open.address}</div>
      </div>
    );
  } else if (belowMin) {
    reason = (
      <p className="text-sm text-muted">
        {t("dash.payouts.need_min", {
          defaultValue: "До вывода нужно набрать {{min}} USDT. Доступно: {{available}} USDT",
          min: fmtUsdt(money.min_payout),
          available: fmtUsdt(money.available),
        })}
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <p className="text-base text-foreground">
        {t("dash.payouts.available", { defaultValue: "Доступно" })}:{" "}
        <Money value={money.available} className="font-bold" />
      </p>

      {created && <Note tone="ok" size="sm">{t("dash.payouts.created", { defaultValue: "Заявка на проверке" })}</Note>}

      <AddressCard
        saved={me.payout_address}
        changedAt={me.payout_address_changed_at}
        readOnly={blocked}
        onSaved={onAddressSaved}
      />

      <section className={CARD}>
        <h2 className="mb-3 text-lg font-semibold text-foreground">
          {t("dash.payouts.withdraw_title", { defaultValue: "Вывести USDT" })}
        </h2>
        {reason ?? (
          <WithdrawForm
            me={me}
            onCreated={() => {
              setCreated(true);
              onChanged();
              list.reload();
            }}
            onStale={onChanged}
          />
        )}
      </section>

      <section className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold text-foreground">
          {t("dash.payouts.history", { defaultValue: "История выплат" })}
        </h2>
        {list.loading ? (
          <ListSkeleton />
        ) : list.error ? (
          <ErrorNote error={list.error} onRetry={list.reload} />
        ) : list.rows.length === 0 ? (
          <Empty>{t("dash.payouts.empty", { defaultValue: "Выплат пока не было." })}</Empty>
        ) : (
          <>
            <History rows={list.rows} />
            {list.moreError && <ErrorNote error={list.moreError} />}
            <LoadMore shown={list.rows.length} total={list.count} loading={list.loadingMore} onMore={list.loadMore} />
          </>
        )}
      </section>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Адрес выплат                                                        */
/* ------------------------------------------------------------------ */

function AddressCard({
  saved,
  changedAt,
  readOnly,
  onSaved,
}: {
  saved: string;
  changedAt: Iso | null;
  readOnly: boolean;
  onSaved: Props["onAddressSaved"];
}) {
  const { t, i18n } = useTranslation("creators", { useSuspense: false });
  const [address, setAddress] = useState(saved);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<CrError | { code: string } | null>(null);
  const [done, setDone] = useState(false);

  // Сохранённый адрес сменился (здесь или вместе с заявкой на вывод) — показываем его в поле.
  const [known, setKnown] = useState(saved);
  if (saved !== known) {
    setKnown(saved);
    setAddress(saved);
  }

  const value = address.trim();
  const title = t("dash.payouts.address_title", { defaultValue: "Адрес USDT TRC20" });

  const save = async () => {
    setDone(false);
    // Форму адреса проверяем сразу; контрольную сумму проверит сервер.
    if (!isTronAddressShape(value)) {
      setError({ code: "address_invalid" });
      return;
    }
    setError(null);
    setBusy(true);
    const res = await setPayoutAddress(value);
    setBusy(false);
    if (res.ok) {
      setDone(true);
      onSaved(res.data);
    } else {
      setError(res.error);
    }
  };

  return (
    <section className={CARD}>
      <h2 className="mb-3 text-lg font-semibold text-foreground">{title}</h2>
      {readOnly ? (
        <p className="break-all font-mono text-sm text-foreground">
          {saved || <span className="font-sans text-muted">{t("dash.payouts.address_none", { defaultValue: "Адрес не указан" })}</span>}
        </p>
      ) : (
        <form
          className="flex flex-col gap-2 sm:flex-row"
          noValidate
          onSubmit={(e) => {
            e.preventDefault();
            if (!busy) void save();
          }}
        >
          <input
            type="text"
            value={address}
            onChange={(e) => {
              setAddress(e.target.value);
              setError(null);
              setDone(false);
            }}
            placeholder="T…"
            maxLength={64}
            autoComplete="off"
            autoCapitalize="none"
            spellCheck={false}
            aria-label={title}
            aria-invalid={Boolean(error)}
            disabled={busy}
            className={`${INPUT} flex-1 font-mono`}
          />
          <button type="submit" disabled={busy || !value || value === saved} className={BTN_PRIMARY}>
            {busy
              ? t("dash.common.saving", { defaultValue: "Сохраняю…" })
              : t("dash.payouts.address_save", { defaultValue: "Сохранить адрес" })}
          </button>
        </form>
      )}
      {error && <Note tone="fail" className="mt-2">{errorText(t, error)}</Note>}
      {done && <Note tone="ok" className="mt-2">{t("dash.payouts.address_saved", { defaultValue: "Адрес сохранён" })}</Note>}
      <p className="mt-2 text-xs text-status-wait">
        {t("dash.payouts.address_warning", {
          defaultValue: "Только сеть TRC20. Перевод на адрес другой сети вернуть нельзя.",
        })}
      </p>
      {changedAt && (
        <p className="mt-1 text-xs text-muted">
          {t("dash.payouts.address_changed", {
            defaultValue: "Адрес изменён {{date}}",
            date: fmtDate(changedAt, i18n.language),
          })}
        </p>
      )}
    </section>
  );
}

/* ------------------------------------------------------------------ */
/* Заявка на вывод                                                     */
/* ------------------------------------------------------------------ */

function WithdrawForm({ me, onCreated, onStale }: { me: Me; onCreated: () => void; onStale: () => void }) {
  const { t } = useTranslation("creators", { useSuspense: false });
  const { money } = me;
  const [amount, setAmount] = useState("");
  const [address, setAddress] = useState(me.payout_address);
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [addressError, setAddressError] = useState<string | null>(null);
  const [error, setError] = useState<CrError | null>(null);

  // Адрес сохранили в карточке выше — подставляем его сюда, сумму не трогаем.
  const [known, setKnown] = useState(me.payout_address);
  if (me.payout_address !== known) {
    setKnown(me.payout_address);
    setAddress(me.payout_address);
    setAddressError(null);
    setConfirm(false);
  }

  const min = fmtUsdt(money.min_payout);
  const wallet = address.trim();

  // Сравнения — только подсказка и состояние кнопки; решает сервер.
  const shaped = AMOUNT_RE.test(amount);
  const tooSmall = shaped && cmpDec(amount, money.min_payout) < 0;
  const tooBig = shaped && cmpDec(amount, money.available) > 0;
  const ready = money.can_withdraw && shaped && !tooSmall && !tooBig;

  let amountHint: string | null = null;
  if (amount && !shaped) {
    amountHint = t("dash.payouts.amount_format", {
      defaultValue: "Введите сумму числом, не больше двух знаков после точки",
    });
  } else if (tooSmall) {
    amountHint = errorText(t, { code: "amount_below_min" }, { min });
  } else if (tooBig) {
    amountHint = errorText(t, { code: "insufficient_available" });
  }

  const reset = () => {
    setConfirm(false);
    setError(null);
  };

  const ask = () => {
    setError(null);
    if (!wallet) {
      setAddressError("address_required");
      return;
    }
    if (!isTronAddressShape(wallet)) {
      setAddressError("address_invalid");
      return;
    }
    setAddressError(null);
    setConfirm(true);
  };

  const submit = async () => {
    setBusy(true);
    setError(null);
    // Сумма уходит строкой, как её ввёл человек: в число не переводим.
    const res = await requestWithdrawal({ amount, address: wallet });
    setBusy(false);
    setConfirm(false);
    if (res.ok) {
      onCreated();
      return;
    }
    const code = res.error.code;
    if (code === "address_required" || code === "address_invalid") {
      setAddressError(code);
      return;
    }
    setError(res.error);
    // Баланс или состояние заявки на экране устарели — перечитываем кабинет.
    if (["insufficient_available", "withdrawal_open", "payouts_disabled", "creator_blocked", "disabled"].includes(code)) {
      onStale();
    }
  };

  const amountTitle = t("dash.payouts.amount", { defaultValue: "Сумма, USDT" });
  const addressTitle = t("dash.payouts.address_title", { defaultValue: "Адрес USDT TRC20" });
  const serverAvailable = error?.code === "insufficient_available" ? error.data.available : null;

  return (
    <form
      className="flex flex-col gap-3"
      noValidate
      onSubmit={(e) => {
        e.preventDefault();
        if (ready && !busy && !confirm) ask();
      }}
    >
      <label className="flex flex-col gap-1">
        <span className="text-xs text-muted">{amountTitle}</span>
        <span className="flex items-stretch gap-2">
          <input
            type="text"
            inputMode="decimal"
            pattern="^\d+(\.\d{1,2})?$"
            value={amount}
            onChange={(e) => {
              // Запятая с телефонной клавиатуры — та же десятичная точка.
              setAmount(e.target.value.replace(",", ".").replace(/[^\d.]/g, "").slice(0, 16));
              reset();
            }}
            placeholder={min}
            autoComplete="off"
            aria-invalid={Boolean(amountHint)}
            disabled={busy}
            className={`${INPUT} flex-1 tabular-nums`}
          />
          <button
            type="button"
            onClick={() => {
              // Доступную сумму подставляем дословно, как её прислал сервер.
              setAmount(money.available);
              reset();
            }}
            disabled={busy}
            className={BTN_GHOST}
          >
            {t("dash.payouts.all", { defaultValue: "Всё" })}
          </button>
        </span>
        {amountHint && <Note tone="fail">{amountHint}</Note>}
      </label>

      <label className="flex flex-col gap-1">
        <span className="text-xs text-muted">{addressTitle}</span>
        <input
          type="text"
          value={address}
          onChange={(e) => {
            setAddress(e.target.value);
            setAddressError(null);
            reset();
          }}
          placeholder="T…"
          maxLength={64}
          autoComplete="off"
          autoCapitalize="none"
          spellCheck={false}
          aria-invalid={Boolean(addressError)}
          disabled={busy}
          className={`${INPUT} font-mono`}
        />
        {addressError && <Note tone="fail">{errorText(t, { code: addressError })}</Note>}
      </label>

      {confirm ? (
        <div className="rounded-xl border border-border bg-surface-2 p-3">
          <p className="break-words text-sm text-foreground">
            {t("dash.payouts.confirm", {
              defaultValue: "Вывести {{amount}} USDT на адрес {{address}}?",
              amount,
              address: wallet,
            })}
          </p>
          <div className="mt-2 flex flex-wrap gap-2">
            <button type="button" onClick={() => void submit()} disabled={busy} className={BTN_PRIMARY}>
              {busy
                ? t("dash.common.sending", { defaultValue: "Отправляю…" })
                : t("dash.payouts.confirm_yes", { defaultValue: "Да, вывести" })}
            </button>
            <button type="button" onClick={() => setConfirm(false)} disabled={busy} className={BTN_GHOST}>
              {t("dash.common.cancel", { defaultValue: "Отмена" })}
            </button>
          </div>
        </div>
      ) : (
        <button type="submit" disabled={!ready || busy} className={`${BTN_PRIMARY} sm:self-start`}>
          {t("dash.payouts.withdraw", { defaultValue: "Вывести" })}
        </button>
      )}

      {error && (
        <div className="flex flex-col gap-1">
          <ErrorNote error={error} params={{ min }} />
          {typeof serverAvailable === "string" && (
            <Note tone="muted">
              {t("dash.payouts.available_now", {
                defaultValue: "Доступно: {{available}} USDT",
                available: fmtUsdt(serverAvailable),
              })}
            </Note>
          )}
        </div>
      )}

      <p className="text-xs text-muted">
        {t("dash.payouts.min_note", {
          defaultValue: "Минимум {{min}} USDT. Комиссия не удерживается: вы получите ровно запрошенную сумму.",
          min,
        })}
      </p>
    </form>
  );
}

/* ------------------------------------------------------------------ */
/* История выплат                                                      */
/* ------------------------------------------------------------------ */

function History({ rows }: { rows: Withdrawal[] }) {
  const { t, i18n } = useTranslation("creators", { useSuspense: false });
  const lang = i18n.language;
  const { copied, copy } = useCopy();
  // Адрес показан коротко; по нажатию — целиком (одна строка за раз).
  const [fullAddress, setFullAddress] = useState<number | null>(null);

  const head = {
    date: t("dash.payouts.col_date", { defaultValue: "Дата" }),
    amount: t("dash.payouts.col_amount", { defaultValue: "Сумма" }),
    status: t("dash.payouts.col_status", { defaultValue: "Статус" }),
    address: t("dash.payouts.col_address", { defaultValue: "Адрес" }),
  };
  const copyTxid = t("dash.payouts.txid_copy", { defaultValue: "Скопировать TXID" });
  const openTxid = t("dash.payouts.txid_open", { defaultValue: "Открыть в Tronscan" });
  const showAddress = t("dash.payouts.address_show", { defaultValue: "Показать адрес полностью" });

  const txid = (row: Withdrawal) =>
    row.txid ? (
      <span className="inline-flex max-w-full items-center gap-1.5">
        <span className="min-w-0 break-all font-mono text-xs text-foreground" title={row.txid}>
          {row.txid.length > 20 ? `${row.txid.slice(0, 8)}…${row.txid.slice(-8)}` : row.txid}
        </span>
        <button
          type="button"
          onClick={() => void copy(`txid:${row.id}`, row.txid)}
          aria-label={copyTxid}
          title={copyTxid}
          className="shrink-0 cursor-pointer rounded-lg border border-border p-1.5 text-muted transition-colors hover:border-accent hover:text-foreground"
        >
          {copied === `txid:${row.id}` ? <FiCheck className="text-status-ok" /> : <FiCopy />}
        </button>
        {TXID_RE.test(row.txid) && (
          <a
            href={`https://tronscan.org/#/transaction/${row.txid}`}
            target="_blank"
            rel="noopener noreferrer"
            aria-label={openTxid}
            title={openTxid}
            className="shrink-0 rounded-lg border border-border p-1.5 text-muted transition-colors hover:border-accent hover:text-foreground"
          >
            <FiExternalLink />
          </a>
        )}
      </span>
    ) : (
      <span className="text-muted">—</span>
    );

  const address = (row: Withdrawal) => (
    <button
      type="button"
      onClick={() => setFullAddress((id) => (id === row.id ? null : row.id))}
      aria-label={showAddress}
      aria-expanded={fullAddress === row.id}
      className="max-w-full cursor-pointer break-all text-left font-mono text-xs text-foreground underline decoration-dotted underline-offset-2"
    >
      {fullAddress === row.id ? row.address : shortAddress(row.address)}
    </button>
  );

  // Заявку, закрытую блокировкой, сервер помечает кодом, а не текстом.
  const rejectReason = (row: Withdrawal) =>
    row.status === "rejected" && row.reject_reason ? (
      <p className="mt-1 break-words text-xs text-status-fail">
        {row.reject_reason === "creator_blocked" ? errorText(t, { code: "creator_blocked" }) : row.reject_reason}
      </p>
    ) : null;

  return (
    <>
      {/* Телефон и узкий планшет: карточки */}
      <ul className="flex flex-col gap-2 md:hidden">
        {rows.map((row) => (
          <li key={row.id} className="rounded-2xl border border-border bg-surface p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <Money value={row.amount_usdt} className="text-base font-bold text-foreground" />
              <StatusBadge kind="withdrawal" status={row.status} />
            </div>
            {rejectReason(row)}
            <dl className="mt-2 flex flex-col gap-1.5">
              <Pair label={head.date}>{fmtDate(row.created_at, lang)}</Pair>
              <Pair label="TXID">{txid(row)}</Pair>
              <Pair label={head.address}>{address(row)}</Pair>
            </dl>
          </li>
        ))}
      </ul>

      {/* Шире: таблица */}
      <div className="hidden overflow-hidden rounded-2xl border border-border bg-surface md:block">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left text-xs text-muted">
              <th scope="col" className="px-4 py-3 font-medium">{head.date}</th>
              <th scope="col" className="px-4 py-3 text-right font-medium">{head.amount}</th>
              <th scope="col" className="px-4 py-3 font-medium">{head.status}</th>
              <th scope="col" className="px-4 py-3 font-medium">TXID</th>
              <th scope="col" className="px-4 py-3 font-medium">{head.address}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id} className="border-b border-border align-top last:border-b-0">
                <td className="whitespace-nowrap px-4 py-3 text-foreground">{fmtDate(row.created_at, lang)}</td>
                <td className="px-4 py-3 text-right font-semibold text-foreground">
                  <Money value={row.amount_usdt} />
                </td>
                <td className="px-4 py-3">
                  <StatusBadge kind="withdrawal" status={row.status} />
                  {rejectReason(row)}
                </td>
                <td className="px-4 py-3">{txid(row)}</td>
                <td className="px-4 py-3">{address(row)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
