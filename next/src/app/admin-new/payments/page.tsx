"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { fetchData } from "@/tools/fetchData";
import { adminMarkRefunded } from "@/lib/creators/adminApi";
import ReasonDialog from "../creators/_shared/ReasonDialog";
import { CreatorsRoleProvider } from "../creators/_shared/role";
import { SuButton, SuCaption } from "../creators/_shared/ui";
import { FILTERS, filterFromParams, reviewLabel } from "./filters";

type CryptoInfo = {
  status: string;
  coin: string;
  network: string;
  pay_amount: string;
  actually_paid: string;
  credited_tokens: number;
  tx_hash: string;
  expires_at: string | null;
  flags: Record<string, unknown>;
};

/** Счёт единого QR (GoPay). Старый сервер поля не присылает — оно необязательное. */
type QrInfo = {
  status: string;
  env: string;
  provider_payment_id: string;
  expires_at: string | null;
  committed_at: string | null;
  bank_op_date: string | null;
  receipt_url: string;
  /** покупатель ушёл от этого QR, а GoPay его ещё не закрыл */
  abandoned: boolean;
  flags: Record<string, unknown>;
};

type Payment = {
  id: number;
  created_at: string;
  user_email: string;
  amount: number;
  currency: string;
  success: boolean;
  /** крипта и единый QR: счёт ещё живой, «неуспешно» тут означало бы неправду */
  pending?: boolean;
  /** тестовая среда GoPay: кредиты начислены, но в выручку платёж не идёт */
  is_test?: boolean;
  provider?: string;
  /** способ оплаты в сомах, выбранный до ухода на Freedom Pay; "" — не выбирали */
  method?: string;
  order_id: string;
  description: string;
  error: string;
  crypto?: CryptoInfo | null;
  qr?: QrInfo | null;
};

type PaymentsResponse = { count: number; results: Payment[] };

const nf = (n: number) => (n ?? 0).toLocaleString("ru-RU");

const PROVIDERS: Record<string, string> = {
  freedompay: "FreedomPay",
  gopay: "Единый QR (GoPay)",
  yookassa: "ЮKassa",
  crypto_nowpayments: "Крипта",
  telegram_stars: "Telegram Stars",
};

/** Способ оплаты в сомах, выбранный человеком в нашем окне (Payment.request.pay_method). */
const KGS_METHODS: Record<string, string> = {
  elqr: "Единый QR",
  mbank: "MBANK",
  odengi: "О!Деньги",
  balance: "Balance.kg",
  megapay: "MegaPay",
  card: "Карта",
};

/** Чем закончился QR-счёт, если оплаты нет. Открытые счета идут как «Ждём оплату». */
const QR_STATUS: Record<string, string> = {
  failed: "Не прошёл",
  expired: "Истёк",
  cancelled: "Отменён",
};

/** День в банке приходит датой без времени: «2026-10-06» → «06.10.2026». */
const fmtDay = (s: string) => {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s);
  return m ? `${m[3]}.${m[2]}.${m[1]}` : s;
};

const fmtDate = (s: string) => {
  const d = new Date(s);
  if (isNaN(d.getTime())) return s;
  return d.toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
};

/**
 * «Отметить возврат» — денежное действие программы EsAI Creators, оно только
 * для главного администратора. Роль узнаём той же пробой, что и раздел
 * «Creators» (настройки программы открыты только ему).
 *
 * useSearchParams требует границы Suspense (иначе сборка не сможет
 * пререндерить страницу).
 */
export default function AdminPaymentsPage() {
  return (
    <CreatorsRoleProvider>
      <Suspense fallback={<PaymentsSkeleton />}>
        <PaymentsPage />
      </Suspense>
    </CreatorsRoleProvider>
  );
}

function PaymentsSkeleton() {
  return (
    <div className="space-y-4">
      <div className="h-8 w-40 animate-pulse rounded-lg bg-surface-2" />
      <div className="h-96 animate-pulse rounded-2xl bg-surface-2" />
    </div>
  );
}

type RefundKind = "refund" | "fraud";

const REFUND_KINDS: { key: RefundKind; label: string }[] = [
  { key: "refund", label: "Возврат" },
  { key: "fraud", label: "Мошенничество" },
];

