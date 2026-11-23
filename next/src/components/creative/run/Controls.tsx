"use client";

import clsx from "clsx";
import { useId } from "react";
import { FOCUS, INPUT } from "./ui";

/**
 * Простые элементы формы: варианты-кнопки (настоящие radio — стрелки и Tab
 * работают как у обычной группы), выпадающий список, ползунок, переключатель.
 */
export function ChoiceChips<T extends string | number>({
  name,
  value,
  options,
  onChange,
  disabled,
  labelId,
}: {
  name: string;
  value: T;
  options: { value: T; label: string }[];
  onChange: (v: T) => void;
  disabled?: boolean;
  labelId: string;
}) {
  const group = useId();
  return (
    <div role="radiogroup" aria-labelledby={labelId} className="flex flex-wrap gap-2">
      {options.map((o) => {
        const on = o.value === value;
        return (
          <label
            key={String(o.value)}
            className={clsx(
              "relative inline-flex min-h-9 cursor-pointer items-center justify-center rounded-lg border px-3 text-sm font-medium transition-colors",
              "has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-[var(--accent-text)] has-[:focus-visible]:ring-offset-2 has-[:focus-visible]:ring-offset-background",
              on ? "border-[#F5C518] bg-[#F5C518] text-black" : "border-border bg-background text-foreground hover:border-[#F5C518]/60",
              disabled && "cursor-not-allowed opacity-50",
            )}
          >
            <input
              type="radio"
              className="sr-only"
              name={`${group}-${name}`}
              value={String(o.value)}
              checked={on}
              disabled={disabled}
              onChange={() => onChange(o.value)}
            />
            {o.label}
          </label>
        );
      })}
    </div>
  );
}

export function SelectBox({
  id,
  value,
  options,
  onChange,
  disabled,
  describedBy,
}: {
  id: string;
  value: string;
  options: { value: string; label: string }[];
  onChange: (v: string) => void;
  disabled?: boolean;
  describedBy?: string;
}) {
  return (
    <select
      id={id}
      value={value}
      disabled={disabled}
      aria-describedby={describedBy}
      onChange={(e) => onChange(e.target.value)}
      className={clsx(INPUT, "appearance-auto pr-8")}
    >
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  );
}

export function RangeBox({
  id,
  value,
  min,
  max,
  unit,
  onChange,
  disabled,
  describedBy,
}: {
  id: string;
  value: number;
  min: number;
  max: number;
  unit: string;
  onChange: (v: number) => void;
  disabled?: boolean;
  describedBy?: string;
}) {
  return (
    <div className="flex items-center gap-3">
      <input
        id={id}
        type="range"
        min={min}
        max={max}
        step={1}
        value={value}
        disabled={disabled}
        aria-describedby={describedBy}
        aria-valuetext={`${value} ${unit}`}
        onChange={(e) => onChange(Number(e.target.value))}
        className={clsx("h-2 flex-1 cursor-pointer accent-[#F5C518]", FOCUS)}
      />
      <output htmlFor={id} className="min-w-14 rounded-lg border border-border bg-background px-2 py-1 text-center text-sm font-semibold tabular-nums">
        {value} {unit}
      </output>
    </div>
  );
}

export function Toggle({
  id,
  checked,
  onChange,
  disabled,
  describedBy,
  labelledBy,
}: {
  id: string;
  checked: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
  describedBy?: string;
  labelledBy?: string;
}) {
  return (
    <button
      id={id}
      type="button"
      role="switch"
      aria-checked={checked}
      aria-describedby={describedBy}
      aria-labelledby={labelledBy}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={clsx(
        "relative inline-flex h-7 w-12 shrink-0 items-center rounded-full border transition-colors",
        checked ? "border-[#F5C518] bg-[#F5C518]" : "border-border-strong bg-surface-3",
        "disabled:cursor-not-allowed disabled:opacity-50",
        FOCUS,
      )}
    >
      <span
        aria-hidden="true"
        className={clsx(
          "inline-block size-5 rounded-full shadow transition-transform motion-reduce:transition-none",
          checked ? "translate-x-6 bg-black" : "translate-x-1 bg-white",
        )}
      />
    </button>
  );
}
