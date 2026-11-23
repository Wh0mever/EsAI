"use client";

import clsx from "clsx";
import { useMemo, useState } from "react";
import { FiCheck, FiSlash } from "react-icons/fi";
import type { CatalogItem, CatalogKind } from "@/lib/creative/api";
import { errorText } from "@/lib/creative/errors";
import type { Ct } from "@/lib/creative/text";
import { useCatalog } from "./useCatalog";
import { BTN_GHOST, FOCUS, INPUT, Skeleton, chip } from "./ui";

/**
 * Выбор стиля/пресета из каталога сервера: плитки с превью (наши адреса),
 * поиск и группы, когда вариантов много, «Показать ещё» по 24.
 * Необязательный каталог начинается плиткой «Без стиля» / «Без пресета».
 */
const PAGE = 24;

/** Ключ перевода группы пресетов из её названия: «Proof & Specs» → proof_and_specs. */
export function groupKey(name: string): string {
  return name
    .toLowerCase()
    .replace(/&/g, " and ")
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
}

export default function CatalogPicker({
  kind,
  value,
  onChange,
  required,
  disabled,
  guest,
  ct,
  labelId,
  noneLabel,
}: {
  kind: Exclude<CatalogKind, "influencer">;
  value: string;
  onChange: (id: string) => void;
  required?: boolean;
  disabled?: boolean;
  /** гостю каталог не отдают — показываем подсказку войти */
  guest?: boolean;
  ct: Ct;
  labelId: string;
  noneLabel: string;
}) {
  const { data, error, loading, retry } = useCatalog<CatalogItem[]>(kind, !guest);
  const [query, setQuery] = useState("");
  const [group, setGroup] = useState("");
  const [limit, setLimit] = useState(PAGE);

  const groups = useMemo(() => {
    const set = new Set<string>();
    for (const i of data || []) if (i.group) set.add(i.group);
    return [...set];
  }, [data]);

  // Подписи на языке человека: варианта без имени — «Стиль N», группы — по ключу (название сервера — запасное).
  const nameOf = (i: CatalogItem) => i.name || ct("run.style_n", { n: i.n || 1 });
  const groupLabel = (g: string) => {
    const k = groupKey(g);
    return k ? ct(`preset_group.${k}`, { defaultValue: g }) : g;
  };

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (data || []).filter(
      (i) => (!group || i.group === group) && (!q || (i.name || ct("run.style_n", { n: i.n || 1 })).toLowerCase().includes(q)),
    );
  }, [data, query, group, ct]);

  if (guest) return <p className="rounded-xl border border-dashed border-border px-4 py-3 text-sm text-muted">{ct("run.signin_hint")}</p>;

  if (loading) {
    return (
      <div className="grid grid-cols-3 gap-2 sm:grid-cols-4" aria-busy="true" aria-label={ct("run.catalog_loading")}>
        {Array.from({ length: 8 }, (_, i) => (
          <Skeleton key={i} className="aspect-square" />
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

  const selected = data.find((i) => i.id === value) || null;
  const shown = filtered.slice(0, limit);
  const many = data.length > PAGE;

  return (
    <div className="space-y-3">
      {(many || groups.length > 1) && (
        <div className="space-y-2">
          {many && (
            <input
              type="search"
              value={query}
              disabled={disabled}
              onChange={(e) => {
                setQuery(e.target.value);
                setLimit(PAGE);
              }}
              placeholder={ct("run.search_ph")}
              aria-label={ct("run.search")}
              className={INPUT}
            />
          )}
          {groups.length > 1 && (
            <div className="-mx-1 flex gap-2 overflow-x-auto px-1 pb-1 [scrollbar-width:none]">
              <button type="button" className={clsx(chip(!group), "shrink-0")} aria-pressed={!group} onClick={() => setGroup("")}>
                {ct("run.all_groups")}
              </button>
              {groups.map((g) => (
                <button
                  key={g}
                  type="button"
                  className={clsx(chip(group === g), "shrink-0")}
                  aria-pressed={group === g}
                  onClick={() => {
                    setGroup(g);
                    setLimit(PAGE);
                  }}
                >
                  {groupLabel(g)}
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {selected && !shown.some((i) => i.id === selected.id) && (
        <p className="text-xs text-muted">
          {ct("run.selected")}: <span className="font-semibold text-foreground">{nameOf(selected)}</span>
        </p>
      )}

      <div role="radiogroup" aria-labelledby={labelId} className="grid grid-cols-3 gap-2 sm:grid-cols-4">
        {!required && !query && !group && (
          <Tile on={!value} label={noneLabel} onPick={() => onChange("")} disabled={disabled}>
            <span className="grid size-full place-items-center bg-surface-2 text-muted">
              <FiSlash aria-hidden="true" className="size-6" />
            </span>
          </Tile>
        )}
        {shown.map((i) => (
          <Tile key={i.id} on={i.id === value} label={nameOf(i)} onPick={() => onChange(i.id)} disabled={disabled}>
            {i.preview ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={i.preview} alt="" loading="lazy" decoding="async" className="size-full object-cover" />
            ) : (
              <span className="grid size-full place-items-center bg-gradient-to-br from-surface-2 to-surface-3 px-2 text-center text-xs font-semibold text-muted">
                {nameOf(i)}
              </span>
            )}
          </Tile>
        ))}
      </div>
      {!filtered.length && <p className="text-sm text-muted">{ct("run.nothing_found")}</p>}
      {filtered.length > limit && (
        <button type="button" className={BTN_GHOST} onClick={() => setLimit((x) => x + PAGE)}>
          {ct("run.show_more")}
        </button>
      )}
    </div>
  );
}

function Tile({ on, label, onPick, disabled, children }: { on: boolean; label: string; onPick: () => void; disabled?: boolean; children: React.ReactNode }) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={on}
      disabled={disabled}
      onClick={onPick}
      className={clsx(
        "group relative flex flex-col overflow-hidden rounded-xl border-2 bg-background text-left transition",
        on ? "border-[#F5C518]" : "border-transparent hover:border-[#F5C518]/50",
        "disabled:cursor-not-allowed disabled:opacity-60",
        FOCUS,
      )}
    >
      <span className="relative block aspect-square w-full overflow-hidden">{children}</span>
      <span className="line-clamp-2 min-h-8 px-1.5 py-1 text-[11px] font-medium leading-tight sm:text-xs">{label}</span>
      {on && (
        <span aria-hidden="true" className="absolute right-1.5 top-1.5 grid size-6 place-items-center rounded-full bg-[#F5C518] text-black shadow">
          <FiCheck className="size-3.5" />
        </span>
      )}
    </button>
  );
}
