"use client";

import { useId, useRef, useState, type ReactNode, type RefObject } from "react";
import { useTranslation } from "react-i18next";
import type { IconType } from "react-icons";
import { FiAlertCircle, FiLoader, FiTrash2, FiX } from "react-icons/fi";
import { VS_BTN_GHOST, VS_BTN_LINK, VS_CARD, VS_FOCUS, VS_INPUT, VS_TAG, VS_TAG_GOLD, vx } from "@/components/vstudio/ui/skin";
import { CS_NOTE_FAIL, CS_NOTE_GOLD } from "@/components/studio/ui/cartoonSkin";
import { volumePercent } from "./audioLogic";
import { fillText, formatDuration, shortDate, type TextSpec } from "./mergeLogic";
import type { MergeTrack } from "./mergeTypes";

/**
 * Общие кусочки панели «Звук»: блок с заголовком, плашки отказа и «делается»,
 * ползунок громкости, «Убрать» с подтверждением, подпись дорожки.
 */

/**
 * Платное действие панели («Озвучить», «Создать») — золотой контур: золотая
 * заливка на экране одна — «Склеить» в доке.
 */
export const SOUND_PAID_BTN = vx(
  VS_BTN_GHOST,
  "!border-vs-accent/45 !font-semibold !text-vs-accent hover:!bg-accent/[0.1] aria-disabled:!cursor-not-allowed aria-disabled:opacity-60",
);
/** Поле текста: шрифт 16 px на телефоне — иначе iOS приближает страницу. */
export const SOUND_TEXT_FIELD = vx(VS_INPUT, "resize-none py-2 leading-snug max-sm:!text-base");
export const SOUND_SELECT = vx(VS_INPUT, "cursor-pointer max-sm:!text-base");
export const SOUND_SPIN = "animate-spin motion-reduce:animate-none";
/** Готовая дорожка: текст, плеер, кнопки. */
export const SOUND_TRACK = "flex flex-col gap-2.5 rounded-xl border border-vs-ink/10 bg-vs-ink/[0.03] p-3";

/** TextSpec → строка на языке страницы (нет ключа — русский текст сервера). */
export function useSay() {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  return (spec: TextSpec) => (spec.key ? t(spec.key, { defaultValue: spec.ru, ...spec.params }) : fillText(spec.ru, spec.params));
}

/** Фокус пропал (кнопка, на которой он стоял, исчезла) — вернуть его на заголовок блока. */
export function keepFocus(heading: RefObject<HTMLElement | null>) {
  window.requestAnimationFrame(() => {
    const active = document.activeElement;
    if (!active || active === document.body || !document.contains(active)) heading.current?.focus({ preventScroll: true });
  });
}

export function SoundBlock({
  icon: Icon,
  title,
  chip,
  sub,
  headingRef,
  children,
}: {
  icon: IconType;
  title: string;
  chip?: ReactNode;
  sub?: ReactNode;
  headingRef?: RefObject<HTMLHeadingElement | null>;
  children: ReactNode;
}) {
  const headingId = useId();
  return (
    <section aria-labelledby={headingId} className={vx(VS_CARD, "flex min-w-0 flex-col gap-3 p-3.5 sm:p-4")}>
      <div className="flex items-start gap-2.5">
        <span className="grid size-9 shrink-0 place-items-center rounded-xl bg-accent/[0.1] text-vs-accent" aria-hidden="true">
          <Icon />
        </span>
        <div className="min-w-0 flex-1 pt-0.5">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <h3 ref={headingRef} id={headingId} tabIndex={-1} className="text-[15px] font-semibold leading-tight text-foreground focus:outline-none">
              {title}
            </h3>
            {chip}
          </div>
          {sub && <p className="mt-1 text-[13px] leading-snug text-muted">{sub}</p>}
        </div>
      </div>
      {children}
    </section>
  );
}

/** Метка у заголовка блока: «Готово» (золотая) или «Делается…». */
export function SoundChip({ tone, children }: { tone: "ready" | "busy"; children: ReactNode }) {
  return (
    <span className={tone === "ready" ? VS_TAG_GOLD : VS_TAG}>
      {tone === "busy" && <FiLoader className={vx("size-3", SOUND_SPIN)} aria-hidden="true" />}
      {children}
    </span>
  );
}

/**
 * Отказ у своего блока и «Скрыть». alert — отказ на нажатие человека (диктор
 * прочтёт сразу); неудачная дорожка с сервера — без него.
 */
export function SoundError({
  text,
  onClose,
  busy = false,
  alert = true,
}: {
  text: string;
  onClose: () => void;
  busy?: boolean;
  alert?: boolean;
}) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const close = t("merge.closeError", { defaultValue: "Скрыть" });
  return (
    <div role={alert ? "alert" : undefined} className={vx(CS_NOTE_FAIL, "flex items-start gap-2.5 !px-3 !py-2.5 !text-[13px] leading-snug")}>
      <FiAlertCircle className="mt-0.5 shrink-0" aria-hidden="true" />
      <p className="min-w-0 flex-1 break-words">{text}</p>
      <button
        type="button"
        onClick={onClose}
        disabled={busy}
        aria-label={close}
        title={close}
        className={vx(
          "relative -my-1 -mr-1 grid size-8 shrink-0 cursor-pointer place-items-center rounded-full transition-colors hover:bg-status-fail/15 disabled:cursor-wait disabled:opacity-60 before:absolute before:-inset-1.5",
          VS_FOCUS,
        )}
      >
        {busy ? <FiLoader className={SOUND_SPIN} aria-hidden="true" /> : <FiX aria-hidden="true" />}
      </button>
    </div>
  );
}

