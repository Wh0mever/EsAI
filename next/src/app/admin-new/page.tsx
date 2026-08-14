"use client";

import { useEffect, useState } from "react";
import { fetchData } from "@/tools/fetchData";
import {
  FiUsers,
  FiTrendingUp,
  FiZap,
  FiMessageSquare,
  FiDollarSign,
  FiGift,
} from "react-icons/fi";

type RecentPayment = {
  id: number;
  created_at: string;
  user_email: string;
  amount: number;
  currency: string;
  success: boolean;
  order_id: string;
};

type Summary = {
  users_total: number;
  users_paid: number;
  revenue_kgs: number;
  credits_spent_total: number;
  credits_spent_today: number;
  requests_today: number;
  requests_total: number;
  balance_openrouter_usd: number | null;
  recent_payments: RecentPayment[];
};

/**
 * Статистика попапа скидки при уходе (exit-intent) — GET manage/exit-discount/stats/.
 *
 * Имена полей ДОЛЖНЫ совпадать с ответом ExitDiscountStatsView
 * (core/adminapi/views.py). Раньше здесь были shown_count/claimed_count/
 * paid_count/claim_rate — таких полей бэкенд не отдаёт, они приходили
 * undefined, и админка вечно показывала 0/0/0, хотя скидка исправно
 * работала (на момент починки: 54 показа, 12 забрали). Клиент из-за этого
 * решил, что механика сломана.
 */
type ExitDiscountStats = {
  shown: number;
  claimed: number;
  redeemed: number;
  claim_rate_pct?: number;
  redeem_rate_pct?: number;
};

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

