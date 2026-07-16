"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { fetchData } from "@/tools/fetchData";
import { FiSearch, FiClock, FiPlusCircle } from "react-icons/fi";

type AdminUser = {
  id: number;
  email: string;
  username: string;
  first_name: string;
  last_name: string;
  telegram: string;
  token_balance: number;
  is_paid: boolean;
  is_staff: boolean;
  date_joined: string;
  last_login: string | null;
};

type UsersResponse = { count: number; results: AdminUser[] };

type Tx = {
  id: number;
  delta: number;
  reason: string;
  balance_after: number;
  created_at: string;
  meta: Record<string, unknown> | null;
};

const INPUT =
  "rounded-lg bg-surface-2 border border-border px-3 py-2 text-sm text-foreground focus:border-accent outline-none";

const nf = (n: number) => (n ?? 0).toLocaleString("ru-RU");

const fmtDate = (s: string | null) => {
  if (!s) return "—";
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

const REASON_LABELS: Record<string, string> = {
  admin: "Админ",
  purchase: "Покупка",
  welcome: "Приветственный бонус",
  bonus: "Бонус",
  daily_bonus: "Ежедневный бонус",
  chat: "Чат",
  refund: "Возврат",
};

export default function AdminUsersPage() {
  const [q, setQ] = useState("");
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [count, setCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Раскрытая строка: режим «кредиты» или «история»
  const [expanded, setExpanded] = useState<{ id: number; mode: "credit" | "history" } | null>(
    null
  );

  // Форма начисления
  const [amount, setAmount] = useState("");
  const [note, setNote] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [creditMsg, setCreditMsg] = useState<string | null>(null);

  // История
  const [txs, setTxs] = useState<Tx[] | null>(null);
  const [txLoading, setTxLoading] = useState(false);

  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const load = useCallback(async (query: string) => {
    setLoading(true);
    setError(null);
    const res = await fetchData<UsersResponse>(
      `manage/users/?q=${encodeURIComponent(query)}`,
      "GET",
      null,
      true
    );
    if (res.ok && res.data) {
      setUsers(res.data.results || []);
      setCount(res.data.count || 0);
    } else {
      setError(res.error || "Не удалось загрузить пользователей");
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    load("");
  }, [load]);

  const onSearch = (value: string) => {
    setQ(value);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => load(value.trim()), 400);
  };

  const openCredit = (id: number) => {
    setAmount("");
    setNote("");
    setCreditMsg(null);
    setExpanded((prev) =>
      prev && prev.id === id && prev.mode === "credit" ? null : { id, mode: "credit" }
    );
  };

  const openHistory = async (id: number) => {
    const willClose = expanded && expanded.id === id && expanded.mode === "history";
    if (willClose) {
      setExpanded(null);
      return;
    }
    setExpanded({ id, mode: "history" });
    setTxs(null);
    setTxLoading(true);
    const res = await fetchData<Tx[]>(`manage/users/${id}/transactions/`, "GET", null, true);
    setTxs(res.ok && Array.isArray(res.data) ? res.data : []);
    setTxLoading(false);
  };

  const submitCredit = async (id: number) => {
    const n = parseInt(amount, 10);
    if (!n || isNaN(n)) {
      setCreditMsg("Введите сумму (можно отрицательную для списания)");
      return;
    }
    setSubmitting(true);
    setCreditMsg(null);
    const res = await fetchData<{ ok: boolean; balance: number }>(
      `manage/users/${id}/credit/`,
      "POST",
      { amount: n, note },
      true
    );
    setSubmitting(false);
    if (res.ok && res.data) {
      const balance = res.data.balance;
      setUsers((prev) =>
        prev.map((u) => (u.id === id ? { ...u, token_balance: balance } : u))
      );
      setCreditMsg(
        `Готово! ${n > 0 ? "Начислено" : "Списано"} ${nf(Math.abs(n))} кр. Новый баланс: ${nf(
          balance
        )}`
      );
      setAmount("");
      setNote("");
    } else {
      setCreditMsg(`Ошибка: ${res.error || "не удалось выполнить операцию"}`);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Пользователи</h1>
        <p className="mt-1 text-sm text-muted">
          Поиск по email, имени или Telegram. Всего найдено: {nf(count)}.
        </p>
      </div>

      <div className="relative max-w-md">
        <FiSearch className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-2" />
        <input
          type="text"
          placeholder="Поиск: email, имя, @telegram…"
          className={`${INPUT} w-full pl-9`}
          value={q}
          onChange={(e) => onSearch(e.target.value)}
        />
      </div>

      {loading ? (
        <div className="h-96 animate-pulse rounded-2xl bg-surface-2" />
      ) : error ? (
        <div className="rounded-2xl border border-border bg-surface p-6 text-sm text-muted">
          Ошибка загрузки: {error}
        </div>
      ) : (
        <div className="overflow-x-auto rounded-2xl border border-border bg-surface">
          <table className="w-full min-w-[820px] text-sm">
            <thead>
              <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted-2">
                <th className="px-4 py-3 font-medium">Пользователь</th>
                <th className="px-4 py-3 font-medium">Баланс</th>
                <th className="px-4 py-3 text-center font-medium">Платный</th>
                <th className="px-4 py-3 font-medium">Регистрация</th>
                <th className="px-4 py-3 font-medium">Действия</th>
              </tr>
            </thead>
            <tbody>
              {users.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-4 py-8 text-center text-muted">
                    Никого не найдено.
                  </td>
                </tr>
              )}
              {users.map((u) => {
                const isOpen = expanded?.id === u.id;
                const fio = [u.first_name, u.last_name].filter(Boolean).join(" ");
                return (
                  <UserRows
                    key={u.id}
                    u={u}
                    fio={fio}
                    isOpen={Boolean(isOpen)}
                    mode={isOpen ? expanded!.mode : null}
                    amount={amount}
                    note={note}
                    submitting={submitting}
                    creditMsg={creditMsg}
                    txs={txs}
                    txLoading={txLoading}
                    setAmount={setAmount}
                    setNote={setNote}
                    openCredit={openCredit}
                    openHistory={openHistory}
                    submitCredit={submitCredit}
                  />
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function UserRows({
  u,
  fio,
  isOpen,
  mode,
  amount,
  note,
  submitting,
  creditMsg,
  txs,
  txLoading,
  setAmount,
  setNote,
  openCredit,
  openHistory,
  submitCredit,
}: {
  u: AdminUser;
  fio: string;
  isOpen: boolean;
  mode: "credit" | "history" | null;
  amount: string;
  note: string;
  submitting: boolean;
  creditMsg: string | null;
  txs: Tx[] | null;
  txLoading: boolean;
  setAmount: (v: string) => void;
  setNote: (v: string) => void;
  openCredit: (id: number) => void;
  openHistory: (id: number) => void;
  submitCredit: (id: number) => void;
}) {
  return (
    <>
      <tr className="border-b border-border last:border-0 hover:bg-surface-2">
        <td className="px-4 py-3">
          <div className="font-medium">{u.email || u.username}</div>
          <div className="mt-0.5 text-xs text-muted-2">
            {fio && <span>{fio}</span>}
            {fio && u.telegram && <span> · </span>}
            {u.telegram && <span>@{u.telegram.replace(/^@/, "")}</span>}
            {u.is_staff && <span className="ml-1 text-accent">· админ</span>}
          </div>
        </td>
        <td className="whitespace-nowrap px-4 py-3 font-bold">{nf(u.token_balance)} кр</td>
        <td className="px-4 py-3 text-center">
          {u.is_paid ? (
            <span className="text-emerald-400">✓</span>
          ) : (
            <span className="text-muted-2">—</span>
          )}
        </td>
        <td className="whitespace-nowrap px-4 py-3 text-muted">{fmtDate(u.date_joined)}</td>
        <td className="whitespace-nowrap px-4 py-3">
          <div className="flex gap-2">
            <button
              onClick={() => openCredit(u.id)}
              className={`inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-xs transition-colors hover:border-accent hover:text-accent ${
                isOpen && mode === "credit" ? "border-accent text-accent" : "text-muted"
              }`}
            >
              <FiPlusCircle className="h-3.5 w-3.5" />± Кредиты
            </button>
            <button
              onClick={() => openHistory(u.id)}
              className={`inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-xs transition-colors hover:border-accent hover:text-accent ${
                isOpen && mode === "history" ? "border-accent text-accent" : "text-muted"
              }`}
            >
              <FiClock className="h-3.5 w-3.5" />
              История
            </button>
          </div>
        </td>
      </tr>

      {isOpen && (
        <tr className="border-b border-border last:border-0 bg-surface-2/50">
          <td colSpan={5} className="px-4 py-4">
            {mode === "credit" ? (
              <div className="max-w-2xl">
                <div className="mb-2 text-sm font-medium">
                  Начислить или списать кредиты — {u.email || u.username}
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <input
                    type="number"
                    placeholder="Сумма (напр. 500 или -200)"
                    className="rounded-lg bg-surface-2 border border-border px-3 py-2 text-sm text-foreground focus:border-accent outline-none w-52"
                    value={amount}
                    onChange={(e) => setAmount(e.target.value)}
                  />
                  <input
                    type="text"
                    placeholder="Комментарий (зачем)"
                    className="rounded-lg bg-surface-2 border border-border px-3 py-2 text-sm text-foreground focus:border-accent outline-none w-64"
                    value={note}
                    onChange={(e) => setNote(e.target.value)}
                  />
                  <button
                    onClick={() => submitCredit(u.id)}
                    disabled={submitting}
                    className="rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-on-accent transition-opacity hover:opacity-90 disabled:opacity-50"
                  >
                    {submitting ? "Выполняю…" : "Применить"}
                  </button>
                </div>
                <p className="mt-2 text-xs text-muted-2">
                  Положительное число — начислить, отрицательное — списать (не уйдёт в минус).
                </p>
                {creditMsg && (
                  <p
                    className={`mt-2 text-sm ${
                      creditMsg.startsWith("Ошибка") ? "text-rose-400" : "text-emerald-400"
                    }`}
                  >
                    {creditMsg}
                  </p>
                )}
              </div>
            ) : (
              <div>
                <div className="mb-2 text-sm font-medium">История операций (последние 100)</div>
                {txLoading ? (
                  <div className="h-24 animate-pulse rounded-xl bg-surface-2" />
                ) : !txs || txs.length === 0 ? (
                  <p className="text-sm text-muted">Операций пока нет.</p>
                ) : (
                  <div className="overflow-x-auto rounded-xl border border-border">
                    <table className="w-full min-w-[560px] text-sm">
                      <thead>
                        <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted-2">
                          <th className="px-3 py-2 font-medium">Дата</th>
                          <th className="px-3 py-2 font-medium">Изменение</th>
                          <th className="px-3 py-2 font-medium">Причина</th>
                          <th className="px-3 py-2 font-medium">Баланс после</th>
                        </tr>
                      </thead>
                      <tbody>
                        {txs.map((t) => (
                          <tr key={t.id} className="border-b border-border last:border-0">
                            <td className="whitespace-nowrap px-3 py-2 text-muted">
                              {fmtDate(t.created_at)}
                            </td>
                            <td
                              className={`whitespace-nowrap px-3 py-2 font-medium ${
                                t.delta >= 0 ? "text-emerald-400" : "text-rose-400"
                              }`}
                            >
                              {t.delta >= 0 ? "+" : ""}
                              {nf(t.delta)}
                            </td>
                            <td className="px-3 py-2">
                              {REASON_LABELS[t.reason] || t.reason}
                            </td>
                            <td className="whitespace-nowrap px-3 py-2">
                              {nf(t.balance_after)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            )}
          </td>
        </tr>
      )}
    </>
  );
}
