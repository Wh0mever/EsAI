"use client";

/**
 * Видеостудия, композер: кнопка «Создать · 164 кр» и её состояния (§9.6, §5.4).
 *
 * Что на кнопке, решает composerLogic.runView: цена из свежего quote,
 * «Пополнить · не хватает N кр», «Войти и создать», «Ждём @Image 3…»,
 * «Загружаем фото…», спиннер отправки, «Запущено». Если запуск невозможен —
 * причина словами под кнопкой, а не только серый цвет (§9.8). Наведение (или
 * ⓘ на телефоне) показывает раскладку цены.
 */
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { FiCheck, FiInfo, FiLoader, FiLock, FiLogIn, FiPlusCircle } from "react-icons/fi";
import { errorText, issueText } from "@/lib/vstudio/errors";
import type { QuoteJSON, RefLabels, VsKind } from "@/lib/vstudio/types";
import { fmtNum, runClickable, type RunView } from "./composerLogic";
import { ct } from "./composerText";
import PriceBreakdown from "./PriceBreakdown";
import AnchoredPopover from "./Popover";

type T = ReturnType<typeof useTranslation>["t"];

export type RunButtonProps = {
  view: RunView;
  kind: VsKind;
  /** Свежий quote — для раскладки цены. */
  quote: QuoteJSON | null;
  labels: RefLabels;
  onClick: () => void;
  /** Телефон: короче подписи, без ⓘ (раскладка — PriceInfoButton в строке счётчика). */
  compact?: boolean;
  /** Причину под кнопкой рисует родитель (телефон: во всю ширину под строкой). */
  hideReason?: boolean;
};

function subjectOf(t: T, labels: RefLabels, uid: string | undefined, slot: string): string {
  const label = uid ? labels[uid] : undefined;
  if (label?.n) return `@Image ${label.n}`;
  if (slot === "first_frame") return `@${ct(t, "tray.firstFrame")}`;
  if (slot === "last_frame") return `@${ct(t, "tray.lastFrame")}`;
  return label?.text || "@Image …";
}

/** Причина серым, а не красным: модель под замком или просто пустое поле. */
export function quietReason(view: RunView): boolean {
  return view.kind === "locked" || (view.kind === "blocked" && view.issue.code === "prompt_empty");
}

/** Подпись кнопки и причина под ней. */
export function runTexts(
  t: T,
  view: RunView,
  kind: VsKind,
  labels: RefLabels,
  compact = false,
): { label: string; reason: string | null } {
  // На телефоне в строке ещё чип параметров и «@»: «Создать · 164» без «кр» (§9.7).
  const price = (credits: number) => ct(t, compact ? "composer.runShort" : "composer.run", { credits: fmtNum(credits) });
  switch (view.kind) {
    case "sending":
      return { label: ct(t, "composer.sending"), reason: null };
    case "started":
      return { label: ct(t, "composer.started"), reason: null };
    case "signin":
      return { label: ct(t, "composer.signin"), reason: null };
    case "no_model":
      return { label: ct(t, "composer.modelsLoading"), reason: null };
    case "uploading":
      return { label: ct(t, "composer.waitUpload"), reason: null };
    case "waiting": {
      const subject = subjectOf(t, labels, view.item.assetUid, view.item.slot);
      const n = view.item.assetUid ? labels[view.item.assetUid]?.n : null;
      return {
        label: n ? ct(t, "composer.waitAsset", { n }) : ct(t, "composer.waitFrame", { subject }),
        reason: null,
      };
    }
    case "failed_upload":
      return { label: ct(t, "composer.runNoPrice"), reason: ct(t, "composer.failedUpload") };
    case "limit":
      return {
        label: ct(t, "composer.runNoPrice"),
        reason: ct(t, view.of === "image" ? "composer.limitOpenImage" : "composer.limitOpen", { n: view.n }),
      };
    case "blocked":
      return { label: ct(t, "composer.runNoPrice"), reason: issueText(t, view.issue, "errors") };
    case "no_price":
      return {
        label: ct(t, "composer.runNoPrice"),
        reason: view.error ? `${errorText(t, view.error)} ${ct(t, "composer.priceRetry")}`.trim() : null,
      };
    case "locked":
      return { label: price(view.credits), reason: ct(t, "composer.locked") };
    case "topup":
      return { label: ct(t, "composer.topup", { n: fmtNum(view.missing) }), reason: null };
    case "quoting":
      return { label: view.credits != null ? price(view.credits) : ct(t, "composer.runNoPrice"), reason: null };
    case "run":
      return { label: price(view.credits), reason: null };
    default:
      void kind;
      return { label: ct(t, "composer.runNoPrice"), reason: null };
  }
}

