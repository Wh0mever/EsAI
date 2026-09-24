"use client";

/**
 * Выбор модели: свёрнутая кнопка с текущей моделью и раскрывающийся список
 * карточек (§9.2 «Модель [Seedance 2.0 ▾]»).
 *
 * Карточка: имя, бейдж из админки, «от N кр» (для картинок — «N кр за
 * картинку»), обычное время, бейджи возможностей («до 9 фото», «первый и
 * последний кадр», «звук», «до 15 с»), замок у премиум-моделей (клик ведёт в
 * пэйволл — модель не выбирается). Под карточкой — чем модель не подходит к
 * фото, которые уже в запросе: причина видна до выбора, а не после оплаты.
 *
 * «Другая модель» из ленты (FE-5) раскрывает список через openModelPicker().
 */
import { useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { FiCheck, FiChevronDown, FiClock, FiLock, FiRefreshCw } from "react-icons/fi";
import type { ModelJSON, VsError, VsKind } from "@/lib/vstudio/types";
import { Pill, Reason, Section, cx } from "./SettingsBits";
import { etaText, modelBadges, modelCompat, type InputCounts } from "./settingsModel";
import { fmtNum, tx, txRef, type Translate } from "./settingsText";

/** Событие окна: раскрыть список моделей (кнопка «Другая модель» в карточке ленты). */
export const MODEL_PICKER_EVENT = "vstudio:model-picker";

/** Сколько ждать, пока смонтируется панель (на телефоне — шторка открывается анимацией). */
const PENDING_OPEN_MS = 2000;
let pendingOpen = false;
let pendingTimer: ReturnType<typeof setTimeout> | null = null;

/**
 * Раскрыть список моделей во всех смонтированных ModelPicker (панель или
 * шторка). Если панели сейчас нет (шторка на телефоне ещё открывается), список
 * раскроется у той, что смонтируется в ближайшие 2 секунды. Панель при этом
 * открывает вызывающий: dispatch({type: "ui/panel", panel: "settings", open: true}).
 */
export function openModelPicker(): void {
  if (typeof window === "undefined") return;
  pendingOpen = true;
  if (pendingTimer) clearTimeout(pendingTimer);
  pendingTimer = setTimeout(() => {
    pendingOpen = false;
    pendingTimer = null;
  }, PENDING_OPEN_MS);
  window.dispatchEvent(new CustomEvent(MODEL_PICKER_EVENT, { detail: { open: true } }));
}

function takePendingOpen(): boolean {
  if (!pendingOpen) return false;
  pendingOpen = false;
  if (pendingTimer) clearTimeout(pendingTimer);
  pendingTimer = null;
  return true;
}

export type ModelPickerProps = {
  kind: VsKind;
  models: ModelJSON[];
  value: string | null;
  counts: InputCounts;
  onSelect: (id: string) => void;
  /** Клик по модели под замком: пэйволл premium_locked (или вход для гостя). */
  onLocked: (model: ModelJSON) => void;
  loading?: boolean;
  error?: VsError | null;
  onRetry?: () => void;
  defaultOpen?: boolean;
};

function priceText(t: Translate, m: ModelJSON, kind: VsKind): string {
  if (kind === "image") {
    const n = m.per_image ?? m.price_from;
    return n ? tx(t, "settings.perImage", { n: fmtNum(n) }) : "";
  }
  return m.price_from ? tx(t, "settings.priceFrom", { n: fmtNum(m.price_from) }) : "";
}

function ModelCard({
  model,
  kind,
  selected,
  counts,
  compact,
  onClick,
  t,
}: {
  model: ModelJSON;
  kind: VsKind;
  selected: boolean;
  counts: InputCounts;
  compact?: boolean;
  onClick?: () => void;
  t: Translate;
}) {
  const eta = etaText(model.eta_s);
  const badges = modelBadges(model, kind);
  const compat = modelCompat(model, kind, counts);
  const price = priceText(t, model, kind);
  const reasonId = useId();
  const body = (
    <>
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="truncate text-sm font-semibold text-foreground">{model.name}</span>
            {model.badge && <Pill tone="accent">{model.badge}</Pill>}
          </div>
          <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-muted">
            {eta && (
              <span className="inline-flex items-center gap-1">
                <FiClock className="size-3" aria-hidden />
                {tx(t, "settings.eta", { t: txRef(t, eta) })}
              </span>
            )}
            {model.locked && (
              <span className="inline-flex items-center gap-1 text-status-wait">
                <FiLock className="size-3" aria-hidden />
                {tx(t, "settings.locked")}
              </span>
            )}
          </div>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1">
          {price && <span className="text-xs font-semibold text-foreground">{price}</span>}
          {selected && !compact && (
            <span className="inline-flex items-center gap-0.5 text-[10px] font-semibold text-accent">
              <FiCheck className="size-3" aria-hidden />
              {tx(t, "settings.selected")}
            </span>
          )}
        </div>
      </div>
      {/* Бейджи видны и у свёрнутой кнопки (§9.2: «Модель [Seedance 2.0 ▾] — звук, до 9 фото»). */}
      {badges.length > 0 && (
        <div className="mt-1.5 flex flex-wrap gap-1">
          {badges.map((b) => (
            <Pill key={b.key}>{txRef(t, b)}</Pill>
          ))}
        </div>
      )}
      {compat.length > 0 && (
        <div id={reasonId} className="mt-1.5 flex flex-col gap-0.5">
          {compat.map((c) => (
            <Reason key={c.key}>{txRef(t, c)}</Reason>
          ))}
        </div>
      )}
    </>
  );
  if (!onClick) return <div className="w-full">{body}</div>;
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={selected}
      aria-describedby={compat.length ? reasonId : undefined}
      className={cx(
        "w-full rounded-xl border px-3 py-2.5 text-left transition-colors cursor-pointer",
        selected ? "border-accent bg-accent-soft" : "border-border bg-surface hover:border-border-strong",
        model.locked && "opacity-80",
      )}
    >
      {body}
    </button>
  );
}

