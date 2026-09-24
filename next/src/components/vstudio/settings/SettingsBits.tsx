"use client";

/**
 * Мелкие кирпичи правой панели: заголовок раздела, кнопка-значение с ценой
 * под ней, строка причины. Один вид для всех пикеров, чтобы панель читалась
 * как одна вещь.
 *
 * Акцент (--accent) — только у выбранного значения (§9.2: «активные чипы»).
 * Причина выключенного значения — видимым текстом, а не только tooltip (§9.8).
 */
import { useId, type ReactNode } from "react";

export function cx(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}

export function Section({
  title,
  icon,
  aside,
  children,
  id,
}: {
  title: string;
  icon?: ReactNode;
  aside?: ReactNode;
  children: ReactNode;
  id?: string;
}) {
  // Заголовок подписывает раздел: скринридер читает «Длительность, 5 с, нажата».
  const autoId = useId();
  const titleId = id || autoId;
  return (
    <section className="flex flex-col gap-2" aria-labelledby={titleId}>
      <div className="flex items-center gap-1.5">
        {icon && <span className="text-muted-2 [&>svg]:size-3.5">{icon}</span>}
        <h3 id={titleId} className="text-[11px] font-semibold uppercase tracking-wide text-muted">
          {title}
        </h3>
        {aside && <div className="ml-auto flex items-center">{aside}</div>}
      </div>
      {children}
    </section>
  );
}

export function OptionButton({
  active,
  disabled,
  onClick,
  label,
  sub,
  icon,
  title,
  ariaLabel,
  className,
}: {
  active: boolean;
  disabled?: boolean;
  onClick?: () => void;
  label: ReactNode;
  /** Строка под значением — цена-подсказка («82 кр»). */
  sub?: ReactNode;
  icon?: ReactNode;
  title?: string;
  ariaLabel?: string;
  className?: string;
}) {
  return (
    <button
      type="button"
      onClick={disabled ? undefined : onClick}
      disabled={disabled}
      aria-pressed={active}
      aria-label={ariaLabel}
      title={title}
      className={cx(
        "flex min-h-11 min-w-0 flex-col items-center justify-center gap-0.5 rounded-xl border px-2 py-1.5 text-xs font-semibold transition-colors md:min-h-10",
        active
          ? "border-accent bg-accent-soft text-foreground"
          : "border-border bg-surface-2 text-muted hover:border-border-strong hover:text-foreground",
        disabled ? "cursor-not-allowed opacity-45 hover:border-border hover:text-muted" : "cursor-pointer active:scale-[0.97]",
        className,
      )}
    >
      {icon && <span className="flex items-center justify-center">{icon}</span>}
      <span className="leading-tight">{label}</span>
      {sub != null && sub !== "" && (
        <span className={cx("text-[10px] font-normal leading-tight", active ? "text-muted" : "text-muted-2")}>{sub}</span>
      )}
    </button>
  );
}

/** Видимая причина: почему значение выключено или что будет на самом деле. */
export function Reason({ children, tone = "warn", id }: { children: ReactNode; tone?: "warn" | "muted" | "error"; id?: string }) {
  return (
    <p
      id={id}
      className={cx(
        "text-[11px] leading-snug",
        tone === "warn" && "text-status-wait",
        tone === "error" && "text-status-fail",
        tone === "muted" && "text-muted-2",
      )}
    >
      {children}
    </p>
  );
}

/** Маленький бейдж возможности модели. */
export function Pill({ children, tone = "plain" }: { children: ReactNode; tone?: "plain" | "accent" | "warn" }) {
  return (
    <span
      className={cx(
        "inline-flex items-center gap-1 whitespace-nowrap rounded-full border px-1.5 py-px text-[10px] font-medium leading-4",
        tone === "plain" && "border-border bg-surface text-muted",
        tone === "accent" && "border-accent/40 bg-accent-soft text-foreground",
        tone === "warn" && "border-status-wait/40 text-status-wait",
      )}
    >
      {children}
    </span>
  );
}