function PaymentsPage() {
  const [payments, setPayments] = useState<Payment[]>([]);
  const [count, setCount] = useState(0);
  const [page, setPage] = useState(1);
  // ?unsettled=1 — ссылка «Оплачено, но не зачислено» из настроек. Читаем у
  // роутера: адрес в самом окне браузера при переходе по <Link> на первом
  // рендере ещё показывает прошлую страницу (см. filters.ts).
  const searchParams = useSearchParams();
  const [filter, setFilter] = useState(() => filterFromParams(searchParams));
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [rechecking, setRechecking] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Ручная отметка возврата: платёж, вид отметки (по умолчанию не выбран), изъятие кредитов.
  const [refunding, setRefunding] = useState<Payment | null>(null);
  const [refundKind, setRefundKind] = useState<RefundKind | "">("");
  const [clawback, setClawback] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(
    async (pageNum: number, append: boolean, filterKey = filter, q = search) => {
      if (append) setLoadingMore(true);
      else setLoading(true);
      const extra = FILTERS.find((f) => f.key === filterKey)?.query || "";
      const url =
        `manage/payments/?page=${pageNum}` +
        (extra ? `&${extra}` : "") +
        (q ? `&q=${encodeURIComponent(q)}` : "");
      const res = await fetchData<PaymentsResponse>(url, "GET", null, true);
      if (res.ok && res.data) {
        const results = res.data.results || [];
        setCount(res.data.count || 0);
        setPayments((prev) => (append ? [...prev, ...results] : results));
        setPage(pageNum);
        setError(null);
      } else if (!append) {
        setError(res.error || "Не удалось загрузить платежи");
      }
      setLoading(false);
      setLoadingMore(false);
    },
    [filter, search]
  );

  useEffect(() => {
    load(1, false);
    // Первая загрузка; дальше список перезапрашивается по кнопкам фильтра.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const applyFilter = (key: string) => {
    setFilter(key);
    load(1, false, key, search);
  };

  const applySearch = (value: string) => {
    setSearch(value);
    load(1, false, filter, value);
  };

  /**
   * Перепроверить платёж у процессора. Нужно, когда вебхук не дошёл, а деньги
   * человек отправил: вместо ручного начисления «на глаз» платёж проходит тот
   * же путь, что и обычно, со всеми проверками.
   */
  const recheck = async (id: number) => {
    setRechecking(id);
    const res = await fetchData<{ payment?: Payment; queued?: boolean; detail?: string }>(
      `manage/payments/${id}/recheck/`,
      "POST",
      {},
      true
    );
    setRechecking(null);
    if (res.ok && res.data?.payment) {
      const fresh = res.data.payment;
      setPayments((prev) => prev.map((p) => (p.id === id ? fresh : p)));
      return;
    }
    if (res.ok) return; // поставили в очередь (не крипта и не QR)
    setError(res.data?.detail || res.error || "Не удалось перепроверить платёж");
  };

  if (loading) return <PaymentsSkeleton />;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Платежи</h1>
        <p className="mt-1 text-sm text-muted">
          Все попытки оплаты, новые сверху. Всего: {nf(count)}.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {FILTERS.map((f) => (
          <button
            key={f.key}
            onClick={() => applyFilter(f.key)}
            className={`rounded-lg border px-3 py-1.5 text-xs transition-colors ${
              filter === f.key
                ? "border-accent bg-accent/10 text-accent"
                : "border-border text-muted hover:text-foreground"
            }`}
          >
            {f.label}
          </button>
        ))}
        <form
          className="ml-auto flex items-center gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            applySearch(query.trim());
          }}
        >
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Заказ или email"
            className="rounded-lg border border-border bg-surface-2 px-3 py-1.5 text-sm outline-none focus:border-accent"
          />
          <button
            type="submit"
            className="rounded-lg border border-border px-3 py-1.5 text-xs text-muted transition-colors hover:text-foreground"
          >
            Найти
          </button>
        </form>
      </div>

      {error && (
        <div className="rounded-xl border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
          {error}
        </div>
      )}

      {notice && (
        <div className="rounded-xl border border-status-ok/40 bg-status-ok/10 px-3 py-2 text-sm text-status-ok">
          {notice}
        </div>
      )}

      <div className="overflow-x-auto rounded-2xl border border-border bg-surface">
        <table className="w-full min-w-[1080px] text-sm">
          <thead>
            <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted-2">
              <th className="px-4 py-3 font-medium">Дата</th>
              <th className="px-4 py-3 font-medium">Email</th>
              <th className="px-4 py-3 font-medium">Сумма</th>
              <th className="px-4 py-3 font-medium">Способ</th>
              <th className="px-4 py-3 font-medium">Статус</th>
              <th className="px-4 py-3 font-medium">Заказ</th>
              <th className="px-4 py-3 font-medium">Ошибка</th>
              <th className="px-4 py-3 font-medium" />
            </tr>
          </thead>
          <tbody>
            {payments.length === 0 && (
              <tr>
                <td colSpan={8} className="px-4 py-8 text-center text-muted">
                  Платежей пока нет.
                </td>
              </tr>
            )}
            {payments.map((p) => {
              const reviewFlag = p.crypto?.flags?.needs_review ?? p.qr?.flags?.needs_review;
              const needsReview = Boolean(reviewFlag);
              const qr = p.qr || null;
              // Чек открываем только по https: адрес приходит от провайдера.
              const receiptUrl = qr && /^https:\/\//i.test(qr.receipt_url || "") ? qr.receipt_url : "";
              return (
                <tr
                  key={p.id}
                  className={`border-b border-border last:border-0 hover:bg-surface-2 ${
                    needsReview ? "bg-status-wait/5" : ""
                  }`}
                >
                  <td className="whitespace-nowrap px-4 py-3 text-muted">
                    {fmtDate(p.created_at)}
                  </td>
                  <td className="px-4 py-3">{p.user_email}</td>
                  <td className="whitespace-nowrap px-4 py-3 font-medium">
                    {nf(p.amount)} {p.currency}
                    {p.is_test && (
                      <span
                        className="ml-2 rounded border border-status-wait/50 bg-status-wait/10 px-1.5 py-0.5 align-middle text-[10px] font-semibold tracking-wide text-status-wait"
                        title="Тестовая среда GoPay: деньги не списывались, в выручку платёж не входит"
                      >
                        ТЕСТ
                      </span>
                    )}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-xs">
                    <div>
                      {PROVIDERS[p.provider || ""] || p.provider || "—"}
                      {p.method ? (
                        <span className="text-muted-2"> · {KGS_METHODS[p.method] || p.method}</span>
                      ) : null}
                    </div>
                    {p.crypto && (
                      <div
                        className="text-muted-2"
                        title={`${p.crypto.coin} · ${p.crypto.network}${
                          p.crypto.tx_hash ? ` · tx: ${p.crypto.tx_hash}` : ""
                        }`}
                      >
                        {p.crypto.coin} · {p.crypto.network}
                      </div>
                    )}
                    {qr && (
                      <div
                        className="text-muted-2"
                        title={qr.provider_payment_id ? `GoPay: ${qr.provider_payment_id}` : undefined}
                      >
                        {qr.env === "test" ? "тест" : "боевой"}
                        {qr.bank_op_date ? ` · день в банке ${fmtDay(qr.bank_op_date)}` : ""}
                        {qr.abandoned ? " · оставлен покупателем" : ""}
                        {receiptUrl && (
                          <>
                            {" · "}
                            <a
                              href={receiptUrl}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="text-accent hover:underline"
                            >
                              чек
                            </a>
                          </>
                        )}
                      </div>
                    )}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3">
                    {p.success ? (
                      <span className="text-status-ok">✓ Успешно</span>
                    ) : p.pending ? (
                      // У крипты ждём перевод в сети, у остальных — оплату по счёту.
                      <span className="text-status-wait">
                        {p.crypto ? "⏳ Ждём перевод" : "⏳ Ждём оплату"}
                      </span>
                    ) : qr && QR_STATUS[qr.status] ? (
                      <span className="text-status-fail">✗ {QR_STATUS[qr.status]}</span>
                    ) : (
                      <span className="text-status-fail">✗ Неуспешно</span>
                    )}
                    {qr && qr.status === "committed" && !p.success && (
                      // Деньги в GoPay есть, а заказ не закрыт: либо разбор, либо отмеченный возврат.
                      <div className="text-[11px] text-status-wait">в GoPay оплачен, кредиты не начислены</div>
                    )}
                    {p.crypto && p.crypto.credited_tokens > 0 && !p.success && (
                      <div className="text-[11px] text-muted-2">
                        зачислено {nf(p.crypto.credited_tokens)} кр.
                      </div>
                    )}
                    {needsReview && (
                      <div className="text-[11px] text-status-wait">
                        разбор: {reviewLabel(reviewFlag)}
                      </div>
                    )}
                  </td>
                  <td className="max-w-[180px] truncate px-4 py-3 font-mono text-xs text-muted-2">
                    {p.order_id}
                  </td>
                  <td className="max-w-[200px] truncate px-4 py-3 text-xs text-rose-400/80">
                    {p.error || ""}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-right">
                    <div className="flex flex-col items-end gap-1.5">
                      <button
                        onClick={() => recheck(p.id)}
                        disabled={rechecking === p.id}
                        className="rounded-lg border border-border px-2.5 py-1 text-xs text-muted transition-colors hover:border-accent hover:text-accent disabled:opacity-50"
                      >
                        {rechecking === p.id ? "Проверяю…" : "Перепроверить"}
                      </button>
                      <SuButton
                        onClick={() => {
                          setRefundKind("");
                          setClawback(false);
                          setNotice(null);
                          setRefunding(p);
                        }}
                        className="cursor-pointer rounded-lg border border-border px-2.5 py-1 text-xs text-muted transition-colors enabled:hover:border-rose-400 enabled:hover:text-rose-300 disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        Отметить возврат
                      </SuButton>
                      <SuCaption />
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {payments.length < count && (
        <div className="flex justify-center">
          <button
            onClick={() => load(page + 1, true)}
            disabled={loadingMore}
            className="rounded-xl border border-border px-6 py-2.5 text-sm text-muted transition-colors hover:border-accent hover:text-accent disabled:opacity-50"
          >
            {loadingMore
              ? "Загружаю…"
              : `Ещё (показано ${nf(payments.length)} из ${nf(count)})`}
          </button>
        </div>
      )}

      {refunding && (
        <ReasonDialog
          title="Отметить возврат платежа"
          description={
            <>
              {refunding.user_email || "—"} · {nf(refunding.amount)} {refunding.currency} ·{" "}
              <span className="break-all font-mono text-xs">{refunding.order_id}</span>
              <br />
              Комиссия креатора по этому платежу будет отменена. Деньги покупателю панель не возвращает — отметка
              нужна, когда о возврате не сообщил сам провайдер.
            </>
          }
          reason="required"
          confirmLabel="Отметить"
          danger
          canSubmit={refundKind !== ""}
          confirmText={`Отметить платёж как «${refundKind === "fraud" ? "Мошенничество" : "Возврат"}»${
            clawback ? " и изъять кредиты покупателя" : ""
          }?`}
          onClose={() => setRefunding(null)}
          onSubmit={async (reason) => {
            if (refundKind === "") return null;
            const res = await adminMarkRefunded<Payment>(refunding.id, {
              kind: refundKind,
              reason,
              clawback_credits: clawback,
            });
            if (!res.ok) return res.error;
            const fresh = res.data.payment;
            setPayments((prev) => prev.map((p) => (p.id === refunding.id ? fresh : p)));
            setNotice(
              `Отменено комиссий: ${nf(res.data.reversed)}, изъято кредитов: ${nf(res.data.clawback_debited)}`
            );
            return null;
          }}
        >
          <fieldset className="space-y-2 text-sm">
            <legend className="text-muted">Вид отметки *</legend>
            {REFUND_KINDS.map((option) => (
              <label key={option.key} className="flex cursor-pointer items-center gap-2">
                <input
                  type="radio"
                  name="refund-kind"
                  checked={refundKind === option.key}
                  onChange={() => setRefundKind(option.key)}
                  className="accent-accent"
                />
                {option.label}
              </label>
            ))}
          </fieldset>
          <label className="flex cursor-pointer items-start gap-2 text-sm">
            <input
              type="checkbox"
              checked={clawback}
              onChange={(e) => setClawback(e.target.checked)}
              className="mt-0.5 accent-accent"
            />
            <span>
              Изъять кредиты покупателя
              <span className="block text-xs text-muted-2">
                Кредиты этого заказа будут списаны с баланса покупателя. Если платёж уже отмечен, повторная отметка
                принимается только чтобы добавить изъятие.
              </span>
            </span>
          </label>
        </ReasonDialog>
      )}
    </div>
  );
}