export default function ModelPicker({
  kind,
  models,
  value,
  counts,
  onSelect,
  onLocked,
  loading,
  error,
  onRetry,
  defaultOpen = false,
}: ModelPickerProps) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  // «Другая модель» нажали, пока панели не было (шторка ещё открывается) — сразу раскрыт.
  const [open, setOpen] = useState(() => defaultOpen || pendingOpen);
  const listId = useId();
  const titleId = useId();
  const rootRef = useRef<HTMLDivElement>(null);
  const current = models.find((m) => m.id === value) ?? null;

  // «Другая модель» из ленты: раскрыть список и показать его.
  useEffect(() => {
    let raf = 0;
    const reveal = () => {
      cancelAnimationFrame(raf);
      // Через кадр после шторки: она сначала забирает фокус себе (BottomSheet), потом — выбранная модель.
      raf = requestAnimationFrame(() => {
        raf = requestAnimationFrame(() => {
          const root = rootRef.current;
          if (!root || !root.offsetParent) return;
          root.scrollIntoView({ block: "nearest", behavior: "smooth" });
          root
            .querySelector<HTMLButtonElement>(`#${CSS.escape(listId)} button[aria-pressed="true"]`)
            ?.focus({ preventScroll: true });
        });
      });
    };
    const onOpen = () => {
      takePendingOpen();
      setOpen(true);
      reveal();
    };
    if (takePendingOpen()) reveal();
    window.addEventListener(MODEL_PICKER_EVENT, onOpen);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener(MODEL_PICKER_EVENT, onOpen);
    };
  }, [listId]);

  const pick = (m: ModelJSON) => {
    if (m.locked) {
      onLocked(m);
      return;
    }
    onSelect(m.id);
    setOpen(false);
  };

  let content;
  if (!models.length && error && !loading) {
    content = (
      <div className="flex flex-col items-start gap-2 rounded-xl border border-border bg-surface-2 p-3">
        <Reason tone="error">{tx(t, "settings.modelsError")}</Reason>
        {onRetry && (
          <button
            type="button"
            onClick={onRetry}
            className="inline-flex min-h-9 items-center gap-1.5 rounded-lg border border-border px-3 text-xs font-semibold text-foreground hover:border-border-strong cursor-pointer"
          >
            <FiRefreshCw className="size-3.5" aria-hidden />
            {tx(t, "settings.retry")}
          </button>
        )}
      </div>
    );
  } else if (!models.length && loading) {
    content = (
      <div className="flex flex-col gap-2" aria-busy="true">
        <p className="sr-only">{tx(t, "settings.modelsLoading")}</p>
        <div className="h-16 animate-pulse rounded-xl bg-surface-2" />
      </div>
    );
  } else if (!models.length) {
    content = <Reason tone="muted">{tx(t, "settings.modelsEmpty")}</Reason>;
  } else {
    content = (
      <div ref={rootRef} className="flex flex-col gap-2">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          aria-controls={listId}
          className={cx(
            "flex w-full items-start gap-2 rounded-xl border bg-surface px-3 py-2.5 text-left transition-colors cursor-pointer",
            open ? "border-border-strong" : "border-border hover:border-border-strong",
          )}
        >
          <div className="min-w-0 flex-1">
            {current ? (
              <ModelCard model={current} kind={kind} selected counts={counts} compact t={t} />
            ) : (
              <span className="text-sm font-semibold text-foreground">{tx(t, "settings.modelChange")}</span>
            )}
          </div>
          <span className="sr-only">{tx(t, open ? "settings.modelCollapse" : "settings.modelChange")}</span>
          <FiChevronDown
            className={cx("mt-0.5 size-4 shrink-0 text-muted transition-transform duration-200", open && "rotate-180")}
            aria-hidden
          />
        </button>

        {/* Раскрытие через grid-rows — плавно и без фиксированной высоты, как в чате. */}
        <div
          className={cx(
            "grid transition-[grid-template-rows,opacity] duration-200 ease-out",
            open ? "grid-rows-[1fr] opacity-100" : "grid-rows-[0fr] opacity-0",
          )}
        >
          <div className="min-h-0 overflow-hidden">
            <div id={listId} role="group" aria-labelledby={titleId} className="flex flex-col gap-2" inert={!open}>
              {models.map((m) => (
                <ModelCard
                  key={m.id}
                  model={m}
                  kind={kind}
                  selected={m.id === value}
                  counts={counts}
                  onClick={() => pick(m)}
                  t={t}
                />
              ))}
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <Section id={titleId} title={tx(t, "settings.model")}>
      {content}
    </Section>
  );
}
