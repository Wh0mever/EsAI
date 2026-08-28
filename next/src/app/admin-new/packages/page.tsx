"use client";

import { useEffect, useMemo, useState } from "react";
import { fetchData } from "@/tools/fetchData";
import { FiCheck } from "react-icons/fi";

type Pkg = {
  id: number;
  name: string;
  tokens: number;
  bonus_tokens: number;
  price: number;
  badge: string;
  featured: boolean;
  is_active: boolean;
  sort_order: number;
  description: string;
  name_en: string;
  name_kg: string;
  badge_en: string;
  badge_kg: string;
  description_en: string;
  description_kg: string;
};

type Editable = Pick<
  Pkg,
  | "tokens"
  | "price"
  | "badge"
  | "featured"
  | "is_active"
  | "name_en"
  | "name_kg"
  | "badge_en"
  | "badge_kg"
  | "description_en"
  | "description_kg"
>;

/** Что переводится в пакете: русский текст рядом, чтобы было с чего переводить. */
const TRANSLATABLE: { label: string; source: keyof Pkg; en: keyof Editable; kg: keyof Editable }[] = [
  { label: "Название", source: "name", en: "name_en", kg: "name_kg" },
  { label: "Бейдж", source: "badge", en: "badge_en", kg: "badge_kg" },
  { label: "Подпись", source: "description", en: "description_en", kg: "description_kg" },
];

const INPUT =
  "rounded-lg bg-surface-2 border border-border px-3 py-2 text-sm text-foreground focus:border-accent outline-none";

