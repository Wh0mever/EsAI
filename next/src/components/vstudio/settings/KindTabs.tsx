"use client";

/**
 * Переключатель «Видео / Картинка». Стоит в панели параметров и в шторке;
 * оболочка может поставить его и в другое место, передав панели
 * showKindTabs={false}.
 *
 * Вид без моделей не прячется, а выключается с подписью «скоро» — чтобы было
 * видно, почему нельзя.
 */
import { useTranslation } from "react-i18next";
import { FiImage, FiVideo } from "react-icons/fi";
import type { VsKind } from "@/lib/vstudio/types";
import { VS_FOCUS } from "../ui/skin";
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

const KINDS: { kind: VsKind; icon: typeof FiVideo; key: "kind.video" | "kind.image"; col: string }[] = [
  { kind: "video", icon: FiVideo, key: "kind.video", col: "col-start-1" },
  { kind: "image", icon: FiImage, key: "kind.image", col: "col-start-2" },
];

export default function KindTabs({ value, onChange, counts, disabled, className }: KindTabsProps) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  return (
    <div
      role="group"
      aria-label={tx(t, "kind.label")}
      className={cx("grid grid-cols-2 gap-1 rounded-full bg-white/[0.05] p-1", className)}
    >
      {/* Подложка выбранного вида лежит в первой ячейке и переезжает во вторую
          (ширина ячейки + зазор gap-1), а не гаснет в одной и вспыхивает в другой. */}
      <span
        aria-hidden
        className={cx(
          "pointer-events-none col-start-1 row-start-1 rounded-full bg-white/[0.1] shadow-[inset_0_1px_0_rgba(255,255,255,0.1)] transition-transform duration-300 ease-[var(--vs-ease)] motion-reduce:transition-none",
          value === "image" && "translate-x-[calc(100%+0.25rem)]",
        )}
      />
      {KINDS.map(({ kind, icon: Icon, key, col }) => {
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
              "relative row-start-1 flex min-h-11 min-w-0 items-center justify-center gap-1.5 rounded-full px-3 text-[13px] font-semibold transition-colors md:min-h-9",
              col,
              VS_FOCUS,
              active ? "text-accent" : off ? "text-muted" : "text-muted hover:text-foreground",
              off ? "cursor-not-allowed opacity-50" : "cursor-pointer",
            )}
          >
            <Icon className="size-4 shrink-0" aria-hidden />
            <span className="truncate">{tx(t, key)}</span>
            {empty && <span className="shrink-0 text-[10px] font-normal text-muted-2">· {tx(t, "kind.soon")}</span>}
          </button>
        );
      })}
    </div>
  );
}
