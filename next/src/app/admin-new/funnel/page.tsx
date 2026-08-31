"use client";

import { useEffect, useState } from "react";
import { fetchData } from "@/tools/fetchData";
import { FiAlertCircle } from "react-icons/fi";

/**
 * Воронка оплаты.
 *
 * Клиент спросил: почему столько людей не заплатили и на каком шаге отвалились.
 * В таблице платежей все неоплаченные выглядели одинаково — «Неуспешно», хотя
 * за этим словом две совершенно разные истории. Человек, которому отказал банк,
 * и человек, который просто закрыл страницу оплаты, лечатся по-разному:
 * первому нужен другой способ платежа, второму — удобство и доверие.
 *
 * Поэтому здесь шаги идут сверху вниз, и у каждого видно, сколько людей до него
 * дошло и сколько потерялось на переходе.
 */

type Step = { key: string; label: string; count: number; lost: number; rate: number | null };
type Reason = { key: string; label: string; count: number; hint: string };
type Report = {
  days: number;
  steps: Step[];
  reasons: Reason[];
  by_currency: { currency: string; всего: number; оплачено: number }[];
  by_package: { package_id: number; всего: number; оплачено: number }[];
  conversion: number | null;
};

const PERIODS = [7, 30, 90];

export default function AdminFunnelPage() {
  const [data, setData] = useState<Report | null>(null);
  const [days, setDays] = useState(30);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    (async () => {
      const res = await fetchData<Report>(`manage/funnel/?days=${days}`, "GET", null, true);
      if (!alive) return;
      if (res.ok && res.data) setData(res.data);
      setLoading(false);
    })();
    return () => {
      alive = false;
    };
  }, [days]);

  if (loading && !data) {
    return (
      <div className="space-y-4">
        <div className="h-8 w-48 animate-pulse rounded-lg bg-surface-2" />
        <div className="h-64 animate-pulse rounded-2xl bg-surface-2" />
      </div>
    );
  }

  const steps = data?.steps || [];
  const top = steps.length ? Math.max(...steps.map((s) => s.count), 1) : 1;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Воронка оплаты</h1>
          <p className="mt-1 max-w-2xl text-sm text-muted">
            Где теряются те, кто хотел заплатить. «Ушёл и не вернулся» и «отказано» —
            разные беды: первая лечится удобством оплаты, вторая — другим способом платежа.
          </p>
        </div>
        <div className="inline-flex rounded-xl border border-border p-1">
          {PERIODS.map((d) => (
            <button
              key={d}
              type="button"
              onClick={() => setDays(d)}
              className={`rounded-lg px-3 py-1.5 text-sm transition-colors ${
                days === d ? "bg-accent text-on-accent" : "text-muted hover:text-foreground"
              }`}
            >
              {d} дн.
            </button>
          ))}
        </div>
      </div>

      {data?.conversion !== null && data?.conversion !== undefined && (
        <div className="rounded-2xl border border-border bg-surface p-5">
          <div className="text-sm text-muted">Доходит до оплаты</div>
          <div className="mt-1 text-3xl font-bold">{data.conversion}%</div>
          <div className="mt-1 text-xs text-muted-2">
            от тех, кто ушёл на страницу оплаты
          </div>
        </div>
      )}

      <div className="rounded-2xl border border-border bg-surface p-5">
        <h2 className="text-base font-semibold">Шаги</h2>
        <div className="mt-4 space-y-3">
          {steps.map((s, i) => (
            <div key={s.key}>
              <div className="flex items-baseline justify-between gap-3 text-sm">
                <span className="text-foreground">{s.label}</span>
                <span className="shrink-0 tabular-nums text-muted">
                  {s.count.toLocaleString("ru-RU")}
                  {s.rate !== null && (
                    <span className={s.rate < 50 ? "ml-2 text-amber-400" : "ml-2 text-muted-2"}>
                      {s.rate}%
                    </span>
                  )}
                </span>
              </div>
              <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-surface-2">
                <div
                  className="h-full rounded-full bg-accent"
                  style={{ width: `${Math.max(2, (s.count * 100) / top)}%` }}
                />
              </div>
              {i > 0 && s.lost > 0 && (
                <div className="mt-1 text-xs text-muted-2">
                  потеряли на этом переходе: {s.lost.toLocaleString("ru-RU")}
                </div>
              )}
            </div>
          ))}
        </div>
        {steps[0]?.count === 0 && (
          <p className="mt-4 flex items-start gap-2 rounded-xl bg-amber-500/10 px-3 py-2 text-xs text-amber-300">
            <FiAlertCircle className="mt-0.5 shrink-0" />
            Первые два шага считаются с момента установки счётчиков — за прошлые
            периоды они будут пустыми.
          </p>
        )}
      </div>

      <div className="rounded-2xl border border-border bg-surface p-5">
        <h2 className="text-base font-semibold">Почему не заплатили</h2>
        <div className="mt-4 space-y-3">
          {(data?.reasons || []).map((r) => (
            <div key={r.key} className="rounded-xl bg-surface-2 p-4">
              <div className="flex items-baseline justify-between gap-3">
                <span className="font-medium">{r.label}</span>
                <span className="text-xl font-bold tabular-nums">{r.count}</span>
              </div>
              <p className="mt-1 text-xs text-muted-2">{r.hint}</p>
            </div>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="rounded-2xl border border-border bg-surface p-5">
          <h2 className="text-base font-semibold">По валюте</h2>
          <table className="mt-3 w-full text-sm">
            <thead className="text-xs uppercase text-muted-2">
              <tr>
                <th className="pb-2 text-left">Валюта</th>
                <th className="pb-2 text-right">Попыток</th>
                <th className="pb-2 text-right">Оплат</th>
                <th className="pb-2 text-right">Доля</th>
              </tr>
            </thead>
            <tbody>
              {(data?.by_currency || []).map((r) => (
                <tr key={r.currency} className="border-t border-border">
                  <td className="py-2">{r.currency}</td>
                  <td className="py-2 text-right tabular-nums">{r.всего}</td>
                  <td className="py-2 text-right tabular-nums">{r.оплачено}</td>
                  <td className="py-2 text-right tabular-nums text-muted">
                    {r.всего ? Math.round((r.оплачено * 100) / r.всего) : 0}%
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="rounded-2xl border border-border bg-surface p-5">
          <h2 className="text-base font-semibold">По пакетам</h2>
          <table className="mt-3 w-full text-sm">
            <thead className="text-xs uppercase text-muted-2">
              <tr>
                <th className="pb-2 text-left">Пакет</th>
                <th className="pb-2 text-right">Попыток</th>
                <th className="pb-2 text-right">Оплат</th>
                <th className="pb-2 text-right">Доля</th>
              </tr>
            </thead>
            <tbody>
              {(data?.by_package || []).map((r) => (
                <tr key={r.package_id} className="border-t border-border">
                  <td className="py-2">#{r.package_id}</td>
                  <td className="py-2 text-right tabular-nums">{r.всего}</td>
                  <td className="py-2 text-right tabular-nums">{r.оплачено}</td>
                  <td className="py-2 text-right tabular-nums text-muted">
                    {r.всего ? Math.round((r.оплачено * 100) / r.всего) : 0}%
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
