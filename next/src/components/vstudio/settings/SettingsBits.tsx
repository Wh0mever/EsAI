"use client";

/**
 * Мелкие кирпичи панели параметров: заголовок раздела, кнопка-значение с ценой
 * под ней, строка причины, метка возможности, точка вендора. Один вид для всех
 * пикеров, чтобы параметры читались как одна вещь — в колонке, в шторке и в
 * узком окошке у чипа панели запроса.
 *
 * Золото — только у выбранного значения (§9.2: «активные чипы»).
 * Причина выключенного значения — видимым текстом, а не только tooltip (§9.8).
 */
import { useId, type CSSProperties, type ReactNode } from "react";
import { vendorColorByOpenRouterId } from "@/lib/vendorColors";
import { VS_LABEL, VS_TAG, VS_TAG_GOLD, vx } from "../ui/skin";

export const cx = vx;

/**
 * Цветная подложка у vs-card (выбрано, готово, ошибка): ставится вместе с
 * !bg-…. В тёмной теме фон карточки полупрозрачный, и заливка видна сквозь
 * него. В светлой он непрозрачный и закрыл бы её — там градиент снимаем, а в
 * тёмной возвращаем тот же, что у vs-card.
 */
export const CARD_TINT = "!bg-none dark:![background-image:var(--vs-card-bg)]";

/**
 * Наведение на карточку в панели: рамка плотнее и фон чуть другой, без тени.
 * Глубокая тень vs-card-hover здесь не годится — список стоит в прокрутке и в
 * раскрывающемся блоке, они срезали бы её в паре пикселей от карточки.
 * «!» — потому что рамка и фон vs-card заданы вне слоёв Tailwind. Градиент при
 * наведении снимается по той же причине, что и в CARD_TINT.
 */
export const CARD_HOVER =
  "hover:!border-vs-ink/25 hover:!bg-vs-ink/[0.04] hover:!bg-none dark:hover:![background-image:var(--vs-card-bg)]";

const TAG_WARN =
  "inline-flex items-center gap-1 rounded-full border border-status-wait/40 bg-status-wait/[0.08] px-2 py-0.5 text-[11px] font-medium leading-4 text-status-wait";

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
    <section className="flex min-w-0 flex-col gap-2.5" aria-labelledby={titleId}>
      <div className="flex min-h-5 items-center gap-1.5">
        {icon && (
          <span className="shrink-0 text-muted-2 [&>svg]:size-3.5" aria-hidden>
            {icon}
          </span>
        )}
        <h3 id={titleId} className={VS_LABEL}>
          {title}
        </h3>
        {aside && <div className="ml-auto flex shrink-0 items-center pl-2">{aside}</div>}
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
        // Фокус с клавиатуры карточке (vs-card) рисует контур из app/globals.css.
        "vs-card flex min-h-11 min-w-0 flex-col items-center justify-center gap-0.5 rounded-xl px-1.5 py-1.5 text-xs font-semibold tabular-nums md:min-h-10",
        // Выбранное — золотая рамка и едва заметная золотая заливка; наведение только у невыбранного.
        active ? cx("vs-card-on !bg-accent/[0.07] text-foreground", CARD_TINT) : "text-foreground/65",
        disabled
          ? "cursor-not-allowed opacity-45"
          : cx("cursor-pointer active:scale-[0.97]", !active && CARD_HOVER, !active && "hover:text-foreground"),
        className,
      )}
    >
      {icon && <span className={cx("flex items-center justify-center", active && "text-vs-accent")}>{icon}</span>}
      <span className="leading-tight">{label}</span>
      {sub != null && sub !== "" && (
        // Цена — в обоих состояниях text-muted: на карточке поверх стекла muted-2 не дотягивает до контраста 4.5.
        <span className="whitespace-nowrap text-[10px] font-normal leading-tight text-muted">{sub}</span>
      )}
    </button>
  );
}

/**
 * Видимая причина: почему значение выключено или что будет на самом деле.
 * w-0 + min-w-full: длинная фраза переносится по ширине раздела и не
 * растягивает окошко, которое само подбирает ширину по содержимому.
 */
export function Reason({ children, tone = "warn", id }: { children: ReactNode; tone?: "warn" | "muted" | "error"; id?: string }) {
  return (
    <p
      id={id}
      className={cx(
        "w-0 min-w-full text-[11px] leading-snug",
        tone === "warn" && "text-status-wait",
        tone === "error" && "text-status-fail",
        tone === "muted" && "text-muted-2",
      )}
    >
      {children}
    </p>
  );
}

/** Маленькая метка возможности модели. */
export function Pill({ children, tone = "plain" }: { children: ReactNode; tone?: "plain" | "accent" | "warn" }) {
  return (
    <span
      className={cx(
        "whitespace-nowrap",
        tone === "plain" && VS_TAG,
        tone === "accent" && VS_TAG_GOLD,
        tone === "warn" && TAG_WARN,
      )}
    >
      {children}
    </span>
  );
}

/**
 * Цветная точка вендора модели: цвет — из общей карты lib/vendorColors, тот же,
 * что в каталоге моделей. Чужих логотипов не рисуем. Цвета карты подобраны под
 * тёмный фон: на белом светлые (бирюзовый ByteDance, серый xAI) бледнеют,
 * поэтому в светлой теме точка на пятую часть темнее.
 */
export function VendorDot({ modelId, className }: { modelId: string | null | undefined; className?: string }) {
  const style = { "--vs-dot": vendorColorByOpenRouterId(modelId ?? undefined) } as CSSProperties;
  return (
    <span
      aria-hidden
      style={style}
      className={cx(
        "inline-block size-2 shrink-0 rounded-full bg-[color:color-mix(in_srgb,var(--vs-dot)_78%,var(--vs-ink))] [box-shadow:0_0_0_3px_color-mix(in_srgb,var(--vs-dot)_22%,transparent)] dark:bg-[color:var(--vs-dot)]",
        className,
      )}
    />
  );
}
