"use client";

import clsx from "clsx";
import { FiShuffle } from "react-icons/fi";
import type { InfluencerCategory } from "@/lib/creative/api";
import { errorText } from "@/lib/creative/errors";
import type { Ct } from "@/lib/creative/text";
import { useCatalog } from "./useCatalog";
import { BTN_GHOST, FOCUS, Skeleton } from "./ui";

/**
 * Виртуальный блогер: категории внешности чипами. В категории можно выбрать
 * не больше max; «исключающий» вариант (например, «без аксессуаров») стоит
 * один. Ничего не выбрано — сервер подберёт случайно (так и по умолчанию).
 * Подписи переводим по ключам (inf.cat.*, inf.opt.*); английская подпись
 * сервера — запасная, если ключа ещё нет.
 */
export type Selection = Record<string, string[]>;

export function toggleOption(sel: Selection, cat: InfluencerCategory, key: string): Selection {
  const cur = sel[cat.key] || [];
  const opt = cat.options.find((o) => o.key === key);
  let next: string[];
  if (cur.includes(key)) next = cur.filter((k) => k !== key);
  else if (cat.max <= 1 || opt?.exclusive) next = [key];
  else {
    const base = cur.filter((k) => !cat.options.find((o) => o.key === k)?.exclusive);
    // Предел категории: самый ранний выбор уступает место новому.
    next = [...base, key].slice(-cat.max);
  }
  const out = { ...sel };
  if (next.length) out[cat.key] = next;
  else delete out[cat.key];
  return out;
}

export default function InfluencerPicker({
  value,
  onChange,
  disabled,
  guest,
  ct,
}: {
  value: Selection;
  onChange: (v: Selection) => void;
  disabled?: boolean;
  guest?: boolean;
  ct: Ct;
}) {
  const { data, error, loading, retry } = useCatalog<InfluencerCategory[]>("influencer", !guest);
  if (guest) return <p className="rounded-xl border border-dashed border-border px-4 py-3 text-sm text-muted">{ct("run.signin_hint")}</p>;
  if (loading) {
    return (
      <div className="space-y-3" aria-busy="true" aria-label={ct("run.catalog_loading")}>
        {Array.from({ length: 3 }, (_, i) => (
          <Skeleton key={i} className="h-16" />
        ))}
      </div>
    );
  }
  if (error || !data) {
    return (
      <div className="flex flex-wrap items-center gap-3 rounded-xl border border-border px-4 py-3 text-sm">
        <span role="alert" className="text-status-fail">
          {error ? errorText(ct, error) : ct("errors.catalog_unavailable")}
        </span>
        <button type="button" className={BTN_GHOST} onClick={retry}>
          {ct("run.catalog_retry")}
        </button>
      </div>
    );
  }
  const picked = Object.values(value).reduce((n, l) => n + l.length, 0);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="inline-flex items-center gap-1.5 rounded-lg bg-surface-2 px-2.5 py-1 text-muted" aria-live="polite">
          <FiShuffle aria-hidden="true" className="size-3.5" />
          {picked ? `${ct("run.selected")}: ${picked}` : ct("run.random")}
        </span>
        {picked > 0 && (
          <button type="button" className={clsx("text-sm font-medium text-[var(--accent-text)] underline-offset-2 hover:underline", FOCUS)} onClick={() => onChange({})} disabled={disabled}>
            {ct("run.reset_options")}
          </button>
        )}
      </div>
      {data.map((cat) => {
        const cur = value[cat.key] || [];
        const headId = `inf-${cat.key}`;
        return (
          <div key={cat.key} role="group" aria-labelledby={headId} className="space-y-2">
            <p id={headId} className="flex items-baseline justify-between gap-2 text-sm font-medium">
              <span>{ct(`inf.cat.${cat.key}`, { defaultValue: cat.label })}</span>
              {cat.max > 1 && <span className="text-xs font-normal text-muted">{ct("run.max_in_group", { max: cat.max })}</span>}
            </p>
            <div className="flex flex-wrap gap-2">
              {cat.options.map((o) => {
                const on = cur.includes(o.key);
                return (
                  <button
                    key={o.key}
                    type="button"
                    aria-pressed={on}
                    disabled={disabled}
                    onClick={() => onChange(toggleOption(value, cat, o.key))}
                    className={clsx(
                      "inline-flex min-h-9 items-center gap-2 rounded-full border py-1 pl-1.5 pr-3 text-sm transition-colors",
                      on ? "border-[#F5C518] bg-[#F5C518] font-medium text-black" : "border-border bg-background hover:border-[#F5C518]/60",
                      "disabled:cursor-not-allowed disabled:opacity-50",
                      FOCUS,
                    )}
                  >
                    {o.preview ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img src={o.preview} alt="" loading="lazy" className="size-6 rounded-full object-cover" />
                    ) : o.color ? (
                      <span aria-hidden="true" className="size-5 rounded-full border border-black/10" style={{ backgroundColor: o.color }} />
                    ) : (
                      <span aria-hidden="true" className="w-0.5" />
                    )}
                    {ct(`inf.opt.${cat.key}.${o.key}`, { defaultValue: o.label })}
                  </button>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}