export default function RunButton({ view, kind, quote, labels, onClick, compact, hideReason }: RunButtonProps) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const { label, reason } = runTexts(t, view, kind, labels, compact);
  const clickable = runClickable(view);
  const [info, setInfo] = useState(false);
  const hover = useRef<ReturnType<typeof setTimeout> | null>(null);
  const groupRef = useRef<HTMLDivElement | null>(null);
  useEffect(
    () => () => {
      if (hover.current) clearTimeout(hover.current);
    },
    [],
  );

  const priced = Boolean(quote && quote.credits != null && (view.kind === "run" || view.kind === "topup" || view.kind === "locked"));
  const accent = view.kind === "run" || view.kind === "topup" || view.kind === "signin" || view.kind === "started";
  const muted = view.kind === "blocked" || view.kind === "limit" || view.kind === "failed_upload" || view.kind === "no_price";
  const busy = view.kind === "sending" || view.kind === "uploading" || view.kind === "waiting" || view.kind === "no_model";

  const icon =
    view.kind === "sending" || view.kind === "uploading" || view.kind === "waiting" ? (
      <FiLoader className="animate-spin" aria-hidden />
    ) : view.kind === "signin" ? (
      <FiLogIn aria-hidden />
    ) : view.kind === "locked" ? (
      <FiLock aria-hidden />
    ) : view.kind === "topup" ? (
      <FiPlusCircle aria-hidden />
    ) : view.kind === "started" ? (
      <FiCheck aria-hidden />
    ) : null;

  const openSoon = () => {
    if (!priced) return;
    if (hover.current) clearTimeout(hover.current);
    hover.current = setTimeout(() => setInfo(true), 250);
  };
  const closeSoon = () => {
    if (hover.current) clearTimeout(hover.current);
    hover.current = setTimeout(() => setInfo(false), 200);
  };

  return (
    <div className={`flex min-w-0 flex-col items-end gap-1 ${compact ? "" : "max-w-[22rem]"}`}>
      <div
        ref={groupRef}
        className="flex items-center gap-1"
        onPointerEnter={(e) => {
          if (e.pointerType === "mouse") openSoon();
        }}
        onPointerLeave={(e) => {
          if (e.pointerType === "mouse") closeSoon();
        }}
      >
        {priced && !compact && (
          <button
            type="button"
            onClick={() => setInfo((v) => !v)}
            aria-expanded={info}
            aria-label={ct(t, "composer.priceInfo")}
            title={ct(t, "composer.priceInfo")}
            className="grid size-11 shrink-0 place-items-center rounded-xl text-muted transition-colors hover:bg-surface-2 hover:text-foreground md:size-9 cursor-pointer"
          >
            <FiInfo aria-hidden />
          </button>
        )}
        <button
          type="button"
          onClick={() => {
            if (clickable) onClick();
          }}
          disabled={busy}
          aria-disabled={!clickable || muted || undefined}
          aria-busy={busy || view.kind === "quoting" || undefined}
          className={`inline-flex min-h-11 items-center justify-center gap-2 whitespace-nowrap rounded-xl px-4 text-sm font-semibold transition-colors ${
            accent
              ? "bg-accent text-on-accent hover:bg-accent-strong"
              : muted
                ? "bg-surface-3 text-muted"
                : "bg-accent/70 text-on-accent"
          } ${busy ? "cursor-wait" : clickable ? "cursor-pointer" : "cursor-not-allowed"} ${compact ? "px-3.5" : "min-w-[9.5rem]"}`}
        >
          {icon}
          {view.kind === "quoting" && view.credits == null ? (
            <span className="inline-flex items-center gap-1.5">
              {ct(t, "composer.runNoPrice")}
              <span aria-hidden>·</span>
              <span className="inline-block h-3 w-9 animate-pulse rounded bg-on-accent/25" aria-hidden />
              <span className="sr-only">{ct(t, "composer.quoting")}</span>
            </span>
          ) : (
            <span className={view.kind === "quoting" ? "opacity-70" : ""}>{label}</span>
          )}
        </button>
      </div>
      {reason && !hideReason && (
        <p
          className={`text-right text-xs leading-snug ${quietReason(view) ? "text-muted" : "text-status-fail"} ${
            compact ? "line-clamp-2" : ""
          }`}
          aria-live="polite"
        >
          {reason}
        </p>
      )}
      {quote && !compact && (
        <AnchoredPopover
          anchor={groupRef}
          open={info && priced}
          onClose={() => setInfo(false)}
          placement="top-end"
          role="region"
          ariaLabel={ct(t, "composer.priceInfo")}
        >
          <div
            onPointerEnter={(e) => {
              if (e.pointerType === "mouse" && hover.current) clearTimeout(hover.current);
            }}
            onPointerLeave={(e) => {
              if (e.pointerType === "mouse") closeSoon();
            }}
          >
            <PriceBreakdown quote={quote} />
          </div>
        </AnchoredPopover>
      )}
    </div>
  );
}

/**
 * «Из чего цена» отдельной кнопкой — для телефона, где рядом с «Создать» нет
 * места под ⓘ: кнопка стоит в строке счётчика и открывает ту же раскладку.
 */
export function PriceInfoButton({ quote }: { quote: QuoteJSON | null }) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const [open, setOpen] = useState(false);
  const anchor = useRef<HTMLButtonElement | null>(null);
  if (!quote || quote.credits == null) return null;
  return (
    <>
      <button
        ref={anchor}
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="inline-flex min-h-9 shrink-0 items-center gap-1 rounded-lg px-1.5 text-xs text-muted hover:text-foreground cursor-pointer"
      >
        <FiInfo aria-hidden />
        {ct(t, "composer.priceInfoShort", { credits: fmtNum(quote.credits) })}
      </button>
      <AnchoredPopover anchor={anchor} open={open} onClose={() => setOpen(false)} placement="top-end" role="region" ariaLabel={ct(t, "composer.priceInfo")}>
        <PriceBreakdown quote={quote} />
      </AnchoredPopover>
    </>
  );
}
