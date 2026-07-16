"use client";

import { useEffect, useMemo, useState } from "react";
import { fetchData } from "@/tools/fetchData";
import { FiCheck } from "react-icons/fi";

type Model = {
  id: number;
  name: string;
  openrouter_id: string;
  description: string;
  markup_coefficient: number;
  category: string;
  recommended: boolean;
  free_tier: boolean;
  supports_vision: boolean;
  is_active: boolean;
  sort_order: number;
  cartoon_stage?: string;
};

type Editable = Pick<
  Model,
  "markup_coefficient" | "category" | "recommended" | "free_tier" | "is_active"
> & { cartoon_stage: string };

const CATEGORIES: { value: string; label: string }[] = [
  { value: "chat", label: "Для общения" },
  { value: "writing", label: "Тексты и SEO" },
  { value: "coding", label: "Программирование" },
  { value: "reasoning", label: "Анализ" },
  { value: "search", label: "Поиск" },
  { value: "image", label: "Изображения" },
  { value: "fast", label: "Быстрые" },
  { value: "budget", label: "Экономичные" },
];

const CARTOON_STAGES: { value: string; label: string }[] = [
  { value: "", label: "—" },
  { value: "script", label: "Сценарий" },
  { value: "image", label: "Изображения" },
  { value: "video", label: "Видео" },
];

const INPUT =
  "rounded-lg bg-surface-2 border border-border px-3 py-2 text-sm text-foreground focus:border-accent outline-none";

