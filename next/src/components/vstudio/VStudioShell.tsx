"use client";

import { useEffect, useState, useSyncExternalStore } from "react";
import type { ReactNode, RefObject } from "react";
import BottomSheet from "./BottomSheet";
import MobileDrawer from "./MobileDrawer";
import type { VsBreakpoint } from "./context";
import { vx } from "./ui/skin";

/**
 * Каркас студии по ширине окна (§9.2, §9.7).
 *
 * ≥1280  история 248 px | лента до 920 px с композером внизу; «Параметры
 *        запуска» 340 px — третья колонка, по умолчанию свёрнута.
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
 *
 * Первый экран (home) занимает всю ширину центральной колонки: поля и ширину
 * его секции задают себе сами. Прокручивается он там же, где и лента, а
 * композер остаётся внизу той же ширины, что и в проекте.
 *
 * Верхняя строка прозрачная — сцена под ней одна на всю колонку. Линия под
 * строкой появляется, только когда лента прокручена: иначе на первом экране
 * она отрезала бы заголовок от собственного света.
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

/** Сколько пикселей ленты должно уйти вверх, чтобы под верхней строкой появилась линия. */
const SCROLLED_PX = 4;

/** Лента прокручена? Слушаем её контейнер, а не окно: окно в студии не прокручивается. */
function useScrolled(scrollRef: RefObject<HTMLElement | null>): boolean {
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    let frame = 0;
    const read = () => {
      frame = 0;
      setScrolled(el.scrollTop > SCROLLED_PX);
    };
    // Не чаще раза за кадр: событий прокрутки приходит больше, чем экран успевает нарисовать.
    const onScroll = () => {
      if (!frame) frame = window.requestAnimationFrame(read);
    };
    // Первое чтение — тоже через кадр: лента могла открыться уже прокрученной.
    onScroll();
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      el.removeEventListener("scroll", onScroll);
      if (frame) window.cancelAnimationFrame(frame);
    };
  }, [scrollRef]);
  return scrolled;
}

/**
 * Обёртка верхней строки. Состояние «прокручено» живёт здесь, а не в оболочке:
 * при переходе через порог перерисовывается одна линия, а не лента с композером.
 */
function TopLine({ scrollRef, children }: { scrollRef: RefObject<HTMLElement | null>; children: ReactNode }) {
  const scrolled = useScrolled(scrollRef);
  return (
    <div className="relative shrink-0">
      {children}
      {/* Линия лежит поверх нижнего края и не занимает высоты: строка не прыгает на пиксель. */}
      <div
        className={vx(
          "pointer-events-none absolute inset-x-0 bottom-0 h-px bg-border transition-opacity duration-300 motion-reduce:transition-none",
          scrolled ? "opacity-100" : "opacity-0",
        )}
        aria-hidden="true"
      />
    </div>
  );
}

/** Боковая колонка: чуть светлее сцены и полупрозрачная, чтобы не спорить с кадрами. */
const SIDE = "min-h-0 bg-surface/60";

export type VStudioShellProps = {
  breakpoint: VsBreakpoint;
  /** Первый экран: проекта нет, в ленте — StudioHome во всю ширину колонки. */
  home: boolean;
  /** Левая колонка: full — 248 px или в шторке, compact — значки 64 px. */
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
  home,
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
      ? "grid-cols-[248px_minmax(0,1fr)_340px]"
      : "grid-cols-[248px_minmax(0,1fr)]"
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
      {desktop && <aside className={vx(SIDE, "flex flex-col border-r border-border")}>{rail("full")}</aside>}
      {laptop && <aside className={vx(SIDE, "flex flex-col border-r border-border")}>{rail("compact")}</aside>}

      <main className="relative flex min-h-0 min-w-0 flex-col" aria-label={labels.main}>
        <TopLine scrollRef={feedScrollRef}>{wide ? header : topBar}</TopLine>
        {banner}
        {/* Лента уходит под верхнюю строку так же мягко, как под панель запроса
            (vs-dock): затухание висит над её верхом и высоты не занимает. На
            первом экране оно длиннее — гасит срез луча над заголовком. Слой
            выше плашек на карточках (z-10), но ниже меню и зоны перетаскивания
            (z-30). Свой слой ленте (isolate) не даём: зерно первого экрана
            смешивается с фоном оболочки, а в отдельном слое стало бы шумом. */}
        <div className="relative z-20 h-0 shrink-0" aria-hidden="true">
          <div
            className={vx(
              "pointer-events-none absolute inset-x-0 top-0 bg-gradient-to-b from-background to-transparent",
              home ? "h-6" : "h-4",
            )}
          />
        </div>
        {/* relative: скрытые подписи для экранных читалок (sr-only — position:absolute) внутри
            ленты иначе привязывались к <main> мимо этой прокрутки, оболочка получала лишнюю
            высоту, и переход фокуса сдвигал всю студию вверх без возможности вернуть.
            overflow-x-hidden — страховка от того же по горизонтали: при одном overflow-y-auto
            колонка прокручивается и вбок, и подпись правее экрана давала свайпом увести вбок
            всю студию. Режет так же, как прежний вычисленный auto, — пропадает только сдвиг. */}
        <div ref={feedScrollRef} className="relative min-h-0 flex-1 overflow-x-hidden overflow-y-auto overscroll-contain" data-vs-feed="">
          {/* Нижний отступ ленты — не меньше затухания над композером (vs-dock, 56 px):
              иначе кнопки последней карточки остались бы под ним. */}
          <div className={home ? "w-full pb-10" : "mx-auto w-full max-w-[920px] px-3 pb-14 pt-4 sm:px-4"}>{feed}</div>
        </div>
        {composer && (
          // Затухание ленты (vs-dock::before) рисуется выше края этого блока,
          // поэтому прокрутка — у внутреннего: свой overflow его бы обрезал.
          <div className="vs-dock shrink-0 bg-background">
            {/* Композер (подсказки, лоток, поле) выше видимой части окна под
                верхней строкой — прокручивается сам: строка «Создать · N кр»
                остаётся достижимой, а оболочка не переполняется. На любой
                ширине: телефон на боку шире 768 px, а планшету клавиатура
                оставляет меньше половины экрана. relative — по той же причине,
                что у ленты: скрытые подписи (sr-only) должны прокручиваться
                вместе с композером, а не добавлять высоту оболочке. */}
            <div className="relative mx-auto max-h-[calc(var(--vvh,100dvh)_-_3.5rem_-_env(safe-area-inset-top,0px))] w-full max-w-[920px] overflow-y-auto overscroll-contain px-3 pb-[max(0.5rem,env(safe-area-inset-bottom))] pt-2 sm:px-4">
              {composer}
            </div>
          </div>
        )}
        {centerOverlay}
      </main>

      {settingsColumn && (
        <aside className={vx(SIDE, "overflow-y-auto overscroll-contain border-l border-border")} aria-label={settingsTitle}>
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
