"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { FiChevronDown, FiCheck } from "react-icons/fi";
import { fetchData } from "@/tools/fetchData";

export type AiModel = {
  id: number | string;
  name: string;
  openrouter_id?: string;
  description?: string;
  sort_order?: number;
};

const LS_MODEL = "esai-model";

type Props = {
  value?: string; // currently selected model identifier (openrouter_id || id)
  onChange: (modelId: string, model: AiModel) => void;
  className?: string;
};

/**
 * ModelSelector — fetches the model list from GET /api/ai/models/ and lets the
 * user pick one. The selected identifier (openrouter_id, falling back to id) is
 * reported upward and persisted in localStorage.
 */
export default function ModelSelector({ value, onChange, className }: Props) {
  const { t } = useTranslation("common");
  const [models, setModels] = useState<AiModel[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const ref = useRef<HTMLDivElement | null>(null);

  const modelKey = (m: AiModel) => String(m.openrouter_id || m.id);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetchData<AiModel[]>("ai/models/", "GET", null, false);
        if (cancelled) return;
        const list = Array.isArray(res?.data) ? res.data : [];
        list.sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0));
        setModels(list);
        // initialise selection: stored -> first available
        if (list.length) {
          let stored = "";
          try { stored = localStorage.getItem(LS_MODEL) || ""; } catch {}
          const found = list.find((m) => modelKey(m) === stored);
          const chosen = found || list[0];
          if (!value) onChange(modelKey(chosen), chosen);
        }
      } catch {
        if (!cancelled) setModels([]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // close on outside click
  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  const select = (m: AiModel) => {
    const key = modelKey(m);
    try { localStorage.setItem(LS_MODEL, key); } catch {}
    onChange(key, m);
    setOpen(false);
  };

  const current = models.find((m) => modelKey(m) === value);
  const label = current?.name
    || (loading ? t("common.loading", { defaultValue: "Загрузка..." }) : t("chat.model.select", { defaultValue: "Выбрать модель" }));

  return (
    <div ref={ref} className={`relative ${className || ""}`}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        disabled={loading && models.length === 0}
        className="inline-flex items-center gap-1.5 rounded-full border border-border bg-surface-2 hover:border-accent/60 text-foreground text-sm px-3 py-1.5 transition-colors cursor-pointer disabled:opacity-60"
        title={t("chat.model.select", { defaultValue: "Выбрать модель" })}
      >
        <span className="w-2 h-2 rounded-full bg-accent shrink-0" />
        <span className="max-w-[10rem] truncate">{label}</span>
        <FiChevronDown className={`transition-transform ${open ? "rotate-180" : ""}`} />
      </button>

      {open && models.length > 0 && (
        <div className="absolute z-50 bottom-full mb-2 left-0 w-72 max-h-80 overflow-y-auto rounded-xl border border-border bg-surface shadow-2xl p-1.5">
          {models.map((m) => {
            const active = modelKey(m) === value;
            return (
              <button
                key={modelKey(m)}
                type="button"
                onClick={() => select(m)}
                className={`w-full text-left rounded-lg px-3 py-2 flex items-start gap-2 transition-colors cursor-pointer ${
                  active ? "bg-accent-soft" : "hover:bg-surface-2"
                }`}
              >
                <span className="mt-0.5 shrink-0 w-4">{active && <FiCheck className="text-accent" />}</span>
                <span className="min-w-0">
                  <span className="block text-sm font-medium text-foreground truncate">{m.name}</span>
                  {m.description && (
                    <span className="block text-xs text-muted truncate">{m.description}</span>
                  )}
                </span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