export default function AdminModelsPage() {
  const [models, setModels] = useState<Model[]>([]);
  const [edits, setEdits] = useState<Record<number, Partial<Editable>>>({});
  const [saving, setSaving] = useState<Record<number, boolean>>({});
  const [savedFlash, setSavedFlash] = useState<Record<number, boolean>>({});
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    (async () => {
      const res = await fetchData<Model[]>("manage/models/", "GET", null, true);
      if (!alive) return;
      if (res.ok && Array.isArray(res.data)) setModels(res.data);
      else setError(res.error || "Не удалось загрузить модели");
      setLoading(false);
    })();
    return () => {
      alive = false;
    };
  }, []);

  // По умолчанию показываем ТОЛЬКО активные: в БД ~100 легаси-моделей из старого
  // импорта — клиенту они не нужны и превращают таблицу в свалку.
  const [showInactive, setShowInactive] = useState(false);

  const merged = useMemo(
    () =>
      models
        .filter((m) => showInactive || m.is_active || Boolean(edits[m.id]))
        .map((m) => ({ ...m, ...(edits[m.id] || {}) })),
    [models, edits, showInactive]
  );
  const inactiveCount = useMemo(() => models.filter((m) => !m.is_active).length, [models]);

  const setField = <K extends keyof Editable>(id: number, key: K, value: Editable[K]) => {
    setEdits((prev) => {
      const base = models.find((m) => m.id === id);
      const next = { ...(prev[id] || {}), [key]: value };
      // Если значение вернулось к исходному — убираем из правок.
      // cartoon_stage может отсутствовать в модели (undefined) — считаем его "".
      const orig = key === "cartoon_stage" ? (base?.cartoon_stage ?? "") : base?.[key];
      if (base && orig === value) delete next[key];
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
    const res = await fetchData<Model>(`manage/models/${id}/`, "PATCH", patch, true);
    setSaving((s) => ({ ...s, [id]: false }));
    if (res.ok && res.data) {
      const updated = res.data;
      setModels((prev) => prev.map((m) => (m.id === id ? { ...m, ...updated } : m)));
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
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Модели</h1>
          <p className="mt-1 text-sm text-muted">
            Тарифы, категории и доступность моделей. Изменили строку — нажмите «Сохранить».
          </p>
        </div>
        {inactiveCount > 0 && (
          <label className="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-border bg-surface-2 px-3 py-2 text-sm text-muted hover:text-foreground">
            <input
              type="checkbox"
              checked={showInactive}
              onChange={(e) => setShowInactive(e.target.checked)}
              className="accent-[#F5C518]"
            />
            Показать выключенные ({inactiveCount})
          </label>
        )}
      </div>

      <div className="overflow-x-auto rounded-2xl border border-border bg-surface">
        <table className="w-full min-w-[900px] text-sm">
          <thead>
            <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted-2">
              <th className="px-4 py-3 font-medium">Название</th>
              <th className="px-4 py-3 font-medium">Тариф (кр/1000)</th>
              <th className="px-4 py-3 font-medium">Категория</th>
              <th className="px-4 py-3 font-medium">Студия</th>
              <th className="px-4 py-3 text-center font-medium">⭐ Реком.</th>
              <th className="px-4 py-3 text-center font-medium">Бесплатная</th>
              <th className="px-4 py-3 text-center font-medium">Активна</th>
              <th className="px-4 py-3 font-medium"></th>
            </tr>
          </thead>
          <tbody>
            {merged.map((m) => {
              const dirty = Boolean(edits[m.id]);
              return (
                <tr
                  key={m.id}
                  className={`border-b border-border last:border-0 hover:bg-surface-2 ${
                    m.is_active ? "" : "opacity-50"
                  }`}
                >
                  <td className="px-4 py-3">
                    <div className="font-medium">{m.name}</div>
                    <div className="mt-0.5 font-mono text-xs text-muted-2">
                      {m.openrouter_id}
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <input
                      type="number"
                      min={0}
                      step="any"
                      className={`${INPUT} w-24`}
                      value={m.markup_coefficient}
                      onChange={(e) =>
                        setField(m.id, "markup_coefficient", Number(e.target.value))
                      }
                    />
                  </td>
                  <td className="px-4 py-3">
                    <select
                      className={`${INPUT} w-44`}
                      value={m.category}
                      onChange={(e) => setField(m.id, "category", e.target.value)}
                    >
                      {CATEGORIES.map((c) => (
                        <option key={c.value} value={c.value}>
                          {c.label}
                        </option>
                      ))}
                      {!CATEGORIES.some((c) => c.value === m.category) && (
                        <option value={m.category}>{m.category}</option>
                      )}
                    </select>
                  </td>
                  <td className="px-4 py-3">
                    <select
                      className={`${INPUT} w-40`}
                      value={m.cartoon_stage ?? ""}
                      onChange={(e) => setField(m.id, "cartoon_stage", e.target.value)}
                    >
                      {CARTOON_STAGES.map((s) => (
                        <option key={s.value} value={s.value}>
                          {s.label}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className="px-4 py-3 text-center">
                    <input
                      type="checkbox"
                      className="h-4 w-4 accent-accent"
                      checked={m.recommended}
                      onChange={(e) => setField(m.id, "recommended", e.target.checked)}
                    />
                  </td>
                  <td className="px-4 py-3 text-center">
                    <input
                      type="checkbox"
                      className="h-4 w-4 accent-accent"
                      checked={m.free_tier}
                      onChange={(e) => setField(m.id, "free_tier", e.target.checked)}
                    />
                  </td>
                  <td className="px-4 py-3 text-center">
                    <input
                      type="checkbox"
                      className="h-4 w-4 accent-accent"
                      checked={m.is_active}
                      onChange={(e) => setField(m.id, "is_active", e.target.checked)}
                    />
                  </td>
                  <td className="px-4 py-3 text-right">
                    {savedFlash[m.id] ? (
                      <span className="inline-flex items-center gap-1 text-xs font-medium text-emerald-400">
                        <FiCheck className="h-4 w-4" /> Сохранено
                      </span>
                    ) : dirty ? (
                      <button
                        onClick={() => save(m.id)}
                        disabled={Boolean(saving[m.id])}
                        className="rounded-lg bg-accent px-3 py-1.5 text-xs font-semibold text-on-accent transition-opacity hover:opacity-90 disabled:opacity-50"
                      >
                        {saving[m.id] ? "Сохранение…" : "Сохранить"}
                      </button>
                    ) : null}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
