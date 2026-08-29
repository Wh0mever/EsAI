"use client";

import { useEffect, useState } from "react";
import { fetchData } from "@/tools/fetchData";
import {
  FiAlertTriangle,
  FiCheck,
  FiCheckCircle,
  FiLoader,
  FiPlus,
  FiRefreshCw,
  FiTrash2,
} from "react-icons/fi";

/**
 * Аккаунты OpenRouter.
 *
 * Ключ был один и лежал строкой в настройках. Когда на нём кончались деньги,
 * вставало всё: чат, картинки, видео и студия, — а пополнение шло вручную и не
 * всегда вовремя. Здесь можно держать запасной аккаунт и переключиться на него
 * в один клик, не заходя на сервер.
 *
 * Ключи целиком не показываются даже администратору: в списке только огрызок.
 * Секрет, который незачем показывать, утечёт с первым же скриншотом в
 * переписке.
 */

type Account = {
  id: number;
  title: string;
  key_masked: string;
  is_active: boolean;
  auto_switch: boolean;
  auto_switched_at: string | null;
  note: string;
  balance_usd: number | null;
  spent_usd: number | null;
  limit_usd: number | null;
  checked_at: string | null;
  last_error: string;
};

const INPUT =
  "rounded-lg bg-surface-2 border border-border px-3 py-2 text-sm text-foreground focus:border-accent outline-none";

/** Ниже этой суммы аккаунт подсвечивается: пора пополнять или переключаться. */
const LOW_BALANCE = 15;

type Payload = { accounts: Account[]; auto_switch_below: number };

function money(v: number | null): string {
  return v === null || v === undefined ? "—" : `$${v.toFixed(2)}`;
}

