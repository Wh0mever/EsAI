"use client";

/**
 * Вкладки «Видео / Картинка». Стоят в панели параметров и в шторке; оболочка
 * (FE-1) может поставить их и в верхнюю строку ленты (§9.2), передав
 * showKindTabs={false} панели.
 *
 * Вид без моделей не прячется, а выключается с подписью «скоро» — чтобы было
 * видно, почему нельзя.
 */
import { useTranslation } from "react-i18next";
import { FiImage, FiVideo } from "react-icons/fi";
import type { VsKind } from "@/lib/vstudio/types";
import { cx } from "./SettingsBits";
import { tx } from "./settingsText";

export type KindTabsProps = {
  value: VsKind;
  onChange: (kind: VsKind) => void;
  /** Сколько моделей у вида; 0 — вкладка выключена с подписью «скоро». undefined — не знаем (грузятся). */
  counts?: Partial<Record<VsKind, number>>;
  disabled?: boolean;
  className?: string;
};

const KINDS: { kind: VsKind; icon: typeof FiVideo; key: "kind.video" | "kind.image" }[] = [
  { kind: "video", icon: FiVideo, key: "kind.video" },
  { kind: "image", icon: FiImage, key: "kind.image" },
];

export default function KindTabs({ value, onChange, counts, disabled, className }: KindTabsProps) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  return (
    <div
      role="group"
      aria-label={tx(t, "kind.label")}
      className={cx("grid grid-cols-2 gap-1 rounded-xl border border-border bg-surface-2 p-1", className)}
    >
      {KINDS.map(({ kind, icon: Icon, key }) => {
        const empty = counts?.[kind] === 0;
        const active = value === kind;
        const off = disabled || empty;
        return (
          <button
            key={kind}
            type="button"
            aria-pressed={active}
            disabled={off}
            onClick={() => !off && onChange(kind)}
            className={cx(
              "flex min-h-11 items-center justify-center gap-1.5 rounded-lg px-3 text-sm font-semibold transition-colors md:min-h-9",
              active ? "bg-surface text-foreground shadow-sm ring-1 ring-accent/60" : "text-muted hover:text-foreground",
              off ? "cursor-not-allowed opacity-50 hover:text-muted" : "cursor-pointer",
            )}
          >
            <Icon className={cx("size-4 shrink-0", active && "text-accent")} aria-hidden />
            <span>{tx(t, key)}</span>
            {empty && <span className="text-[10px] font-normal text-muted-2">· {tx(t, "kind.soon")}</span>}
          </button>
        );
      })}
    </div>
  );
}
