"use client";

import { useSyncExternalStore } from "react";
import type { ReactNode, RefObject } from "react";
import BottomSheet from "./BottomSheet";
import MobileDrawer from "./MobileDrawer";
import type { VsBreakpoint } from "./context";

/**
 * Каркас студии по ширине окна (§9.2, §9.7).
 *
 * ≥1280  три колонки: история 240 px | лента до 860 px с композером внизу |
 *        «Параметры запуска» 340 px (колонку можно свернуть).
 * 1024–1279  история — колонка значков 64 px (полная — шторкой слева),
 *        параметры — панель, выезжающая справа.
 * 768–1023   история — шторка слева, параметры — панель справа поверх ленты.
 * <768   одна колонка: верхняя панель, лента, прилипший композер;
 *        параметры — нижняя шторка.
 *
 * Каждая часть (лента, композер, параметры) монтируется ровно один раз —
 * меняется только контейнер вокруг неё. Две копии панели параметров иначе
 * дважды сохраняли бы Project.settings и дважды спрашивали бы цену.
 *
 * Высота оболочки — видимая часть окна (--vvh из useVisualViewport): на
 * телефоне с открытой клавиатурой композер остаётся над ней.
 */

const Q_DESKTOP = "(min-width: 1280px)";
const Q_LAPTOP = "(min-width: 1024px)";
const Q_TABLET = "(min-width: 768px)";

function readBreakpoint(): VsBreakpoint {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return "desktop";
  if (window.matchMedia(Q_DESKTOP).matches) return "desktop";
  if (window.matchMedia(Q_LAPTOP).matches) return "laptop";
  if (window.matchMedia(Q_TABLET).matches) return "tablet";
  return "mobile";
}

function subscribeBreakpoint(onChange: () => void): () => void {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return () => {};
  const lists = [Q_DESKTOP, Q_LAPTOP, Q_TABLET].map((q) => window.matchMedia(q));
  lists.forEach((l) => l.addEventListener("change", onChange));
  return () => lists.forEach((l) => l.removeEventListener("change", onChange));
}

/** Текущая раскладка по ширине окна; на сервере — компьютерная. */
export function useVsBreakpoint(): VsBreakpoint {
  return useSyncExternalStore(subscribeBreakpoint, readBreakpoint, () => "desktop");
}

export type VStudioShellProps = {
  breakpoint: VsBreakpoint;
  /** Левая колонка: full — 240 px или в шторке, compact — значки 64 px. */
  rail: (variant: "full" | "compact") => ReactNode;
  /** Шторка истории открыта (планшет, телефон, развёрнутая колонка на 1024–1279). */
  railOpen: boolean;
  onRailOpenChange: (open: boolean) => void;
  /** Строка над лентой на компьютере (≥1024). */
  header: ReactNode;
  /** Верхняя панель телефона и планшета (<1024). */
  topBar: ReactNode;
  /** Плашки над лентой: «Нет сети», «Восстановили…». */
  banner?: ReactNode;
  feed: ReactNode;
  composer?: ReactNode;
  /** Панель параметров: колонка, выезжающая панель или содержимое нижней шторки. */
  settings?: ReactNode;
  /** Своя нижняя шторка параметров для телефона (SettingsSheet); без неё — BottomSheet вокруг settings. */
  settingsSheet?: ReactNode;
  settingsTitle: string;
  /** Панель/шторка параметров открыта (<1280). */
  settingsOpen: boolean;
  onSettingsOpenChange: (open: boolean) => void;
  /** Колонка параметров свёрнута (≥1280). */
  settingsCollapsed: boolean;
  /** Поверх центральной колонки: зона перетаскивания файлов. */
  centerOverlay?: ReactNode;
  /** Окна, шторки и тосты — вне сетки. */
  overlays?: ReactNode;
  feedScrollRef: RefObject<HTMLDivElement | null>;
  labels: { history: string; main: string };
};