function when(iso: string | null): string {
  if (!iso) return "не проверялся";
  const d = new Date(iso);
  return d.toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

export default function AdminOpenRouterPage() {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<string>("");
  const [below, setBelow] = useState<number>(2);
  const [title, setTitle] = useState("");
  const [key, setKey] = useState("");
  const [addError, setAddError] = useState("");

  const apply = (d?: Payload | null) => {
    if (!d) return false;
    setAccounts(d.accounts || []);
    if (typeof d.auto_switch_below === "number") setBelow(d.auto_switch_below);
    return true;
  };

  const load = async () => {
    const res = await fetchData<Payload>("manage/openrouter/", "GET", null, true);
    if (!(res.ok && apply(res.data))) setError(res.error || "Не удалось загрузить аккаунты");
    setLoading(false);
  };

  const saveBelow = async (value: number) => {
    setBusy("below");
    const res = await fetchData<Payload>(
      "manage/openrouter/", "PATCH", { auto_switch_below: value }, true
    );
    setBusy("");
    apply(res.data);
  };

  const toggleSpare = async (a: Account, on: boolean) => {
    setBusy(`spare-${a.id}`);
    const res = await fetchData<Account>(
      `manage/openrouter/${a.id}/`, "PATCH", { auto_switch: on }, true
    );
    setBusy("");
    if (res.ok && res.data) {
      const updated = res.data as Account;
      setAccounts((prev) => prev.map((x) => (x.id === updated.id ? updated : x)));
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const add = async () => {
    if (!key.trim()) return;
    setBusy("add");
    setAddError("");
    const res = await fetchData<Account>(
      "manage/openrouter/", "POST", { title: title.trim(), api_key: key.trim() }, true
    );
    setBusy("");
    if (res.ok && res.data) {
      setAccounts((prev) => [...prev, res.data as Account]);
      setTitle("");
      setKey("");
      void load();
    } else {
      setAddError((res.data as any)?.detail || res.error || "Не удалось подключить");
    }
  };

  const activate = async (a: Account) => {
    setBusy(`act-${a.id}`);
    const res = await fetchData<Payload>(`manage/openrouter/${a.id}/activate/`, "POST", {}, true);
    setBusy("");
    if (!(res.ok && apply(res.data))) alert((res.data as any)?.detail || "Не удалось переключиться");
  };

  const refresh = async (a?: Account) => {
    setBusy(a ? `ref-${a.id}` : "ref-all");
    const url = a ? `manage/openrouter/${a.id}/refresh/` : "manage/openrouter/refresh/";
    const res = await fetchData<Payload>(url, "POST", {}, true);
    setBusy("");
    apply(res.data);
  };

  const remove = async (a: Account) => {
    if (!confirm(`Убрать аккаунт «${a.title}»?`)) return;
    setBusy(`del-${a.id}`);
    const res = await fetchData(`manage/openrouter/${a.id}/`, "DELETE", null, true);
    setBusy("");
    if (res.ok) setAccounts((prev) => prev.filter((x) => x.id !== a.id));
    else alert((res.data as any)?.detail || "Не удалось убрать");
  };

  if (loading) {
    return (
      <div className="space-y-4">
        <div className="h-8 w-56 animate-pulse rounded-lg bg-surface-2" />
        <div className="h-40 animate-pulse rounded-2xl bg-surface-2" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Аккаунты OpenRouter</h1>
          <p className="mt-1 max-w-2xl text-sm text-muted">
            С активного аккаунта идут все запросы сайта: чат, картинки, видео и студия.
            Когда на нём заканчиваются деньги, переключитесь на запасной — всё продолжит
            работать сразу, перезапуск не нужен.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <label className="flex items-center gap-2 rounded-xl border border-border px-3 py-2 text-sm">
            <span className="text-muted">Переключаться, когда меньше</span>
            <span className="text-muted-2">$</span>
            <input
              type="number"
              min={0}
              step={1}
              value={below}
              onChange={(e) => setBelow(Number(e.target.value))}
              onBlur={() => void saveBelow(below)}
              className="w-16 bg-transparent text-foreground outline-none"
            />
            {busy === "below" && <FiLoader className="animate-spin text-muted-2" />}
          </label>
        <button
          type="button"
          onClick={() => void refresh()}
          disabled={busy === "ref-all"}
          className="inline-flex items-center gap-2 rounded-xl border border-border px-4 py-2 text-sm font-medium transition-colors hover:border-accent disabled:opacity-60"
        >
          {busy === "ref-all" ? <FiLoader className="animate-spin" /> : <FiRefreshCw />}
          Обновить балансы
        </button>
        </div>
      </div>

      {error && (
        <div className="rounded-2xl border border-border bg-surface p-4 text-sm text-muted">
          {error}
        </div>
      )}

      {!accounts.length && (
        <div className="rounded-2xl border border-dashed border-border p-6 text-sm text-muted">
          Аккаунтов пока нет — сайт работает на ключе из настроек. Подключите первый, и
          он сразу станет рабочим.
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {accounts.map((a) => {
          const low = a.balance_usd !== null && a.balance_usd < LOW_BALANCE;
          return (
            <div
              key={a.id}
              className={`rounded-2xl border bg-surface p-5 ${
                a.is_active ? "border-accent" : "border-border"
              }`}
            >
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-base font-semibold">{a.title}</span>
                    {a.is_active && (
                      <span className="inline-flex items-center gap-1 rounded-full bg-accent-soft px-2.5 py-0.5 text-xs font-medium text-accent">
                        <FiCheckCircle className="h-3.5 w-3.5" /> рабочий
                      </span>
                    )}
                  </div>
                  <div className="mt-1 font-mono text-xs text-muted-2">{a.key_masked}</div>
                </div>
                <div className="text-right">
                  <div
                    className={`text-2xl font-bold ${low ? "text-amber-400" : "text-foreground"}`}
                  >
                    {money(a.balance_usd)}
                  </div>
                  <div className="text-xs text-muted-2">
                    из {money(a.limit_usd)} · {when(a.checked_at)}
                  </div>
                </div>
              </div>

              {low && (
                <div className="mt-3 flex items-start gap-2 rounded-xl bg-amber-500/10 px-3 py-2 text-xs text-amber-300">
                  <FiAlertTriangle className="mt-0.5 shrink-0" />
                  Меньше ${LOW_BALANCE} — пополните или переключитесь на запасной.
                </div>
              )}

              {a.last_error && (
                <div className="mt-3 flex items-start gap-2 rounded-xl bg-red-500/10 px-3 py-2 text-xs text-red-300">
                  <FiAlertTriangle className="mt-0.5 shrink-0" />
                  {a.last_error}
                </div>
              )}

              {a.auto_switched_at && (
                <p className="mt-3 text-xs text-muted-2">
                  Включён автоматически {when(a.auto_switched_at)}
                </p>
              )}

              {a.note && <p className="mt-3 text-xs text-muted">{a.note}</p>}

              {/* Запасной. Молча увести расходы на чужой ключ, заведённый
                  «на потом», нельзя — поэтому переключение только на
                  отмеченные аккаунты. */}
              <label className="mt-3 flex cursor-pointer items-start gap-2 text-sm">
                <input
                  type="checkbox"
                  className="mt-0.5 h-4 w-4 accent-accent"
                  checked={a.auto_switch}
                  disabled={busy === `spare-${a.id}`}
                  onChange={(e) => void toggleSpare(a, e.target.checked)}
                />
                <span>
                  Запасной
                  <span className="block text-xs text-muted-2">
                    Включить автоматически, когда на рабочем останется меньше ${below}
                  </span>
                </span>
              </label>

              <div className="mt-4 flex flex-wrap items-center gap-2">
                {!a.is_active && (
                  <button
                    type="button"
                    onClick={() => void activate(a)}
                    disabled={busy === `act-${a.id}`}
                    className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-3.5 py-2 text-sm font-semibold text-on-accent transition-colors hover:bg-accent-strong disabled:opacity-60"
                  >
                    {busy === `act-${a.id}` ? <FiLoader className="animate-spin" /> : <FiCheck />}
                    Сделать рабочим
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => void refresh(a)}
                  disabled={busy === `ref-${a.id}`}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-sm transition-colors hover:border-accent disabled:opacity-60"
                >
                  {busy === `ref-${a.id}` ? (
                    <FiLoader className="animate-spin" />
                  ) : (
                    <FiRefreshCw />
                  )}
                  Баланс
                </button>
                {!a.is_active && (
                  <button
                    type="button"
                    onClick={() => void remove(a)}
                    disabled={busy === `del-${a.id}`}
                    className="ml-auto inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-sm text-muted transition-colors hover:border-red-500/60 hover:text-red-400 disabled:opacity-60"
                  >
                    <FiTrash2 />
                    Убрать
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>

      <div className="rounded-2xl border border-border bg-surface p-5">
        <h2 className="text-base font-semibold">Подключить аккаунт</h2>
        <p className="mt-1 text-sm text-muted">
          Ключ проверяется до сохранения: неработающий не подключится. Взять его можно на
          openrouter.ai → Keys.
        </p>
        <div className="mt-4 grid gap-3 sm:grid-cols-[1fr_2fr_auto]">
          <input
            className={INPUT}
            placeholder="Название, напр. «Резервный»"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
          <input
            className={`${INPUT} font-mono`}
            placeholder="sk-or-v1-…"
            value={key}
            onChange={(e) => setKey(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void add();
            }}
          />
          <button
            type="button"
            onClick={() => void add()}
            disabled={busy === "add" || !key.trim()}
            className="inline-flex items-center justify-center gap-2 rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-on-accent transition-colors hover:bg-accent-strong disabled:opacity-60"
          >
            {busy === "add" ? <FiLoader className="animate-spin" /> : <FiPlus />}
            Подключить
          </button>
        </div>
        {addError && <p className="mt-2 text-sm text-red-400">{addError}</p>}
      </div>
    </div>
  );
}