/** Звук делается: крутилка и что происходит. */
export function SoundPending({ children }: { children: ReactNode }) {
  return (
    <p className={vx(CS_NOTE_GOLD, "flex items-start gap-2.5 !px-3 !py-2.5 !text-[13px] leading-snug")}>
      <FiLoader className={vx("mt-0.5 shrink-0 text-vs-accent", SOUND_SPIN)} aria-hidden="true" />
      <span className="min-w-0 flex-1">{children}</span>
    </p>
  );
}

/** Громкость 0…max: подпись, ползунок (44 px на телефоне) и проценты. */
export function VolumeSlider({
  label,
  value,
  max,
  onChange,
}: {
  label: string;
  value: number;
  max: number;
  onChange: (v: number) => void;
}) {
  const id = useId();
  const pct = volumePercent(value);
  return (
    <div className="flex min-w-0 items-center gap-3">
      <label htmlFor={id} className="w-[7.5rem] shrink-0 text-xs leading-tight text-muted">
        {label}
      </label>
      <input
        id={id}
        type="range"
        min={0}
        max={max}
        step={0.05}
        value={value}
        aria-valuetext={`${pct} %`}
        onChange={(e) => onChange(Number(e.currentTarget.value))}
        className={vx("h-11 min-w-0 flex-1 cursor-pointer rounded-full accent-[var(--accent)] md:h-8", VS_FOCUS)}
      />
      <span className="w-11 shrink-0 text-right text-xs tabular-nums text-muted" aria-hidden="true">
        {pct} %
      </span>
    </div>
  );
}

/**
 * «Убрать» дорожку. Оплаченную — вторым нажатием: новая будет стоить заново,
 * и случайный тап на телефоне не должен стоить кредитов.
 */
export function SoundRemove({
  label,
  ask,
  busy,
  onRemove,
}: {
  label: string;
  /** Вопрос перед удалением; null — убирать сразу (свой трек бесплатный). */
  ask: string | null;
  busy: boolean;
  onRemove: () => void;
}) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const [asking, setAsking] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const yesRef = useRef<HTMLButtonElement>(null);
  const askId = useId();
  const back = () => {
    setAsking(false);
    window.requestAnimationFrame(() => triggerRef.current?.focus({ preventScroll: true }));
  };
  if (asking && ask) {
    return (
      <div role="group" aria-labelledby={askId} className="flex w-full flex-col gap-2 rounded-xl border border-status-fail/30 bg-status-fail/[0.06] p-2.5">
        <p id={askId} className="text-[13px] leading-snug text-foreground">
          {ask}
        </p>
        <div className="flex flex-wrap gap-2">
          <button
            ref={yesRef}
            type="button"
            onClick={() => {
              // Фокус после удаления возвращает блок: кнопка сейчас станет «занята», а дорожка исчезнет.
              setAsking(false);
              onRemove();
            }}
            className={vx(VS_BTN_GHOST, "!border-status-fail/45 !text-status-fail hover:!bg-status-fail/10")}
          >
            <FiTrash2 aria-hidden="true" />
            {t("merge.audio.removeYes", { defaultValue: "Убрать" })}
          </button>
          <button type="button" onClick={back} className={VS_BTN_GHOST}>
            {t("nav.cancel", { defaultValue: "Отмена" })}
          </button>
        </div>
      </div>
    );
  }
  return (
    <button
      ref={triggerRef}
      type="button"
      onClick={() => {
        if (!ask) {
          onRemove();
          return;
        }
        setAsking(true);
        // Вопрос появился на месте кнопки — фокус на «Убрать»: Enter подтверждает, Tab — к «Отмене».
        window.requestAnimationFrame(() => yesRef.current?.focus({ preventScroll: true }));
      }}
      disabled={busy}
      aria-busy={busy || undefined}
      className={vx(VS_BTN_LINK, "hover:!text-status-fail disabled:cursor-wait disabled:opacity-60")}
    >
      {busy ? <FiLoader className={SOUND_SPIN} aria-hidden="true" /> : <FiTrash2 aria-hidden="true" />}
      {label}
    </button>
  );
}

/**
 * «0:03 · оплачено 5 кр · хранится до 21.11» / «0:42 · бесплатно» — под готовой
 * дорожкой. until — склейку ещё правят: звук черновика живёт 30 дней с заказа,
 * и оплаченный голос не должен пропасть молча.
 */
export function useTrackMeta() {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  return (track: MergeTrack, until = false): string => {
    const parts: string[] = [];
    if (typeof track.duration_s === "number" && track.duration_s > 0) parts.push(formatDuration(track.duration_s));
    if (track.source === "upload") parts.push(t("merge.audio.free", { defaultValue: "бесплатно" }));
    else if (track.credits_charged > 0) parts.push(t("merge.audio.paidN", { defaultValue: "оплачено {{n}} кр", n: track.credits_charged }));
    // Копия из прежней склейки: оплачена там.
    else parts.push(t("merge.audio.paidCopy", { defaultValue: "уже оплачено" }));
    const date = until ? shortDate(track.expires_at) : "";
    if (date) parts.push(t("merge.audio.until", { defaultValue: "хранится до {{date}}", date }));
    return parts.join(" · ");
  };
}
