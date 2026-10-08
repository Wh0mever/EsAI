"use client";

/**
 * Выбор модели: свёрнутая кнопка с текущей моделью и раскрывающийся список
 * карточек (§9.2 «Модель [Seedance 2.0 ▾]»). С inline — только сам список:
 * так он стоит в окошке у чипа модели в панели запроса.
 *
 * Карточка: точка вендора, имя, бейдж из админки, «от N кр» (для картинок —
 * «N кр за картинку»), обычное время, метки возможностей («до 9 фото», «первый
 * и последний кадр», «звук», «до 15 с»), замок у премиум-моделей (клик ведёт в
 * пэйволл — модель не выбирается). Под карточкой — чем модель не подходит к
 * фото, которые уже в запросе: причина видна до выбора, а не после оплаты.
 *
 * «Другая модель» из ленты (FE-5) раскрывает список через openModelPicker().
 */
import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { useTranslation } from "react-i18next";
import { FiCheck, FiChevronDown, FiClock, FiLock, FiRefreshCw } from "react-icons/fi";
import type { ModelJSON, VsError, VsKind } from "@/lib/vstudio/types";
import { VS_BTN_GHOST, VS_TAG, VS_TAG_GOLD } from "../ui/skin";
import { CARD_HOVER, Pill, Reason, Section, VendorDot, cx } from "./SettingsBits";
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
  /**
   * Только список карточек: без заголовка раздела, без кнопки-свёртки и без
   * анимации раскрытия. Ширину, отступы и прокрутку даёт тот, кто его показывает
   * (окошко у чипа модели, 360 px). Событие openModelPicker() такой список не
   * слушает — окошко открывает его хозяин.
   */
  inline?: boolean;
};

function priceText(t: Translate, m: ModelJSON, kind: VsKind): string {
  if (kind === "image") {
    const n = m.per_image ?? m.price_from;
    return n ? tx(t, "settings.perImage", { n: fmtNum(n) }) : "";
  }
  return m.price_from ? tx(t, "settings.priceFrom", { n: fmtNum(m.price_from) }) : "";
}

/** Метки и причины стоят под именем, а не под точкой: точка 8 px + зазор 10 px. */
const UNDER_NAME = "pl-[18px]";

function ModelCard({
  model,
  kind,
  selected,
  counts,
  compact,
  dense,
  onClick,
  t,
}: {
  model: ModelJSON;
  kind: VsKind;
  selected: boolean;
  counts: InputCounts;
  compact?: boolean;
  /** Список в окошке: скругление меньше, чтобы повторять скругление окошка. */
  dense?: boolean;
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
      <div className="flex items-start gap-2.5">
        <VendorDot modelId={model.id} className="mt-1.5" />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-1.5 gap-y-1">
            <span className="min-w-0 truncate text-sm font-semibold leading-5 text-foreground">{model.name}</span>
            {model.badge && <span className={cx(VS_TAG_GOLD, "whitespace-nowrap")}>{model.badge}</span>}
          </div>
          {(eta || model.locked) && (
            <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] leading-4 text-muted">
              {eta && (
                <span className="inline-flex items-center gap-1">
                  <FiClock className="size-3 shrink-0" aria-hidden />
                  {tx(t, "settings.eta", { t: txRef(t, eta) })}
                </span>
              )}
              {model.locked && (
                <span className="inline-flex items-center gap-1 text-status-wait">
                  <FiLock className="size-3 shrink-0" aria-hidden />
                  {tx(t, "settings.locked")}
                </span>
              )}
            </div>
          )}
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1">
          {price && <span className={cx(VS_TAG, "whitespace-nowrap tabular-nums")}>{price}</span>}
          {selected && !compact && (
            <span className="inline-flex items-center gap-0.5 text-[11px] font-semibold leading-4 text-vs-accent">
              <FiCheck className="size-3" aria-hidden />
              {tx(t, "settings.selected")}
            </span>
          )}
        </div>
      </div>
      {/* Метки видны и у свёрнутой кнопки (§9.2: «Модель [Seedance 2.0 ▾] — звук, до 9 фото»). */}
      {badges.length > 0 && (
        <div className={cx("mt-2 flex flex-wrap gap-1", UNDER_NAME)}>
          {badges.map((b) => (
            <Pill key={b.key}>{txRef(t, b)}</Pill>
          ))}
        </div>
      )}
      {compat.length > 0 && (
        <div id={reasonId} className={cx("mt-2 flex flex-col gap-0.5", UNDER_NAME)}>
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
        "vs-card block w-full cursor-pointer px-3 py-2.5 text-left active:scale-[0.985]",
        dense ? "rounded-xl" : "rounded-2xl",
        // Либо выбрана, либо подсвечивается при наведении: вместе наведение гасит золотую рамку.
        selected ? "vs-card-on" : CARD_HOVER,
        // Приглушаем только в тёмной теме: на белой карточке мелкие подписи с прозрачностью
        // уходят ниже 4.5:1, а замок и «платный тариф» отмечают модель и без неё.
        model.locked && "dark:opacity-80",
      )}
    >
      {body}
    </button>
  );
}

