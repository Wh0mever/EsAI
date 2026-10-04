import type { ReactNode } from "react";

/**
 * Кабинет креатора: общие классы и мелкие блоки разделов.
 *
 * Только токены темы (bg-surface, text-muted…): кабинет открывают и в светлой,
 * и в тёмной теме.
 */

export const CARD = "rounded-2xl border border-border bg-surface p-4 sm:p-6";

export const INPUT =
  "w-full min-w-0 rounded-xl border border-border bg-surface-2 px-3 py-2.5 text-sm text-foreground placeholder:text-muted-2 transition-colors focus:border-accent focus:outline-none disabled:opacity-60";

export const BTN_PRIMARY =
  "inline-flex shrink-0 cursor-pointer items-center justify-center gap-1.5 rounded-xl bg-accent px-4 py-2.5 text-sm font-semibold text-on-accent transition-colors hover:bg-accent-strong disabled:cursor-default disabled:opacity-60";

export const BTN_GHOST =
  "inline-flex shrink-0 cursor-pointer items-center justify-center gap-1.5 rounded-xl border border-border bg-surface px-4 py-2.5 text-sm font-semibold text-foreground transition-colors hover:border-accent disabled:cursor-default disabled:opacity-60";

/** Верхний отступ страницы: только чтобы выйти из-под закреплённой шапки (64 px на телефоне). */
export const PAGE =
  "mx-auto min-h-[80dvh] w-full max-w-4xl px-4 pb-16 pt-[calc(4.5rem_+_env(safe-area-inset-top,0px))] lg:pt-24";

/** Каркас кабинета, пока грузятся данные или переводы. Высоты — как у блоков первого экрана. */
export function DashboardSkeleton() {
  return (
    <main className={PAGE} aria-busy="true">
      <div className="flex flex-col gap-1.5">
        <div className="h-[30px] animate-pulse rounded-xl bg-surface-2" />
        <div className="h-[122px] animate-pulse rounded-2xl bg-surface-2" />
        <div className="grid grid-cols-2 gap-1.5">
          <div className="h-[52px] animate-pulse rounded-xl bg-surface-2" />
          <div className="h-[52px] animate-pulse rounded-xl bg-surface-2" />
        </div>
        <div className="grid grid-cols-3 gap-1.5">
          <div className="h-16 animate-pulse rounded-xl bg-surface-2" />
          <div className="h-16 animate-pulse rounded-xl bg-surface-2" />
          <div className="h-16 animate-pulse rounded-xl bg-surface-2" />
        </div>
        <div className="h-[86px] animate-pulse rounded-2xl bg-surface-2" />
      </div>
    </main>
  );
}

/** Каркас списка раздела: несколько строк-заглушек. */
export function ListSkeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div className="flex flex-col gap-2" aria-busy="true">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="h-16 animate-pulse rounded-2xl bg-surface-2" />
      ))}
    </div>
  );
}

/** Пустой раздел: спокойный текст в пунктирной рамке. */
export function Empty({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-2xl border border-dashed border-border px-4 py-8 text-center text-sm text-muted">
      {children}
    </div>
  );
}

/** Текст под полем или формой: ошибка, успех или пояснение. */
export function Note({
  tone,
  children,
  size = "xs",
  className = "",
}: {
  tone: "ok" | "fail" | "wait" | "muted";
  children: ReactNode;
  size?: "xs" | "sm";
  className?: string;
}) {
  const color =
    tone === "ok"
      ? "text-status-ok"
      : tone === "fail"
        ? "text-status-fail"
        : tone === "wait"
          ? "text-status-wait"
          : "text-muted";
  return (
    <p role={tone === "fail" ? "alert" : undefined} className={`break-words ${size === "sm" ? "text-sm" : "text-xs"} ${color} ${className}`}>
      {children}
    </p>
  );
}

/** Строка «подпись — значение» в карточке списка на телефоне. */
export function Pair({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="shrink-0 text-xs text-muted">{label}</dt>
      <dd className="min-w-0 break-words text-right text-sm text-foreground">{children}</dd>
    </div>
  );
}
