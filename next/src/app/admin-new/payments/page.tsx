"use client";

import { useCallback, useEffect, useState } from "react";
import { fetchData } from "@/tools/fetchData";

type Payment = {
  id: number;
  created_at: string;
  user_email: string;
  amount: number;
  currency: string;
  success: boolean;
  order_id: string;
  description: string;
  error: string;
};

type PaymentsResponse = { count: number; results: Payment[] };

const nf = (n: number) => (n ?? 0).toLocaleString("ru-RU");

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

export default function AdminPaymentsPage() {
  const [payments, setPayments] = useState<Payment[]>([]);
  const [count, setCount] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (pageNum: number, append: boolean) => {
    if (append) setLoadingMore(true);
    else setLoading(true);
    const res = await fetchData<PaymentsResponse>(
      `manage/payments/?page=${pageNum}`,
      "GET",
      null,
      true
    );
    if (res.ok && res.data) {
      const results = res.data.results || [];
      setCount(res.data.count || 0);
      setPayments((prev) => (append ? [...prev, ...results] : results));
      setPage(pageNum);
    } else if (!append) {
      setError(res.error || "Не удалось загрузить платежи");
    }
    setLoading(false);
    setLoadingMore(false);
  }, []);

  useEffect(() => {
    load(1, false);
  }, [load]);

  if (loading) {
    return (
      <div className="space-y-4">
        <div className="h-8 w-40 animate-pulse rounded-lg bg-surface-2" />
        <div className="h-96 animate-pulse rounded-2xl bg-surface-2" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-2xl border border-border bg-surface p-6 text-sm text-muted">
        Ошибка загрузки: {error}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Платежи</h1>
        <p className="mt-1 text-sm text-muted">
          Все попытки оплаты, новые сверху. Всего: {nf(count)}.
        </p>
      </div>

      <div className="overflow-x-auto rounded-2xl border border-border bg-surface">
        <table className="w-full min-w-[820px] text-sm">
          <thead>
            <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted-2">
              <th className="px-4 py-3 font-medium">Дата</th>
              <th className="px-4 py-3 font-medium">Email</th>
              <th className="px-4 py-3 font-medium">Сумма</th>
              <th className="px-4 py-3 font-medium">Статус</th>
              <th className="px-4 py-3 font-medium">Заказ</th>
              <th className="px-4 py-3 font-medium">Ошибка</th>
            </tr>
          </thead>
          <tbody>
            {payments.length === 0 && (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-muted">
                  Платежей пока нет.
                </td>
              </tr>
            )}
            {payments.map((p) => (
              <tr
                key={p.id}
                className="border-b border-border last:border-0 hover:bg-surface-2"
              >
                <td className="whitespace-nowrap px-4 py-3 text-muted">
                  {fmtDate(p.created_at)}
                </td>
                <td className="px-4 py-3">{p.user_email}</td>
                <td className="whitespace-nowrap px-4 py-3 font-medium">
                  {nf(p.amount)} {p.currency}
                </td>
                <td className="whitespace-nowrap px-4 py-3">
                  {p.success ? (
                    <span className="text-emerald-400">✓ Успешно</span>
                  ) : (
                    <span className="text-rose-400">✗ Неуспешно</span>
                  )}
                </td>
                <td className="max-w-[180px] truncate px-4 py-3 font-mono text-xs text-muted-2">
                  {p.order_id}
                </td>
                <td className="max-w-[220px] truncate px-4 py-3 text-xs text-rose-400/80">
                  {p.error || ""}
                </td>
              </tr>
            ))}
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
    </div>
  );
}
