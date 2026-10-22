"use client";

import { useId, useState, useSyncExternalStore, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { FiCheck, FiLoader, FiMusic, FiScissors, FiSliders, FiZap } from "react-icons/fi";
import BottomSheet from "@/components/vstudio/BottomSheet";
import { VS_BTN_GHOST, VS_FOCUS, VS_LABEL, VS_PILL, VS_PILL_ON, vx } from "@/components/vstudio/ui/skin";
import { CS_DOT, CS_RUN_GOLD, CS_RUN_OFF } from "@/components/studio/ui/cartoonSkin";
import { hasSound, type SoundInfo } from "./audioLogic";
import { ASPECTS, FITS, fillText, formatDuration, type TextSpec } from "./mergeLogic";
import type { MergeAspect, MergeFit } from "./mergeTypes";
import { useSoundText } from "./soundText";

/**
 * Док склейки — как панель запроса видеостудии: формат (16:9 / 9:16 / 1:1),
 * заполнение кадра («Поля» / «Обрезать»), «Звук», итог «N фрагм. · M:SS» и
 * одна золотая кнопка «Склеить · 20 кр». С 768 px всё в одну строку; на
 * телефоне — две: сводка параметров (нажатие открывает шторку с выбором) и
 * «Звук», под ними итог и кнопка во всю ширину.
 *
 * Голос и музыку оплачивают, когда они готовы; цена на кнопке — только
 * склейка, и строка рядом говорит, что оплаченный звук второй раз не спишется.
 *
 * Кнопка не disabled, а aria-disabled: фокус остаётся на ней, а причина
 * («добавьте хотя бы 2 фрагмента») читается диктором и видна строкой.
 *
 * Что значат выбранные формат и заполнение, с 768 px написано строкой под
 * кнопками: подсказка при наведении не видна ни на планшете, ни с клавиатуры.
 */

/** Ключ перевода без двоеточия: «:» у i18next отделяет пространство имён. */
const ASPECT_KEY: Record<MergeAspect, "wide" | "tall" | "square"> = { "16:9": "wide", "9:16": "tall", "1:1": "square" };

const ASPECT_RU: Record<"wide" | "tall" | "square", string> = {
  wide: "YouTube, горизонтальное",
  tall: "Reels, TikTok, Shorts",
  square: "Квадрат для ленты",
};

const FIT_RU: Record<MergeFit, string> = {
  pad: "Поля",
  crop: "Обрезать",
};

const FIT_HINT_RU: Record<MergeFit, string> = {
  pad: "Кадр целиком, по краям — его размытая копия",
  crop: "Кадр на весь экран, лишние края срезаются",
};

const WIDE_QUERY = "(min-width: 768px)";

function subscribeWide(onChange: () => void): () => void {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return () => {};
  const media = window.matchMedia(WIDE_QUERY);
  media.addEventListener("change", onChange);
  return () => media.removeEventListener("change", onChange);
}

/** С 768 px — кнопки значений в строку, уже — сводка и шторка (как в студиях). */
function useWide(): boolean {
  return useSyncExternalStore(
    subscribeWide,
    () => typeof window.matchMedia === "function" && window.matchMedia(WIDE_QUERY).matches,
    () => true,
  );
}

/** Значок формата: рамка в пропорциях кадра. */
function AspectIcon({ aspect }: { aspect: MergeAspect }) {
  const size = aspect === "16:9" ? "h-2.5 w-[18px]" : aspect === "9:16" ? "h-[18px] w-2.5" : "size-3.5";
  return <span className={vx("inline-block shrink-0 rounded-[3px] border-[1.5px] border-current", size)} aria-hidden="true" />;
}

const PILL = `${VS_PILL} !px-3 tabular-nums aria-disabled:!cursor-not-allowed aria-disabled:opacity-60`;
const TOTAL = "flex min-h-11 min-w-0 shrink-0 flex-col items-end justify-center rounded-xl px-1.5 text-right leading-tight md:px-2";

export type MergePrimary =
  /** Можно склеить. */
  | { kind: "run"; price: number }
  /** Кредитов не хватает — кнопка ведёт к пополнению. */
  | { kind: "short"; price: number; missing: number }
  /** Склеить нельзя: причина строкой. */
  | { kind: "off"; price: number; reason: TextSpec }
  /** Запрос ушёл или склейка идёт. */
  | { kind: "busy" };

/** «Звук» в доке: что уже есть и куда открывается панель. */
export type MergeDockSound = {
  info: SoundInfo;
  /** Что из звука уже оплачено. */
  paid: "voice" | "music" | "both" | null;
  open: boolean;
  /** Открывается шторкой (телефон, планшет); иначе — колонкой слева. */
  popup: boolean;
  buttonId: string;
  /** id панели в колонке — для aria-controls. */
  panelId: string;
  onToggle: () => void;
};

export type MergeDockProps = {
  aspect: MergeAspect;
  fit: MergeFit;
  /** Формат и заполнение менять нельзя (склейка идёт). */
  locked: boolean;
  count: number;
  total: number;
  primary: MergePrimary;
  saving: boolean;
  onAspect: (a: MergeAspect) => void;
  onFit: (f: MergeFit) => void;
  onRun: () => void;
  /** «N фрагм. · M:SS» — к ленте. */
  onTotal: () => void;
  sound: MergeDockSound;
};

export default function MergeDock({
  aspect,
  fit,
  locked,
  count,
  total,
  primary,
  saving,
  onAspect,
  onFit,
  onRun,
  onTotal,
  sound,
}: MergeDockProps) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const soundText = useSoundText();
  const wide = useWide();
  const [sheet, setSheet] = useState(false);
  const [hint, setHint] = useState(false);
  const reasonId = useId();
  const choiceId = useId();
  const paidId = useId();

  const credits = (n: number) => t("top.balance", { defaultValue: "{{n}} кр", n });
  const fitLabel = (f: MergeFit) => t(`merge.fit.${f}`, { defaultValue: FIT_RU[f] });
  const fitHint = (f: MergeFit) => t(`merge.fitHint.${f}`, { defaultValue: FIT_HINT_RU[f] });
  const aspectHint = (a: MergeAspect) => t(`merge.aspect.${ASPECT_KEY[a]}`, { defaultValue: ASPECT_RU[ASPECT_KEY[a]] });
  const formatTitle = t("merge.dock.format", { defaultValue: "Формат" });
  const fillTitle = t("merge.dock.fill", { defaultValue: "Заполнение кадра" });
  const lock = locked ? ({ "aria-disabled": true } as const) : {};

  const aspectPills = (
    <div role="group" aria-label={formatTitle} className="flex items-center gap-1.5">
      {ASPECTS.map((a) => (
        <button
          key={a}
          type="button"
          onClick={() => {
            if (!locked) onAspect(a);
          }}
          aria-pressed={aspect === a}
          aria-describedby={aspect === a ? choiceId : undefined}
          title={aspectHint(a)}
          {...lock}
          className={vx(PILL, aspect === a && VS_PILL_ON)}
        >
          <AspectIcon aspect={a} />
          {a}
        </button>
      ))}
    </div>
  );

  const fitPills = (
    <div role="group" aria-label={fillTitle} className="flex items-center gap-1.5">
      {FITS.map((f) => (
        <button
          key={f}
          type="button"
          onClick={() => {
            if (!locked) onFit(f);
          }}
          aria-pressed={fit === f}
          aria-describedby={fit === f ? choiceId : undefined}
          title={fitHint(f)}
          {...lock}
          className={vx(PILL, fit === f && VS_PILL_ON)}
        >
          {fitLabel(f)}
        </button>
      ))}
    </div>
  );

  // Итог: число фрагментов и длина будущего ролика; нажатие — к ленте.
  const countText = t("merge.dock.count", { defaultValue: "{{n}} фрагм.", n: count });
  const totalTitle = t("merge.dock.total", { defaultValue: "Фрагментов: {{n}}, длина {{total}}", n: count, total: formatDuration(total) });
  const totalNode = (
    <button type="button" onClick={onTotal} title={totalTitle} className={vx(TOTAL, "cursor-pointer transition-colors hover:bg-vs-ink/[0.06]", VS_FOCUS)}>
      <span className={vx(VS_LABEL, "max-md:font-medium max-md:normal-case max-md:tracking-normal")} aria-hidden="true">
        {countText}
      </span>
      <span className="text-sm font-semibold tabular-nums text-foreground" aria-hidden="true">
        {formatDuration(total)}
      </span>
      <span className="sr-only">{totalTitle}</span>
    </button>
  );

  const priceText = (price: number) => (price > 0 ? credits(price) : t("merge.dock.free", { defaultValue: "бесплатно" }));
  const runFull = (price: number) => t("merge.dock.run", { defaultValue: "Склеить · {{price}}", price: priceText(price) });
  // Оплаченный звук: «Склеить · 20 кр» спишет только склейку.
  const paidText = soundText.paid(sound.paid);
  let reason: string | null = null;
  let button: ReactNode;
  if (primary.kind === "busy") {
    const busy = t("merge.dock.busy", { defaultValue: "Склеиваем…" });
    button = (
      <button type="button" aria-disabled aria-busy className={vx(CS_RUN_GOLD, "!cursor-wait active:!scale-100 max-md:w-full max-md:!px-4")}>
        <FiLoader className="size-4 shrink-0 animate-spin motion-reduce:animate-none" aria-hidden="true" />
        {busy}
      </button>
    );
  } else if (primary.kind === "short") {
    const label = t("merge.dock.short", { defaultValue: "Пополнить · не хватает {{n}}", n: credits(primary.missing) });
    // На телефоне у кнопки своя строка во всю ширину — подпись та же, что на компьютере.
    button = (
      <button type="button" onClick={onRun} title={label} className={vx(CS_RUN_GOLD, "min-w-0 max-w-full max-md:w-full max-md:!px-4")}>
        <FiZap className="size-4 shrink-0" aria-hidden="true" />
        <span className="min-w-0 truncate">{label}</span>
      </button>
    );
  } else if (primary.kind === "off") {
    reason = primary.reason.key
      ? t(primary.reason.key, { defaultValue: primary.reason.ru, ...primary.reason.params })
      : fillText(primary.reason.ru, primary.reason.params);
    button = (
      <button
        type="button"
        onClick={() => setHint(true)}
        aria-disabled
        aria-describedby={reasonId}
        title={reason}
        className={vx(CS_RUN_OFF, "min-w-0 max-w-full !cursor-not-allowed max-md:w-full max-md:!px-4")}
      >
        <FiScissors className="size-4 shrink-0" aria-hidden="true" />
        <span className="min-w-0 truncate">{runFull(primary.price)}</span>
      </button>
    );
  } else {
    button = (
      <button
        type="button"
        onClick={onRun}
        aria-describedby={paidText ? paidId : undefined}
        className={vx(CS_RUN_GOLD, "min-w-0 max-w-full max-md:w-full max-md:!px-4")}
      >
        <FiScissors className="size-4 shrink-0" aria-hidden="true" />
        <span className="min-w-0 truncate">{runFull(primary.price)}</span>
      </button>
    );
  }

  const summary = `${aspect} · ${fitLabel(fit)}`;

  // «Звук»: колонка слева или шторка; пока склейка идёт — недоступен, как остальные параметры.
  const soundList = soundText.list(sound.info);
  const soundName = t("merge.audio.title", { defaultValue: "Звук" });
  const soundLabel = soundList
    ? t("merge.dock.soundState", { defaultValue: "Звук: {{state}}", state: soundList })
    : t("merge.dock.soundEmpty", { defaultValue: "Звук: голос за кадром и музыка" });
  const soundOn = hasSound(sound.info);
  const soundPill = (stretch: boolean) => (
    <button
      id={sound.buttonId}
      type="button"
      onClick={() => {
        if (!locked) sound.onToggle();
      }}
      {...lock}
      aria-label={soundLabel}
      title={soundLabel}
      aria-expanded={sound.open}
      aria-haspopup={sound.popup ? "dialog" : undefined}
      aria-controls={!sound.popup && sound.open ? sound.panelId : undefined}
      className={vx(PILL, stretch ? "!h-11 min-w-0 flex-1 justify-start !gap-2 overflow-hidden" : "shrink-0", sound.open && VS_PILL_ON)}
    >
      {sound.info.pending ? (
        <FiLoader className="shrink-0 animate-spin text-vs-accent motion-reduce:animate-none" aria-hidden="true" />
      ) : (
        <FiMusic className={vx("shrink-0", soundOn ? "text-vs-accent" : "text-muted")} aria-hidden="true" />
      )}
      <span className="min-w-0 truncate" aria-hidden="true">
        {stretch && soundList ? `${soundName} · ${soundList}` : soundName}
      </span>
      {soundOn && !stretch && <span className={CS_DOT} aria-hidden="true" />}
    </button>
  );
  const paidNode = paidText ? (
    <p id={paidId} className="ml-auto inline-flex items-start gap-1 text-right">
      <FiCheck className="mt-0.5 shrink-0 text-vs-accent" aria-hidden="true" />
      <span>{paidText}</span>
    </p>
  ) : null;

  return (
    <>
      <div role="region" aria-label={t("merge.dock.label", { defaultValue: "Параметры склейки" })} data-vs-composer="">
        <div className="vs-solid flex flex-col gap-1.5 rounded-[20px] p-2 transition-[border-color] duration-200 focus-within:!border-vs-ink/25 md:gap-2 md:rounded-[24px] md:p-3">
          {wide ? (
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1.5">
              <div className="vs-noscroll -my-1 min-w-0 flex-1 basis-0 overflow-x-auto px-0.5 py-1" aria-busy={saving || undefined}>
                <div className="flex w-max items-center gap-2">
                  {aspectPills}
                  <span className="h-5 w-px shrink-0 bg-vs-ink/15" aria-hidden="true" />
                  {fitPills}
                </div>
              </div>
              {soundPill(false)}
              {totalNode}
              <div className="ml-auto flex min-w-0 max-w-full shrink-0">{button}</div>
            </div>
          ) : (
            <div className="flex flex-col gap-1.5">
              <div className="flex items-center gap-1.5">
                <button
                  type="button"
                  onClick={() => {
                    // Пока склейка идёт, шторка закрыта; нажатие не должно открыть её потом само.
                    if (!locked) setSheet(true);
                  }}
                  {...lock}
                  aria-haspopup="dialog"
                  aria-expanded={sheet}
                  className={vx(PILL, "!h-11 min-w-0 flex-1 justify-start !gap-2 overflow-hidden")}
                >
                  <FiSliders className="shrink-0 text-muted" aria-hidden="true" />
                  <AspectIcon aspect={aspect} />
                  <span className="min-w-0 truncate" aria-hidden="true">
                    {summary}
                  </span>
                  <span className="sr-only">
                    {formatTitle}: {aspect}. {fillTitle}: {fitLabel(fit)}
                  </span>
                </button>
                {soundPill(true)}
              </div>
              <div className="flex items-center gap-1.5">
                {totalNode}
                <div className="flex min-w-0 flex-1">{button}</div>
              </div>
            </div>
          )}
          {wide ? (
            <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-0.5 px-1 text-xs leading-snug text-muted">
              <p id={choiceId} className="min-w-0">
                {aspectHint(aspect)} · {fitHint(fit)}
              </p>
              {reason && (
                <p id={reasonId} className="ml-auto text-right">
                  {reason}
                </p>
              )}
              {paidNode}
            </div>
          ) : (
            <>
              {reason && (
                <p id={reasonId} className={hint ? "px-1 text-right text-xs leading-snug text-muted" : "sr-only"}>
                  {reason}
                </p>
              )}
              {paidNode && <div className="flex px-1 text-xs leading-snug text-muted">{paidNode}</div>}
            </>
          )}
          {saving && <span className="sr-only">{t("merge.dock.saving", { defaultValue: "Сохраняем…" })}</span>}
        </div>
      </div>

      {!wide && (
        <BottomSheet
          open={sheet && !locked}
          onClose={() => setSheet(false)}
          title={t("merge.dock.label", { defaultValue: "Параметры склейки" })}
          className="vs-root"
          zIndex={1050}
          footer={
            <button type="button" onClick={() => setSheet(false)} className={vx(VS_BTN_GHOST, "w-full")}>
              {t("merge.dock.done", { defaultValue: "Готово" })}
            </button>
          }
        >
          <div className="flex flex-col gap-5 pt-1">
            <fieldset className="flex flex-col gap-2">
              <legend className={vx(VS_LABEL, "mb-2")}>{formatTitle}</legend>
              {ASPECTS.map((a) => (
                <button
                  key={a}
                  type="button"
                  onClick={() => onAspect(a)}
                  aria-pressed={aspect === a}
                  className={vx(VS_PILL, "!h-auto min-h-12 w-full justify-start gap-3 !rounded-2xl py-2 text-left", aspect === a && VS_PILL_ON)}
                >
                  <AspectIcon aspect={a} />
                  <span className="flex min-w-0 flex-col">
                    <span className="font-semibold">{a}</span>
                    <span className="truncate text-[12px] font-normal text-muted">{aspectHint(a)}</span>
                  </span>
                </button>
              ))}
            </fieldset>
            <fieldset className="flex flex-col gap-2">
              <legend className={vx(VS_LABEL, "mb-2")}>{fillTitle}</legend>
              {FITS.map((f) => (
                <button
                  key={f}
                  type="button"
                  onClick={() => onFit(f)}
                  aria-pressed={fit === f}
                  className={vx(VS_PILL, "!h-auto min-h-12 w-full flex-col items-start !gap-0.5 !rounded-2xl py-2 text-left", fit === f && VS_PILL_ON)}
                >
                  <span className="font-semibold">{fitLabel(f)}</span>
                  <span className="text-[12px] font-normal text-muted">{fitHint(f)}</span>
                </button>
              ))}
            </fieldset>
          </div>
        </BottomSheet>
      )}
    </>
  );
}