export default function AdminPackagesPage() {
  const [packages, setPackages] = useState<Pkg[]>([]);
  const [edits, setEdits] = useState<Record<number, Partial<Editable>>>({});
  const [saving, setSaving] = useState<Record<number, boolean>>({});
  const [savedFlash, setSavedFlash] = useState<Record<number, boolean>>({});
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    (async () => {
      const res = await fetchData<Pkg[]>("manage/packages/", "GET", null, true);
      if (!alive) return;
      if (res.ok && Array.isArray(res.data)) setPackages(res.data);
      else setError(res.error || "Не удалось загрузить пакеты");
      setLoading(false);
    })();
    return () => {
      alive = false;
    };
  }, []);

  const merged = useMemo(
    () => packages.map((p) => ({ ...p, ...(edits[p.id] || {}) })),
    [packages, edits]
  );

  const setField = <K extends keyof Editable>(id: number, key: K, value: Editable[K]) => {
    setEdits((prev) => {
      const base = packages.find((p) => p.id === id);
      const next = { ...(prev[id] || {}), [key]: value };
      if (base && base[key] === value) delete next[key];
      const out = { ...prev };
      if (Object.keys(next).length === 0) delete out[id];
      else out[id] = next;
      return out;
    });
  };

  const save = async (id: number) => {
    const patch = edits[id];
    if (!patch || Object.keys(patch).length === 0) return;
    setSaving((s) => ({ ...s, [id]: true }));
    const res = await fetchData<Pkg>(`manage/packages/${id}/`, "PATCH", patch, true);
    setSaving((s) => ({ ...s, [id]: false }));
    if (res.ok && res.data) {
      const updated = res.data;
      setPackages((prev) => prev.map((p) => (p.id === id ? { ...p, ...updated } : p)));
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

  if (loading) {
    return (
      <div className="space-y-4">
        <div className="h-8 w-40 animate-pulse rounded-lg bg-surface-2" />
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-64 animate-pulse rounded-2xl bg-surface-2" />
          ))}
        </div>
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
        <h1 className="text-2xl font-semibold">Пакеты кредитов</h1>
        <p className="mt-1 text-sm text-muted">
          Цены и наполнение пакетов, которые видят пользователи на странице пополнения.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {merged.map((p) => {
          const dirty = Boolean(edits[p.id]);
          return (
            <div
              key={p.id}
              className={`rounded-2xl border border-border bg-surface p-5 ${
                p.is_active ? "" : "opacity-60"
              }`}
            >
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="text-base font-semibold">{p.name}</div>
                  {p.bonus_tokens > 0 && (
                    <div className="mt-0.5 text-xs text-muted-2">
                      + бонус: {p.bonus_tokens.toLocaleString("ru-RU")} кр
                    </div>
                  )}
                </div>
                {p.featured && (
                  <span className="rounded-full bg-accent-soft px-2.5 py-1 text-xs font-medium text-accent">
                    Featured
                  </span>
                )}
              </div>

              <div className="mt-4 space-y-3">
                <label className="block">
                  <span className="mb-1 block text-xs text-muted">Кредиты</span>
                  <input
                    type="number"
                    min={0}
                    className={`${INPUT} w-full`}
                    value={p.tokens}
                    onChange={(e) => setField(p.id, "tokens", Number(e.target.value))}
                  />
                </label>
                <label className="block">
                  <span className="mb-1 block text-xs text-muted">Цена, сом</span>
                  <input
                    type="number"
                    min={0}
                    className={`${INPUT} w-full`}
                    value={p.price}
                    onChange={(e) => setField(p.id, "price", Number(e.target.value))}
                  />
                </label>
                <label className="block">
                  <span className="mb-1 block text-xs text-muted">
                    Бейдж (например «Хит»)
                  </span>
                  <input
                    type="text"
                    className={`${INPUT} w-full`}
                    value={p.badge}
                    onChange={(e) => setField(p.id, "badge", e.target.value)}
                  />
                </label>
                <div className="flex items-center gap-5 pt-1">
                  <label className="inline-flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      className="h-4 w-4 accent-accent"
                      checked={p.featured}
                      onChange={(e) => setField(p.id, "featured", e.target.checked)}
                    />
                    Выделенный
                  </label>
                  <label className="inline-flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      className="h-4 w-4 accent-accent"
                      checked={p.is_active}
                      onChange={(e) => setField(p.id, "is_active", e.target.checked)}
                    />
                    Активен
                  </label>
                </div>
              </div>

              {/* Переводы витрины. Свёрнуты: заходят сюда обычно за ценой и
                  наполнением, а переводы правят редко. */}
              <details className="mt-4 rounded-xl border border-border bg-surface-2/50 p-3">
                <summary className="cursor-pointer text-sm font-medium text-muted hover:text-foreground">
                  Переводы витрины (EN / KG)
                </summary>
                <p className="mt-2 text-xs text-muted-2">
                  Пусто — на английской и кыргызской странице покажется русский текст.
                </p>
                <div className="mt-3 space-y-3">
                  {TRANSLATABLE.map((f) => (
                    <div key={f.en} className="space-y-1.5">
                      <div className="text-xs text-muted">
                        {f.label}
                        <span className="ml-1.5 text-muted-2">
                          — {String(p[f.source] || "").trim() || "пусто"}
                        </span>
                      </div>
                      <input
                        type="text"
                        placeholder="EN"
                        className={`${INPUT} w-full`}
                        value={String(p[f.en] ?? "")}
                        onChange={(e) => setField(p.id, f.en, e.target.value)}
                      />
                      <input
                        type="text"
                        placeholder="KG"
                        className={`${INPUT} w-full`}
                        value={String(p[f.kg] ?? "")}
                        onChange={(e) => setField(p.id, f.kg, e.target.value)}
                      />
                    </div>
                  ))}
                </div>
              </details>

              <div className="mt-5 flex h-9 items-center">
                {savedFlash[p.id] ? (
                  <span className="inline-flex items-center gap-1 text-sm font-medium text-emerald-400">
                    <FiCheck className="h-4 w-4" /> Сохранено
                  </span>
                ) : dirty ? (
                  <button
                    onClick={() => save(p.id)}
                    disabled={Boolean(saving[p.id])}
                    className="rounded-xl bg-accent px-4 py-2 text-sm font-semibold text-on-accent transition-opacity hover:opacity-90 disabled:opacity-50"
                  >
                    {saving[p.id] ? "Сохранение…" : "Сохранить"}
                  </button>
                ) : (
                  <span className="text-xs text-muted-2">Без изменений</span>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
