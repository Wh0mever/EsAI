"use client";

/**
 * Телефон (< 768 px): чип «Seedance 2.0 · 9:16 · 10 с ▾» в строке композера и
 * нижняя шторка с той же панелью параметров (§9.7).
 *
 * Шторка — общая BottomSheet студии (FE-1): высота от visualViewport (--vvh,
 * --kb), поэтому клавиатура у полей seed и негатива её не закрывает; Esc,
 * свайп вниз, ловушка фокуса и возврат фокуса — там же. Открыта ли —
 * ui.panels.settings в сторе (или проп open). На ширине от 768 px шторка не
 * рисуется: там параметры — панель справа (оболочка FE-1).
 *
 * Стор — пропсами или из контекста <VideoStudio>: композер (FE-3) может
 * поставить просто <SettingsChip />.
 */
import { useSyncExternalStore, type Dispatch } from "react";
import { useTranslation } from "react-i18next";
import { FiChevronDown, FiSliders } from "react-icons/fi";
import type { ModelJSON, ShotParams, VsAction, VsKind, VsState } from "@/lib/vstudio/types";
import BottomSheet from "../BottomSheet";
import { VS_PILL } from "../ui/skin";
import RunSettingsPanel, { useStudioStore } from "./RunSettingsPanel";
import { cx } from "./SettingsBits";
import { AUTO, chipParts, findModel } from "./settingsModel";
import { tx, type Translate } from "./settingsText";
import { useRunSettingsSync } from "./useRunSettingsSync";

const MOBILE_QUERY = "(max-width: 767px)";

function subscribeMedia(cb: () => void) {
  if (typeof window === "undefined" || !window.matchMedia) return () => {};
  const mq = window.matchMedia(MOBILE_QUERY);
  mq.addEventListener("change", cb);
  return () => mq.removeEventListener("change", cb);
}
const isMobileNow = () => (typeof window !== "undefined" && window.matchMedia ? window.matchMedia(MOBILE_QUERY).matches : false);

/** true на ширине меньше 768 px. На сервере — false. */
export function useIsMobile(): boolean {
  return useSyncExternalStore(subscribeMedia, isMobileNow, () => false);
}

/** «Seedance 2.0 · 9:16 · 10 с» — пусто, пока модели не пришли. */
export function settingsSummary(t: Translate, model: ModelJSON | null, kind: VsKind, params: ShotParams): string {
  const parts = chipParts(model, kind, params);
  return [
    parts.model,
    parts.aspect ? (parts.aspect === AUTO ? tx(t, "settings.aspectAuto") : parts.aspect) : "",
    parts.duration != null ? tx(t, "settings.seconds", { n: parts.duration }) : "",
  ]
    .filter(Boolean)
    .join(" · ");
}

/* ------------------------------------------------------------------ */
/* Чип                                                                 */
/* ------------------------------------------------------------------ */

export type SettingsChipProps = {
  state?: VsState;
  dispatch?: Dispatch<VsAction>;
  /** По умолчанию открывает шторку (ui/panel settings). */
  onClick?: () => void;
  className?: string;
};

/**
 * «Seedance 2.0 · 9:16 · 10 с ▾». Заодно держит жизненный цикл параметров
 * (useRunSettingsSync): на телефоне панель закрыта, а выбор модели по
 * умолчанию и сохранение в проект должны работать. Повторный вызов хука рядом
 * с контейнером ничего не удваивает.
 */
export function SettingsChip({ state, dispatch, onClick, className }: SettingsChipProps) {
  const store = useStudioStore(state, dispatch);
  useRunSettingsSync(store.state, store.dispatch);
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const { composer, models } = store.state;
  const model = findModel(models, composer.model, composer.kind);
  const summary = settingsSummary(t, model, composer.kind, composer.params);
  const open = !!store.state.ui.panels.settings;

  return (
    <button
      type="button"
      onClick={onClick ?? (() => store.dispatch({ type: "ui/panel", panel: "settings", open: true }))}
      aria-haspopup="dialog"
      aria-expanded={open}
      aria-label={tx(t, "settings.chipAria", { summary: summary || tx(t, "mobile.params") })}
      className={cx(
        VS_PILL,
        // Телефон: чип во всю свободную ширину строки и не ниже 44 px; длинная сводка обрезается, а не раздвигает строку.
        // Нижняя граница ширины — два значка: когда длинная подпись «Создать» забирает строку, чип остаётся
        // кнопкой, а его шеврон не выезжает поверх соседней «@» (лишнее режет overflow-hidden).
        "min-w-14 max-w-full justify-start overflow-hidden max-md:min-h-11 max-md:w-full max-md:shrink",
        className,
      )}
    >
      <FiSliders className="size-3.5 shrink-0 opacity-70" aria-hidden />
      {summary ? (
        <span className="min-w-0 truncate">{summary}</span>
      ) : (
        <span className="vs-film h-2.5 w-28 rounded-full" aria-hidden />
      )}
      <FiChevronDown className="ml-auto size-3.5 shrink-0 opacity-70" aria-hidden />
    </button>
  );
}

/* ------------------------------------------------------------------ */
/* Шторка                                                              */
/* ------------------------------------------------------------------ */

export type SettingsSheetProps = {
  state?: VsState;
  dispatch?: Dispatch<VsAction>;
  /** По умолчанию — state.ui.panels.settings. */
  open?: boolean;
  onClose?: () => void;
  /** true (по умолчанию) — рисуется только на телефоне. */
  mobileOnly?: boolean;
};

export default function SettingsSheet({ state, dispatch, open, onClose, mobileOnly = true }: SettingsSheetProps) {
  const store = useStudioStore(state, dispatch);
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const mobile = useIsMobile();
  const isOpen = (open ?? !!store.state.ui.panels.settings) && (!mobileOnly || mobile);
  const close = onClose ?? (() => store.dispatch({ type: "ui/panel", panel: "settings", open: false }));

  // Шторка, а не экран: сверху видно ленту — понятно, куда вернёшься.
  return (
    <BottomSheet open={isOpen} onClose={close} title={tx(t, "settings.title")} size="half">
      <RunSettingsPanel state={store.state} dispatch={store.dispatch} variant="sheet" />
    </BottomSheet>
  );
}