export default function AdminDashboardPage() {
  const [data, setData] = useState<Summary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const [exitStats, setExitStats] = useState<ExitDiscountStats | null>(null);
  const [exitStatsError, setExitStatsError] = useState<string | null>(null);
  const [exitStatsLoading, setExitStatsLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    (async () => {
      const res = await fetchData<Summary>("manage/summary/", "GET", null, true);
      if (!alive) return;
      if (res.ok && res.data) setData(res.data);
      else setError(res.error || "Не удалось загрузить данные");
      setLoading(false);
    })();
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    let alive = true;
    (async () => {
      const res = await fetchData<ExitDiscountStats>("manage/exit-discount/stats/", "GET", null, true);
      if (!alive) return;
      if (res.ok && res.data) setExitStats(res.data);
      else setExitStatsError(res.error || "Не удалось загрузить статистику");
      setExitStatsLoading(false);
    })();
    return () => {
      alive = false;
    };
  }, []);

  if (loading) {
    return (
      <div className="space-y-4">
        <div className="h-8 w-40 animate-pulse rounded-lg bg-surface-2" />
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {[0, 1, 2, 3, 4].map((i) => (
            <div key={i} className="h-28 animate-pulse rounded-2xl bg-surface-2" />
          ))}
        </div>
        <div className="h-64 animate-pulse rounded-2xl bg-surface-2" />
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="rounded-2xl border border-border bg-surface p-6 text-sm text-muted">
        Ошибка загрузки: {error || "нет данных"}
      </div>
    );
  }

  const cards = [
    {
      icon: FiUsers,
      label: "Пользователи",
      value: nf(data.users_total),
      sub: `из них платных: ${nf(data.users_paid)}`,
    },
    {
      icon: FiTrendingUp,
      label: "Выручка",
      value: `${nf(data.revenue_kgs)} сом`,
      sub: "успешные платежи",
    },
    {
      icon: FiZap,
      label: "Потрачено кредитов",
      value: nf(data.credits_spent_total),
      sub: `сегодня: ${nf(data.credits_spent_today)}`,
    },
    {
      icon: FiMessageSquare,
      label: "Запросов сегодня",
      value: nf(data.requests_today),
      sub: `всего: ${nf(data.requests_total)}`,
    },
    {
      icon: FiDollarSign,
      label: "Баланс OpenRouter",
      value:
        data.balance_openrouter_usd === null
          ? "—"
          : `$${data.balance_openrouter_usd.toLocaleString("ru-RU", {
              maximumFractionDigits: 2,
            })}`,
      sub: "остаток на API-счёте",
    },
  ];

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">Дашборд</h1>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {cards.map((c) => {
          const Icon = c.icon;
          return (
            <div
              key={c.label}
              className="rounded-2xl border border-border bg-surface p-5"
            >
              <div className="flex items-center gap-2 text-sm text-muted">
                <Icon className="h-4 w-4 text-accent" />
                {c.label}
              </div>
              <div className="mt-2 text-2xl font-semibold tracking-tight">{c.value}</div>
              <div className="mt-1 text-xs text-muted-2">{c.sub}</div>
            </div>
          );
        })}
      </div>

      <section className="rounded-2xl border border-border bg-surface">
        <h2 className="px-5 pt-5 text-base font-semibold">Последние платежи</h2>
        {data.recent_payments.length === 0 ? (
          <p className="px-5 pb-5 pt-3 text-sm text-muted">Платежей пока нет.</p>
        ) : (
          <div className="mt-3 overflow-x-auto pb-2">
            <table className="w-full min-w-[560px] text-sm">
              <thead>
                <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted-2">
                  <th className="px-5 py-2.5 font-medium">Дата</th>
                  <th className="px-5 py-2.5 font-medium">Email</th>
                  <th className="px-5 py-2.5 font-medium">Сумма</th>
                  <th className="px-5 py-2.5 font-medium">Статус</th>
                </tr>
              </thead>
              <tbody>
                {data.recent_payments.map((p) => (
                  <tr
                    key={p.id}
                    className="border-b border-border last:border-0 hover:bg-surface-2"
                  >
                    <td className="whitespace-nowrap px-5 py-3 text-muted">
                      {fmtDate(p.created_at)}
                    </td>
                    <td className="px-5 py-3">{p.user_email}</td>
                    <td className="whitespace-nowrap px-5 py-3 font-medium">
                      {nf(p.amount)} {p.currency}
                    </td>
                    <td className="px-5 py-3">
                      {p.success ? (
                        <span className="text-emerald-400">✓ Успешно</span>
                      ) : (
                        <span className="text-rose-400">✗ Неуспешно</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="rounded-2xl border border-border bg-surface p-5">
        <h2 className="text-base font-semibold">Скидка при уходе</h2>

        {exitStatsLoading ? (
          <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-3">
            {[0, 1, 2].map((i) => (
              <div key={i} className="h-20 animate-pulse rounded-xl bg-surface-2" />
            ))}
          </div>
        ) : exitStatsError || !exitStats ? (
          <p className="mt-3 text-sm text-muted">
            Ошибка загрузки: {exitStatsError || "нет данных"}
          </p>
        ) : (
          <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-3">
            <div className="rounded-xl border border-border bg-surface-2 p-4">
              <div className="flex items-center gap-2 text-sm text-muted">
                <FiGift className="h-4 w-4 text-accent" />
                Показано
              </div>
              <div className="mt-2 text-2xl font-semibold tracking-tight">
                {nf(exitStats.shown)}
              </div>
            </div>
            <div className="rounded-xl border border-border bg-surface-2 p-4">
              <div className="flex items-center gap-2 text-sm text-muted">
                <FiGift className="h-4 w-4 text-accent" />
                Забрали
              </div>
              <div className="mt-2 text-2xl font-semibold tracking-tight">
                {nf(exitStats.claimed)}
              </div>
              <div className="mt-1 text-xs text-muted-2">
                {exitStats.claim_rate_pct != null
                  ? `${exitStats.claim_rate_pct.toLocaleString("ru-RU", { maximumFractionDigits: 1 })}% от показанных`
                  : exitStats.shown
                  ? `${((exitStats.claimed / exitStats.shown) * 100).toFixed(1)}% от показанных`
                  : "—"}
              </div>
            </div>
            <div className="rounded-xl border border-border bg-surface-2 p-4">
              <div className="flex items-center gap-2 text-sm text-muted">
                <FiGift className="h-4 w-4 text-accent" />
                Оплатили
              </div>
              <div className="mt-2 text-2xl font-semibold tracking-tight">
                {nf(exitStats.redeemed)}
              </div>
              <div className="mt-1 text-xs text-muted-2">
                {exitStats.redeem_rate_pct != null
                  ? `${exitStats.redeem_rate_pct.toLocaleString("ru-RU", { maximumFractionDigits: 1 })}% от забравших`
                  : exitStats.claimed
                  ? `${((exitStats.redeemed / exitStats.claimed) * 100).toFixed(1)}% от забравших`
                  : "—"}
              </div>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