export default function VStudioShell({
  breakpoint,
  rail,
  railOpen,
  onRailOpenChange,
  header,
  topBar,
  banner,
  feed,
  composer,
  settings,
  settingsSheet,
  settingsTitle,
  settingsOpen,
  onSettingsOpenChange,
  settingsCollapsed,
  centerOverlay,
  overlays,
  feedScrollRef,
  labels,
}: VStudioShellProps) {
  const desktop = breakpoint === "desktop";
  const laptop = breakpoint === "laptop";
  const wide = desktop || laptop;
  const settingsColumn = desktop && !settingsCollapsed && Boolean(settings);

  const grid = desktop
    ? settingsColumn
      ? "grid-cols-[240px_minmax(0,1fr)_340px]"
      : "grid-cols-[240px_minmax(0,1fr)]"
    : laptop
      ? "grid-cols-[64px_minmax(0,1fr)]"
      : "grid-cols-[minmax(0,1fr)]";

  const closeRail = () => onRailOpenChange(false);
  const closeSettings = () => onSettingsOpenChange(false);

  return (
    <div
      className={"grid w-full grid-rows-[minmax(0,1fr)] overflow-hidden bg-background text-foreground " + grid}
      style={{ height: "var(--vvh, 100dvh)" }}
    >
      {desktop && (
        <aside className="flex min-h-0 flex-col border-r border-border bg-surface">{rail("full")}</aside>
      )}
      {laptop && <aside className="flex min-h-0 flex-col border-r border-border bg-surface">{rail("compact")}</aside>}

      <main className="relative flex min-h-0 min-w-0 flex-col" aria-label={labels.main}>
        {wide ? header : topBar}
        {banner}
        <div ref={feedScrollRef} className="min-h-0 flex-1 overflow-y-auto overscroll-contain" data-vs-feed="">
          <div className="mx-auto w-full max-w-[860px] px-3 py-4 sm:px-4">{feed}</div>
        </div>
        {composer && (
          // Телефон с открытой клавиатурой: если композер (подсказки, лоток,
          // поле) выше видимой части окна, он прокручивается сам — строка
          // «Создать · N кр» остаётся достижимой, а не уезжает за край.
          <div className="shrink-0 border-t border-border bg-background max-md:max-h-[calc(var(--vvh,100dvh)-3.5rem)] max-md:overflow-y-auto max-md:overscroll-contain">
            <div className="mx-auto w-full max-w-[860px] px-3 pb-[max(0.5rem,env(safe-area-inset-bottom))] pt-2 sm:px-4">
              {composer}
            </div>
          </div>
        )}
        {centerOverlay}
      </main>

      {settingsColumn && (
        <aside className="min-h-0 overflow-y-auto overscroll-contain border-l border-border bg-surface" aria-label={settingsTitle}>
          {settings}
        </aside>
      )}

      {/* История шторкой: полная колонка на всём, что уже 1280. */}
      {!desktop && (
        <MobileDrawer open={railOpen} onClose={closeRail} side="left" ariaLabel={labels.history} width="min(86vw, 300px)">
          {rail("full")}
        </MobileDrawer>
      )}

      {/* Параметры: справа поверх ленты (768–1279), снизу шторкой (<768). */}
      {settings && (laptop || breakpoint === "tablet") && (
        <MobileDrawer
          open={settingsOpen}
          onClose={closeSettings}
          side="right"
          ariaLabel={settingsTitle}
          width="min(92vw, 360px)"
          backdrop="clear"
          className="overflow-y-auto overscroll-contain"
        >
          {settings}
        </MobileDrawer>
      )}
      {breakpoint === "mobile" &&
        (settingsSheet ??
          (settings ? (
            <BottomSheet open={settingsOpen} onClose={closeSettings} title={settingsTitle} size="half">
              {settings}
            </BottomSheet>
          ) : null))}

      {overlays}
    </div>
  );
}
