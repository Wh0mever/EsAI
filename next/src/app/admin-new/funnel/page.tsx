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
type StudioStep = { key: string; label: string; count: number; share: number | null };
/** Покупки периода по способу оплаты: провайдер + выбранный в нашем окне способ. */
type MethodRow = { key: string; provider: string; method: string; label: string; всего: number; оплачено: number };
/**
 * Единый QR (GoPay). created / paid / expired — по платежам на сервере,
 * остальное — по устройствам (события экрана QR), поэтому числа разной природы.
 */
type QrFunnel = {
  created: number;
  shown: number;
  app_open: number;
  saved: number;
  other_method: number;
  paid: number;
  expired: number;
  paid_seen: number;
};

type Report = {
  studio?: StudioStep[];
  /** Видеостудия (/video-studio): та же форма, доля — от открывших видеостудию. */
  vstudio?: StudioStep[];
  days: number;
  steps: Step[];
  reasons: Reason[];
  by_currency: { currency: string; всего: number; оплачено: number }[];
  by_package: { package_id: number; всего: number; оплачено: number }[];
  /** Старый сервер этих двух ключей не присылает — блоки тогда просто не рисуются. */
  by_method?: MethodRow[];
  qr?: QrFunnel;
  conversion: number | null;
};

const PERIODS = [7, 30, 90];

const num = (n: number | undefined | null) => (Number(n) || 0).toLocaleString("ru-RU");

/** Подписи строки единого QR — в порядке пути покупателя. */
const QR_PARTS: { key: keyof QrFunnel; label: string }[] = [
  { key: "created", label: "создано" },
  { key: "shown", label: "экран показан" },
  { key: "app_open", label: "открыли приложение банка" },
  { key: "saved", label: "сохранили QR" },
  { key: "other_method", label: "ушли к другому способу" },
  { key: "paid", label: "оплачено" },
  { key: "expired", label: "истекло" },
  { key: "paid_seen", label: "увидели «Оплачено»" },
];

export default function AdminFunnelPage() {
  const [data, setData] = useState<Report | null>(null);
  const [days, setDays] = useState(30);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
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
  const byMethod = Array.isArray(data?.by_method) ? data.by_method : null;
  const qr = data?.qr && typeof data.qr === "object" ? data.qr : null;

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
              onClick={() => {
                // «Загрузка» включается здесь, а не в эффекте: тот же период
                // эффект не перезапустит, и флаг остался бы висеть.
                if (d === days) return;
                setLoading(true);
                setDays(d);
              }}
              className={`rounded-lg px-3 py-1.5 text-sm transition-colors ${
                days === d ? "bg-accent text-on-accent" : "text-muted hover:text-foreground"
              }`}
            >
              {d} дн.
            </button>
          ))}
        </div>
      </div>

      {/* Студия: гость проходит путь до входа и оплаты. Доля — от открывших
          студию, а не от прошлого шага: примерку и оплату можно пропустить. */}
      <ProductFunnel
        title="Студия мультфильмов"
        hint="Доля — от открывших студию. «Вошли после студии» — устройство открывало студию гостем, а потом появилось уже с аккаунтом."
        steps={data?.studio || []}
        firstKey="studio_view"
      />
      <ProductFunnel
        title="Видеостудия"
        hint="Доля — от открывших видеостудию. Исходы генераций (выдано, ошибка, потеряно) — в отчёте видеостудии и журнале генераций."
        steps={data?.vstudio || []}
        firstKey="vstudio_view"
      />

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

      {(byMethod || qr) && (
        <div className="rounded-2xl border border-border bg-surface p-5">
          <h2 className="text-base font-semibold">По способам оплаты</h2>
          {byMethod && (
            <div className="mt-3 overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-xs uppercase text-muted-2">
                  <tr>
                    <th className="pb-2 text-left">Способ</th>
                    <th className="pb-2 text-right">Всего</th>
                    <th className="pb-2 text-right">Оплачено</th>
                    <th className="pb-2 text-right">Конверсия</th>
                  </tr>
                </thead>
                <tbody>
                  {byMethod.length === 0 && (
                    <tr className="border-t border-border">
                      <td colSpan={4} className="py-3 text-center text-muted">
                        За период покупок не было.
                      </td>
                    </tr>
                  )}
                  {byMethod.map((r) => (
                    <tr key={r.key} className="border-t border-border">
                      <td className="py-2 pr-3">{r.label || r.key}</td>
                      <td className="py-2 text-right tabular-nums">{num(r.всего)}</td>
                      <td className="py-2 text-right tabular-nums">{num(r.оплачено)}</td>
                      <td className="py-2 text-right tabular-nums text-muted">
                        {r.всего ? Math.round((r.оплачено * 100) / r.всего) : 0}%
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {qr && (
            <div className="mt-4 rounded-xl bg-surface-2 p-4">
              <p className="text-sm leading-relaxed">
                <span className="font-medium">Единый QR:</span>{" "}
                {QR_PARTS.map((part, i) => (
                  <span key={part.key} className="whitespace-nowrap text-muted">
                    {i > 0 && <span className="text-muted-2"> · </span>}
                    {part.label} <span className="tabular-nums text-foreground">{num(qr[part.key])}</span>
                  </span>
                ))}
              </p>
              <p className="mt-2 text-xs text-muted-2">
                Оплачено и истекло — по платежам; остальное — по устройствам. «Увидели Оплачено» меньше, чем
                «оплачено»: многие платят в приложении банка и не возвращаются на вкладку.
              </p>
            </div>
          )}
        </div>
      )}

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

/** Воронка продукта (мультстудия, видеостудия): полоса — доля от первого шага. */
function ProductFunnel({
  title,
  hint,
  steps,
  firstKey,
}: {
  title: string;
  hint: string;
  steps: StudioStep[];
  firstKey: string;
}) {
  if (!steps.length) return null;
  const first = steps[0]?.count || 1;
  return (
    <div className="rounded-2xl border border-border bg-surface p-5">
      <h2 className="text-lg font-semibold">{title}</h2>
      <p className="mt-1 text-xs text-muted-2">{hint}</p>
      <div className="mt-4 flex flex-col gap-2">
        {steps.map((s) => (
          <div key={s.key} className="grid grid-cols-[minmax(0,14rem)_1fr_auto] items-center gap-3 text-sm">
            <span className="truncate text-muted">{s.label}</span>
            <div className="h-2 overflow-hidden rounded-full bg-surface-2">
              <div
                className="h-full rounded-full bg-accent"
                style={{ width: `${Math.max(2, Math.round((s.count * 100) / Math.max(first, 1)))}%` }}
              />
            </div>
            <span className="tabular-nums">
              {s.count}
              {s.share !== null && s.key !== firstKey && <span className="ml-1 text-xs text-muted-2">{s.share}%</span>}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
