"use client";

import { useEffect, useMemo, useState } from "react";
import { fetchData } from "@/tools/fetchData";
import { FiTag, FiPlus, FiTrash2, FiCheck } from "react-icons/fi";

type PromoCode = {
  id: number;
  code: string;
  bonus_credits: number;
  expires_at: string | null;
  max_activations: number | null;
  used_count: number;
  per_user_once: boolean;
  new_users_only: boolean;
  is_active: boolean;
  note: string;
};

type Editable = Pick<
  PromoCode,
  | "bonus_credits"
  | "expires_at"
  | "max_activations"
  | "per_user_once"
  | "new_users_only"
  | "is_active"
  | "note"
>;

const INPUT =
  "rounded-lg bg-surface-2 border border-border px-3 py-2 text-sm text-foreground focus:border-accent outline-none";

// ISO (или null) -> значение для <input type="datetime-local"> в локальном времени
function isoToLocalInput(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(
    d.getHours()
  )}:${pad(d.getMinutes())}`;
}

// значение datetime-local -> ISO (или null, если пусто)
function localInputToIso(v: string): string | null {
  if (!v.trim()) return null;
  const d = new Date(v);
  if (Number.isNaN(d.getTime())) return null;
  return d.toISOString();
}

function fmtExpires(iso: string | null): string {
  if (!iso) return "бессрочно";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

const EMPTY_FORM = {
  code: "",
  bonus_credits: "",
  expires_at: "", // datetime-local
  max_activations: "", // пусто = без лимита
  per_user_once: true,
  new_users_only: false,
  is_active: true,
};
type FormState = typeof EMPTY_FORM;

export default function AdminPromoPage() {
  const [codes, setCodes] = useState<PromoCode[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  // --- создание ---
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  // --- построчное редактирование ---
  const [edits, setEdits] = useState<Record<number, Partial<Editable>>>({});
  const [saving, setSaving] = useState<Record<number, boolean>>({});
  const [savedFlash, setSavedFlash] = useState<Record<number, boolean>>({});
  const [deleting, setDeleting] = useState<Record<number, boolean>>({});

  useEffect(() => {
    let alive = true;
    (async () => {
      const res = await fetchData<PromoCode[]>("manage/promo-codes/", "GET", null, true);
      if (!alive) return;
      if (res.ok && Array.isArray(res.data)) setCodes(res.data);
      else setError(res.error || "Не удалось загрузить промокоды");
      setLoading(false);
    })();
    return () => {
      alive = false;
    };
  }, []);

  const merged = useMemo(
    () => codes.map((c) => ({ ...c, ...(edits[c.id] || {}) })),
    [codes, edits]
  );

  const setField = <K extends keyof Editable>(id: number, key: K, value: Editable[K]) => {
    setEdits((prev) => {
      const base = codes.find((c) => c.id === id);
      const next = { ...(prev[id] || {}), [key]: value };
      if (base && base[key] === value) delete next[key];
      const out = { ...prev };
      if (Object.keys(next).length === 0) delete out[id];
      else out[id] = next;
      return out;
    });
  };

  // ---------- создание ----------
  const createCode = async () => {
    const code = form.code.trim();
    if (!code) {
      setCreateError("Введите код промокода");
      return;
    }
    const bonus = Number(form.bonus_credits);
    if (!Number.isFinite(bonus) || !Number.isInteger(bonus) || bonus < 0) {
      setCreateError("Бонус (кр) — целое число не меньше 0");
      return;
    }
    let maxAct: number | null = null;
    if (form.max_activations.trim() !== "") {
      const m = Number(form.max_activations);
      if (!Number.isFinite(m) || !Number.isInteger(m) || m < 1) {
        setCreateError("Лимит активаций — целое число от 1 (или пусто = без лимита)");
        return;
      }
      maxAct = m;
    }
    const payload = {
      code,
      bonus_credits: bonus,
      expires_at: localInputToIso(form.expires_at),
      max_activations: maxAct,
      per_user_once: form.per_user_once,
      new_users_only: form.new_users_only,
      is_active: form.is_active,
    };
    setCreating(true);
    setCreateError(null);
    const res = await fetchData<PromoCode>("manage/promo-codes/", "POST", payload, true);
    setCreating(false);
    if (res.ok && res.data) {
      setCodes((prev) => [res.data as PromoCode, ...prev]);
      setForm(EMPTY_FORM);
    } else {
      setCreateError(res.error || "Не удалось создать промокод");
    }
  };

  // ---------- сохранение строки ----------
  const save = async (id: number) => {
    const patch = edits[id];
    if (!patch || Object.keys(patch).length === 0) return;
    setSaving((s) => ({ ...s, [id]: true }));
    const res = await fetchData<PromoCode>(
      `manage/promo-codes/${id}/`,
      "PATCH",
      patch,
      true
    );
    setSaving((s) => ({ ...s, [id]: false }));
    if (res.ok && res.data) {
      const updated = res.data;
      setCodes((prev) => prev.map((c) => (c.id === id ? { ...c, ...updated } : c)));
      setEdits((prev) => {
        const out = { ...prev };
        delete out[id];
        return out;
      });
      setSavedFlash((f) => ({ ...f, [id]: true }));
      setTimeout(() => setSavedFlash((f) => ({ ...f, [id]: false })), 2000);
    } else {
      alert(`Не удалось сохранить: ${res.error || "ошибка сервера"}`);
    }
  };

  // ---------- удаление строки ----------
  const remove = async (id: number, code: string) => {
    if (!confirm(`Удалить промокод «${code}»? Действие необратимо.`)) return;
    setDeleting((d) => ({ ...d, [id]: true }));
    const res = await fetchData(`manage/promo-codes/${id}/`, "DELETE", null, true);
    setDeleting((d) => ({ ...d, [id]: false }));
    if (res.ok || res.status === 204) {
      setCodes((prev) => prev.filter((c) => c.id !== id));
      setEdits((prev) => {
        const out = { ...prev };
        delete out[id];
        return out;
      });
    } else {
      alert(`Не удалось удалить: ${res.error || "ошибка сервера"}`);
    }
  };

  if (loading) {
    return (
      <div className="space-y-4">
        <div className="h-8 w-40 animate-pulse rounded-lg bg-surface-2" />
        <div className="h-44 animate-pulse rounded-2xl bg-surface-2" />
        <div className="h-64 animate-pulse rounded-2xl bg-surface-2" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-2xl border border-border bg-surface p-6 text-sm text-red-400">
        Ошибка загрузки: {error}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Промокоды</h1>
        <p className="mt-1 text-sm text-muted">
          Коды на бонусные кредиты. Управляйте сроком действия, лимитом активаций и условиями
          применения.
        </p>
      </div>

      {/* Форма создания */}
      <section className="rounded-2xl border border-border bg-surface p-5">
        <div className="flex items-center gap-2">
          <FiPlus className="h-4 w-4 text-accent" />
          <h2 className="text-base font-semibold">Новый промокод</h2>
        </div>

        <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <div className="flex flex-col gap-1">
            <label className="text-xs text-muted">Код</label>
            <input
              type="text"
              value={form.code}
              onChange={(e) => setForm((f) => ({ ...f, code: e.target.value }))}
              placeholder="WELCOME100"
              className={`${INPUT} font-mono uppercase`}
            />
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs text-muted">Бонус (кр)</label>
            <input
              type="number"
              min={0}
              step={1}
              value={form.bonus_credits}
              onChange={(e) => setForm((f) => ({ ...f, bonus_credits: e.target.value }))}
              className={INPUT}
            />
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs text-muted">Срок действия</label>
            <input
              type="datetime-local"
              value={form.expires_at}
              onChange={(e) => setForm((f) => ({ ...f, expires_at: e.target.value }))}
              className={INPUT}
            />
            <span className="text-xs text-muted-2">пусто = бессрочно</span>
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs text-muted">Лимит активаций</label>
            <input
              type="number"
              min={1}
              step={1}
              value={form.max_activations}
              onChange={(e) => setForm((f) => ({ ...f, max_activations: e.target.value }))}
              placeholder="без лимита"
              className={INPUT}
            />
            <span className="text-xs text-muted-2">пусто = без лимита</span>
          </div>
          <div className="flex flex-col justify-center gap-2 sm:col-span-2 lg:col-span-2">
            <label className="inline-flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                className="h-4 w-4 accent-accent"
                checked={form.per_user_once}
                onChange={(e) => setForm((f) => ({ ...f, per_user_once: e.target.checked }))}
              />
              Один раз на пользователя
            </label>
            <label className="inline-flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                className="h-4 w-4 accent-accent"
                checked={form.new_users_only}
                onChange={(e) => setForm((f) => ({ ...f, new_users_only: e.target.checked }))}
              />
              Только для новых пользователей
            </label>
            <label className="inline-flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                className="h-4 w-4 accent-accent"
                checked={form.is_active}
                onChange={(e) => setForm((f) => ({ ...f, is_active: e.target.checked }))}
              />
              Активен
            </label>
          </div>
        </div>

        <div className="mt-4 flex items-center gap-3">
          <button
            onClick={createCode}
            disabled={creating}
            className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-4 py-2 text-xs font-semibold text-on-accent transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            <FiPlus className="h-4 w-4" />
            {creating ? "Создание…" : "Создать промокод"}
          </button>
          {createError && <span className="text-sm text-red-400">{createError}</span>}
        </div>
      </section>

      {/* Таблица промокодов */}
      <section className="rounded-2xl border border-border bg-surface p-5">
        <div className="flex items-center gap-2">
          <FiTag className="h-4 w-4 text-accent" />
          <h2 className="text-base font-semibold">Все промокоды</h2>
          <span className="text-xs text-muted-2">({codes.length})</span>
        </div>

        {merged.length === 0 ? (
          <p className="mt-4 text-sm text-muted-2">Промокодов пока нет.</p>
        ) : (
          <div className="mt-4 overflow-x-auto">
            <table className="w-full min-w-[900px] text-sm">
              <thead>
                <tr className="border-b border-border text-left text-xs text-muted">
                  <th className="py-2 pr-3 font-medium">Код</th>
                  <th className="py-2 pr-3 font-medium">Бонус (кр)</th>
                  <th className="py-2 pr-3 font-medium">Срок</th>
                  <th className="py-2 pr-3 font-medium">Активаций</th>
                  <th className="py-2 pr-3 font-medium">1×/юзер</th>
                  <th className="py-2 pr-3 font-medium">Новым</th>
                  <th className="py-2 pr-3 font-medium">Активен</th>
                  <th className="py-2 pr-3 font-medium" />
                </tr>
              </thead>
              <tbody>
                {merged.map((c) => {
                  const dirty = Boolean(edits[c.id]);
                  return (
                    <tr key={c.id} className="border-b border-border/60 align-middle">
                      <td className="py-2.5 pr-3">
                        <span className="font-mono font-semibold">{c.code}</span>
                      </td>
                      <td className="py-2.5 pr-3">
                        <input
                          type="number"
                          min={0}
                          step={1}
                          value={c.bonus_credits}
                          onChange={(e) =>
                            setField(c.id, "bonus_credits", Number(e.target.value))
                          }
                          className={`${INPUT} w-24`}
                        />
                      </td>
                      <td className="py-2.5 pr-3">
                        <input
                          type="datetime-local"
                          value={isoToLocalInput(c.expires_at)}
                          onChange={(e) =>
                            setField(c.id, "expires_at", localInputToIso(e.target.value))
                          }
                          className={`${INPUT} w-52`}
                        />
                        <div className="mt-0.5 text-xs text-muted-2">
                          {fmtExpires(c.expires_at)}
                        </div>
                      </td>
                      <td className="py-2.5 pr-3">
                        <div className="flex items-center gap-1.5">
                          <input
                            type="number"
                            min={1}
                            step={1}
                            value={c.max_activations ?? ""}
                            placeholder="∞"
                            onChange={(e) => {
                              const v = e.target.value.trim();
                              setField(
                                c.id,
                                "max_activations",
                                v === "" ? null : Number(v)
                              );
                            }}
                            className={`${INPUT} w-20`}
                          />
                          <span className="whitespace-nowrap text-xs text-muted-2">
                            исп. {c.used_count}
                          </span>
                        </div>
                      </td>
                      <td className="py-2.5 pr-3 text-center">
                        <input
                          type="checkbox"
                          className="h-4 w-4 accent-accent"
                          checked={c.per_user_once}
                          onChange={(e) =>
                            setField(c.id, "per_user_once", e.target.checked)
                          }
                        />
                      </td>
                      <td className="py-2.5 pr-3 text-center">
                        <input
                          type="checkbox"
                          className="h-4 w-4 accent-accent"
                          checked={c.new_users_only}
                          onChange={(e) =>
                            setField(c.id, "new_users_only", e.target.checked)
                          }
                        />
                      </td>
                      <td className="py-2.5 pr-3 text-center">
                        <input
                          type="checkbox"
                          className="h-4 w-4 accent-accent"
                          checked={c.is_active}
                          onChange={(e) => setField(c.id, "is_active", e.target.checked)}
                        />
                      </td>
                      <td className="py-2.5 pr-3">
                        <div className="flex items-center justify-end gap-2">
                          {savedFlash[c.id] ? (
                            <span className="inline-flex items-center gap-1 text-xs font-medium text-emerald-400">
                              <FiCheck className="h-4 w-4" /> Сохранено
                            </span>
                          ) : dirty ? (
                            <button
                              onClick={() => save(c.id)}
                              disabled={Boolean(saving[c.id])}
                              className="rounded-lg bg-accent px-3 py-1.5 text-xs font-semibold text-on-accent transition-opacity hover:opacity-90 disabled:opacity-50"
                            >
                              {saving[c.id] ? "Сохранение…" : "Сохранить"}
                            </button>
                          ) : null}
                          <button
                            onClick={() => remove(c.id, c.code)}
                            disabled={Boolean(deleting[c.id])}
                            title="Удалить"
                            className="rounded-lg border border-border bg-surface-2 p-1.5 text-muted transition-colors hover:text-red-400 disabled:opacity-50"
                          >
                            <FiTrash2 className="h-4 w-4" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