/** ↑ ↓ Home End ходят по карточкам списка — как в обычном выпадающем списке. */
function onListKey(e: KeyboardEvent<HTMLDivElement>) {
  if (e.key !== "ArrowDown" && e.key !== "ArrowUp" && e.key !== "Home" && e.key !== "End") return;
  const items = Array.from(e.currentTarget.querySelectorAll<HTMLButtonElement>("button"));
  const at = items.findIndex((el) => el === document.activeElement);
  if (at < 0) return;
  e.preventDefault();
  const last = items.length - 1;
  const next = e.key === "Home" ? 0 : e.key === "End" ? last : Math.max(0, Math.min(last, at + (e.key === "ArrowDown" ? 1 : -1)));
  items[next]?.focus();
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
  inline = false,
}: ModelPickerProps) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  // «Другая модель» нажали, пока панели не было (шторка ещё открывается) — сразу раскрыт.
  const [open, setOpen] = useState(() => defaultOpen || pendingOpen);
  const listId = useId();
  const titleId = useId();
  const rootRef = useRef<HTMLDivElement>(null);
  const current = models.find((m) => m.id === value) ?? null;
  const hasModels = models.length > 0;

  // «Другая модель» из ленты: раскрыть список и показать его.
  useEffect(() => {
    // Список в окошке не сворачивается, а отметку «раскрыть» оставляем панели.
    if (inline) return;
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
  }, [listId, inline]);

  // Окошко у чипа: выбранная модель видна сразу, даже если список длиннее окошка.
  // Фокус переносим на неё, только если окошко уже поставило его внутрь списка.
  useEffect(() => {
    if (!inline || !hasModels) return;
    let raf = requestAnimationFrame(() => {
      raf = requestAnimationFrame(() => {
        const root = rootRef.current;
        const chosen = root?.querySelector<HTMLButtonElement>('button[aria-pressed="true"]');
        if (!root || !chosen) return;
        chosen.scrollIntoView({ block: "nearest" });
        if (root.contains(document.activeElement)) chosen.focus({ preventScroll: true });
      });
    });
    return () => cancelAnimationFrame(raf);
  }, [inline, hasModels]);

  const pick = (m: ModelJSON) => {
    if (m.locked) {
      onLocked(m);
      return;
    }
    onSelect(m.id);
    setOpen(false);
  };

  const list = (
    <div
      id={listId}
      role="group"
      aria-labelledby={inline ? undefined : titleId}
      aria-label={inline ? tx(t, "settings.model") : undefined}
      // Зазор над списком лежит внутри него: свёрнутый список не оставляет пустой полосы.
      className={cx("flex flex-col", inline ? "gap-1.5" : "gap-2 pb-1 pt-2")}
      inert={inline ? undefined : !open}
      onKeyDown={onListKey}
    >
      {models.map((m) => (
        <ModelCard
          key={m.id}
          model={m}
          kind={kind}
          selected={m.id === value}
          counts={counts}
          dense={inline}
          onClick={() => pick(m)}
          t={t}
        />
      ))}
    </div>
  );

  let content;
  if (!hasModels && error && !loading) {
    content = (
      <div className="vs-card flex flex-col items-start gap-2.5 rounded-2xl p-3">
        <Reason tone="error">{tx(t, "settings.modelsError")}</Reason>
        {onRetry && (
          <button type="button" onClick={onRetry} className={VS_BTN_GHOST}>
            <FiRefreshCw className="size-3.5" aria-hidden />
            {tx(t, "settings.retry")}
          </button>
        )}
      </div>
    );
  } else if (!hasModels && loading) {
    content = (
      <div className="flex flex-col gap-2" aria-busy="true">
        <p className="sr-only">{tx(t, "settings.modelsLoading")}</p>
        <div className={cx("vs-film h-[4.5rem]", inline ? "rounded-xl" : "rounded-2xl")} />
        {inline && (
          <>
            <div className="vs-film h-[4.5rem] rounded-xl" />
            <div className="vs-film h-[4.5rem] rounded-xl" />
          </>
        )}
      </div>
    );
  } else if (!hasModels) {
    content = <Reason tone="muted">{tx(t, "settings.modelsEmpty")}</Reason>;
  } else if (inline) {
    content = list;
  } else {
    content = (
      <div ref={rootRef} className="flex flex-col">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          aria-controls={listId}
          className={cx(
            "vs-card flex w-full cursor-pointer items-start gap-2 rounded-2xl px-3 py-2.5 text-left",
            CARD_HOVER,
          )}
        >
          <div className="min-w-0 flex-1">
            {current ? (
              <ModelCard model={current} kind={kind} selected counts={counts} compact t={t} />
            ) : (
              <span className="text-sm font-semibold leading-5 text-foreground">{tx(t, "settings.modelChange")}</span>
            )}
          </div>
          <span className="sr-only">{tx(t, open ? "settings.modelCollapse" : "settings.modelChange")}</span>
          <FiChevronDown
            className={cx(
              "mt-0.5 size-4 shrink-0 text-muted transition-transform duration-200 motion-reduce:transition-none",
              open && "rotate-180",
            )}
            aria-hidden
          />
        </button>

        {/* Раскрытие через grid-rows — плавно и без фиксированной высоты, как в чате. */}
        <div
          className={cx(
            "grid transition-[grid-template-rows,opacity] duration-200 ease-out motion-reduce:transition-none",
            open ? "grid-rows-[1fr] opacity-100" : "grid-rows-[0fr] opacity-0",
          )}
        >
          {/* Поля по бокам — чтобы overflow-hidden не срезал золотое кольцо выбранной карточки. */}
          <div className="-mx-1 min-h-0 overflow-hidden px-1">{list}</div>
        </div>
      </div>
    );
  }

  if (inline) {
    return (
      <div ref={rootRef} className="flex min-w-0 flex-col">
        {content}
      </div>
    );
  }
  return (
    <Section id={titleId} title={tx(t, "settings.model")}>
      {content}
    </Section>
  );
}
