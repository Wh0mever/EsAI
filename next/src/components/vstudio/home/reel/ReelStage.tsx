"use client";

import { memo, useCallback, useMemo, useRef, useState } from "react";
import type {
  CSSProperties,
  KeyboardEvent,
  MouseEvent as ReactMouseEvent,
  PointerEvent as ReactPointerEvent,
} from "react";
import { useTranslation } from "react-i18next";
import { FiChevronLeft, FiChevronRight } from "react-icons/fi";
import LazyClip from "../../ui/LazyClip";
import Segments from "../../ui/Segments";
import { VS_ICON_BTN, VS_SECTION, vx } from "../../ui/skin";
import { prefersReducedMotion } from "../../ui/useAutoplayAllowed";
import { useReveal } from "../../ui/useReveal";
import type { ReelItem } from "../showreelData";
import ReelCaption from "./ReelCaption";
import { REEL_ENTER, isBareClick, isStudioReel, type ReelLayoutProps } from "./reelLayout";
import {
  INTENT_PX,
  REEL_INTERVAL_MS,
  dragShift,
  dragSteps,
  fogBand,
  isLoop,
  isPortrait,
  paperFog,
  paperOpacity,
  slotLook,
  slotsAround,
  stepPx,
} from "./reelMath";
import ScenarioRail from "./ScenarioRail";
import { useReelFit } from "./useReelFit";
import { useReelAuto, useReelPause } from "./useReelPause";
import { useReelTrack } from "./useReelTrack";
import { useSettled } from "./useSettled";

/**
 * Карусель первого экрана на экранах от 768 px: сцена с перспективой (§2.2).
 *
 * В центре активный кадр, по бокам — по два соседа, повёрнутых к нему. Ролик
 * играет только в одном кадре — активном; соседи — постеры. Листают стрелками
 * на сцене и на клавиатуре, нажатием на соседа, перетаскиванием и рядом под
 * сценой: у роликов студии это названия сценариев (ScenarioRail), у сцен
 * мультстудии — сегменты. Раз в 7 секунд карусель листается сама, пока человек
 * её видит и не трогает.
 *
 * Нажатие на активный кадр ролика студии — то же, что его золотая кнопка:
 * пример ложится в панель запроса. Отдельной кнопки поверх кадра для этого
 * нет: она закрыла бы «Смотреть» (кнопка во весь кадр, когда ролики не
 * заводятся сами) и дала бы клавиатуре и скринридеру второе такое же действие.
 * Нажатие ловит сам кадр, а кнопки внутри него отвечают за себя; с клавиатуры
 * то же делают золотая кнопка и Enter на самой карусели.
 *
 * Кадры — прямые дети сцены .vs-stage (перспектива действует только на них) и
 * лежат в одной ячейке сетки: высоту сцены задаёт сам кадр, а место каждому —
 * transform. Он, прозрачность и тени меняются CSS-переходом, поэтому любое
 * новое нажатие просто даёт кадрам новую цель — с того места, где их застало.
 *
 * Две темы. Сам кадр и всё, что лежит на нём (чёрная вуаль соседа, подпись,
 * подсветка под курсором), одинаковы: видео тёмное в любой теме. От темы
 * зависит то, чем кадр касается сцены: тень, волосяная кромка, стрелки и то,
 * как дальний кадр уходит из виду. В тёмном зале он гаснет; на «бумаге»
 * притемнённый кадр стоял бы у края серой плитой, поэтому там он растворяется
 * в цвете сцены от ближнего края к дальнему (FOG, reelMath.fogBand).
 */

type Gesture = { id: number; x: number; y: number; live: boolean };

const SLOT = "relative col-start-1 row-start-1 aspect-video max-w-full overflow-hidden rounded-2xl will-change-transform";
/** Пока ширина не измерена (сервер, первый проход) — ширина из макета. */
const SLOT_WIDTH = "w-[min(58vw,760px)]";
const SLOT_MOVE =
  "[transition:transform_600ms_var(--vs-ease),opacity_400ms_ease,box-shadow_400ms_ease] motion-reduce:[transition:none]";
/**
 * Прозрачность места приходит двумя переменными (их ставит Slot), а не готовым
 * opacity: в тёмной теме дальний кадр гаснет по таблице макета, на светлой
 * сцене он бледнее (reelMath.paperOpacity).
 */
const SLOT_FADE = "opacity-[var(--vs-o-paper)] dark:opacity-[var(--vs-o)]";
// Тени — из палитры темы: на «бумаге» чёрная тень легла бы грязным пятном. В
// тёмной теме значения прежние, вплоть до второй, ближней тени активного кадра.
const SLOT_ON =
  "shadow-[var(--vs-shadow-float)] dark:shadow-[var(--vs-shadow-float),0_10px_28px_rgba(0,0,0,0.5)] group-focus-visible/reel:outline-2 group-focus-visible/reel:outline-offset-4 group-focus-visible/reel:outline-vs-accent/80";
const SLOT_SIDE = "shadow-[var(--vs-shadow-soft)] dark:shadow-[0_22px_50px_rgba(0,0,0,0.6)]";
// Дальний кадр на светлой сцене тени не бросает: сам он растворён в «бумаге», и тень обвела бы пустое место.
const SLOT_FAR = "shadow-none dark:shadow-[0_22px_50px_rgba(0,0,0,0.6)]";
const DIM_MOVE = "transition-opacity duration-[400ms] motion-reduce:transition-none";
/**
 * «Туман» светлой сцены: вуаль цвета «бумаги» поверх кадра, гуще к его внешнему
 * краю (vs-fog, globals.css). Это не маска: маска срезала бы и тень кадра, а её
 * границы нельзя вести переходом. Вуаль же проявляется той же прозрачностью,
 * что и затемнение соседа. В тёмной теме её нет.
 */
const FOG = "vs-fog pointer-events-none absolute inset-0 dark:hidden";
/** С какого расстояния кадр считается дальним (между соседом и дальним местом). */
const FAR_FROM = 1.5;
/** Место под сценой: ряд названий или сегменты. Высота одна на все случаи — кадры, придя, не сдвинут страницу. */
const FOOT = "relative -mt-3 h-9";
/**
 * Стрелки стоят у края сцены: обычно над соседним кадром, а у короткой карусели
 * на первом и последнем кадре — над самой сценой. В тёмной теме это тёмное
 * стекло с белым значком, в светлой — белая плашка с тёмным: и на кадре, и на
 * «бумаге» она читается, а чёрный круг на светлой странице был бы чужим.
 * Цвет значка — не vs-ink: в браузерах без color-mix() эти чернила
 * полупрозрачные (globals.css), и значок бы пропал.
 */
const ARROW = `${VS_ICON_BTN} absolute top-1/2 z-20 -translate-y-1/2 !border-vs-ink/15 !bg-surface/90 !text-foreground shadow-md dark:!text-white backdrop-blur-md hover:!bg-surface dark:!bg-black/55 dark:shadow-none dark:hover:!bg-black/75 aria-disabled:cursor-default aria-disabled:opacity-40`;
/** Расстановка заглушек: активный кадр и по соседу с каждой стороны. */
const SKELETON = [-1, 0, 1];
/** Кадр на стоянке или на пути к ней: его не видно, и отзываться ему не на что. */
const PARKED_FROM = 2.5;
/**
 * Через сколько ролик переходит к новому активному кадру. К этому времени
 * прежний уже почти ушёл вбок и притемнён — смена ролика на постер там незаметна.
 */
const HANDOVER_MS = 240;

type SlotProps = {
  item: ReelItem;
  /** Имя кадра — подпись и название для кнопок. */
  name: string;
  /** На сколько мест кадр от центра; дробное — пока его ведут пальцем. */
  d: number;
  active: boolean;
  /** Ролик сейчас у этого кадра. Отстаёт от active на HANDOVER_MS. */
  playing: boolean;
  width: number | null;
  /** Кадр едет сам, переходом, а не за пальцем. */
  eased: boolean;
  /** «Кадр 3 из 12». */
  label: string;
  /** Подпись нажатия на соседа: «Показать: …». */
  pickLabel: string;
  /** Карусель уже листали: кадр, появившийся после этого, проявляется, а не вставляется рывком. */
  late: boolean;
  onUse: (item: ReelItem) => void;
  onPick: (steps: number) => void;
};

const Slot = memo(function Slot({
  item,
  name,
  d,
  active,
  playing,
  width,
  eased,
  label,
  pickLabel,
  late,
  onUse,
  onPick,
}: SlotProps) {
  const look = slotLook(d);
  const parked = Math.abs(d) > PARKED_FROM;
  const far = Math.abs(d) > FAR_FROM;
  // Ролик студии в центре: нажатие на сам кадр применяет пример. Сцена мультстудии — ссылка
  // в другой раздел: уводить туда нажатием на кадр было бы неожиданно, у неё остаётся кнопка.
  const usable = active && item.source === "vstudio";
  // Вертикальный ролик студии показываем целиком, с полями: обрезанный под рамку 16:9, он потерял бы две трети кадра.
  const upright = item.source === "vstudio" && isPortrait(item.aspect);
  const pose = {
    width: width ?? undefined,
    transform: look.transform,
    zIndex: look.zIndex,
    "--vs-o": look.opacity,
    "--vs-o-paper": paperOpacity(look.opacity),
  } as CSSProperties;

  // На стоянку кадр попадает невидимым и выезжает переходом. Но после далёкого
  // прыжка (сегмент, сосед через одного) он рождается сразу на виду. Важно,
  // каким кадр родился, а не каким стал: запоминаем один раз.
  const [bornLate] = useState(late);
  const arrive = useCallback(
    (el: HTMLDivElement | null) => {
      if (!el || !bornLate || prefersReducedMotion() || typeof el.animate !== "function") return;
      try {
        el.animate([{ opacity: 0, offset: 0 }], { duration: 400, easing: "ease-out" });
      } catch {
        // браузер без неявного конечного кадра — появится без проявления
      }
    },
    [bornLate],
  );

  return (
    <div
      ref={arrive}
      role="group"
      aria-label={label}
      aria-hidden={parked ? true : undefined}
      inert={parked}
      onClick={
        usable
          ? (e) => {
              if (isBareClick(e.target)) onUse(item);
            }
          : undefined
      }
      className={vx(
        SLOT,
        SLOT_FADE,
        "bg-black",
        width === null && SLOT_WIDTH,
        eased && SLOT_MOVE,
        active ? SLOT_ON : far ? SLOT_FAR : SLOT_SIDE,
        parked && "pointer-events-none",
        usable && "group/frame",
        // Пока кадр ведут пальцем, курсор — «рука» сцены.
        usable && eased && "cursor-pointer",
      )}
      style={pose}
    >
      <LazyClip
        src={item.video}
        poster={item.poster}
        mode="active"
        active={playing}
        alt=""
        className="absolute inset-0"
        rounded="rounded-2xl"
        fit={upright ? "contain" : "cover"}
      />
      <span
        aria-hidden
        className={vx("pointer-events-none absolute inset-0 bg-black", eased && DIM_MOVE)}
        style={{ opacity: look.dim }}
      />
      {/* Кромка — «чернилами» темы: на светлой сцене она отделяет светлый кадр от «бумаги». */}
      <span aria-hidden className="pointer-events-none absolute inset-0 rounded-2xl border border-vs-ink/10" />
      <span
        aria-hidden
        className={vx(FOG, d < 0 && "[--vs-fog-to:left]", eased && DIM_MOVE)}
        style={{ opacity: paperFog(d) }}
      />
      <ReelCaption item={item} name={name} shown={active} onUse={onUse} />
      {!active && (
        // Листать с клавиатуры — стрелками; сосед-кнопка нужен мыши и пальцу.
        <button
          type="button"
          tabIndex={-1}
          aria-label={pickLabel}
          onClick={() => onPick(Math.round(d))}
          className="absolute inset-0 cursor-pointer rounded-2xl transition-colors hover:bg-white/[0.06]"
        />
      )}
    </div>
  );
});

function ReelStage({ items, names, loading, onUse }: ReelLayoutProps) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const reveal = useReveal<HTMLDivElement>();
  const { frame: fitFrame, width, column } = useReelFit<HTMLDivElement>();
  const { track, index, move, jump } = useReelTrack(items);
  const region = useRef<HTMLDivElement>(null);
  const stage = useRef<HTMLDivElement>(null);
  const pause = useReelPause(region);
  const auto = useReelAuto();
  const playingPos = useSettled(track.pos, HANDOVER_MS);

  /** На какую долю шага кадры ушли за пальцем. */
  const [shift, setShift] = useState(0);
  const [dragging, setDragging] = useState(false);
  /** Карусель уже листали — сама или рукой. До этого все кадры на сцене из первой партии. */
  const [moved, setMoved] = useState(false);
  /** Фокус в ряду названий: там новый кадр называет сам чип, на который фокус переходит. */
  const [railFocus, setRailFocus] = useState(false);
  const gesture = useRef<Gesture | null>(null);
  const swallowClick = useRef(false);

  const count = items.length;
  const loop = isLoop(count);
  const step = stepPx(width ?? 0);
  const canPrev = loop || track.pos > 0;
  const canNext = loop || track.pos < count - 1;
  const current = count > 0 ? items[index] : null;
  const studio = isStudioReel(items);

  // Где дальним кадрам светлой сцены уйти в «бумагу» — зависит только от ширины кадра и колонки.
  const fog = useMemo(() => {
    if (width === null) return undefined;
    const band = fogBand(width, column);
    return { "--vs-fog-a": `${band.from}%`, "--vs-fog-b": `${band.to}%` } as CSSProperties;
  }, [width, column]);

  // Подпись и кнопка прежнего активного кадра сейчас станут недоступны. Если
  // фокус стоял на них, он пропал бы вместе с ними — и стрелки клавиатуры
  // перестали бы листать. Забираем его на саму карусель.
  const keepFocus = useCallback(() => {
    if (stage.current?.contains(document.activeElement)) region.current?.focus({ preventScroll: true });
  }, []);

  const go = useCallback(
    (steps: number) => {
      if (!steps) return;
      keepFocus();
      setMoved(true);
      move(steps);
    },
    [keepFocus, move],
  );
  const select = useCallback(
    (i: number) => {
      keepFocus();
      setMoved(true);
      jump(i);
    },
    [keepFocus, jump],
  );
  const autoNext = useCallback(() => {
    setMoved(true);
    move(1, true);
  }, [move]);

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.defaultPrevented || e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return;
    // Enter на самой карусели — то же, что золотая кнопка активного кадра. На кнопках внутри
    // (стрелки, названия, «Смотреть») Enter нажимает их самих — туда не вмешиваемся.
    if (e.key === "Enter") {
      if (e.repeat || e.target !== region.current || !current || current.source !== "vstudio") return;
      e.preventDefault();
      onUse(current);
      return;
    }
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    e.preventDefault();
    go(e.key === "ArrowLeft" ? -1 : 1);
  };

  const onPointerDown = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (count < 2 || step <= 0 || !e.isPrimary || (e.pointerType === "mouse" && e.button !== 0)) return;
    gesture.current = { id: e.pointerId, x: e.clientX, y: e.clientY, live: false };
  };

  const onPointerMove = (e: ReactPointerEvent<HTMLDivElement>) => {
    const g = gesture.current;
    if (!g || g.id !== e.pointerId) return;
    const dx = e.clientX - g.x;
    const dy = e.clientY - g.y;
    if (!g.live) {
      // Кнопку мыши отпустили за пределами сцены — жеста больше нет.
      if (e.pointerType === "mouse" && (e.buttons & 1) === 0) {
        gesture.current = null;
        return;
      }
      if (Math.abs(dx) < INTENT_PX && Math.abs(dy) < INTENT_PX) return;
      // Ведут вверх или вниз — это прокрутка страницы, карусель не вмешивается.
      if (Math.abs(dx) <= Math.abs(dy)) {
        gesture.current = null;
        return;
      }
      g.live = true;
      try {
        e.currentTarget.setPointerCapture(e.pointerId);
      } catch {
        // указатель уже отпущен — доведём жест по обычным событиям
      }
      setDragging(true);
    }
    setShift(dragShift(dx, step, track.pos, count));
  };

  const endGesture = (e: ReactPointerEvent<HTMLDivElement>) => {
    const g = gesture.current;
    if (!g || g.id !== e.pointerId) return;
    gesture.current = null;
    if (!g.live) return;
    // После перетаскивания браузер пришлёт click тому, на чём отпустили кнопку
    // мыши: соседу, кнопке кадра или самому кадру. Этот click — не нажатие, его гасим.
    swallowClick.current = true;
    setTimeout(() => {
      swallowClick.current = false;
    }, 0);
    setDragging(false);
    setShift(0);
    if (e.type === "pointerup") go(dragSteps(e.clientX - g.x, step));
  };

  const onClickCapture = (e: ReactMouseEvent<HTMLDivElement>) => {
    if (!swallowClick.current) return;
    swallowClick.current = false;
    e.preventDefault();
    e.stopPropagation();
  };

  const frame = (i: number) =>
    t("home.reel.frame", { defaultValue: "Кадр {{n}} из {{total}}", n: i + 1, total: count });
  const running = auto && count > 1;
  const paused = pause.paused || dragging;

  return (
    <div ref={fitFrame} className="w-full" onKeyDown={onKeyDown} {...pause.focusHandlers}>
      <div ref={reveal} className="vs-reveal" style={REEL_ENTER}>
        <div
          ref={region}
          role="group"
          aria-roledescription={t("home.reel.carousel", { defaultValue: "карусель" })}
          aria-label={t("home.reel.label", { defaultValue: "Примеры роликов" })}
          tabIndex={count > 1 ? 0 : -1}
          className={vx(VS_SECTION, "group/reel relative focus-visible:outline-none")}
          {...pause.hoverHandlers}
        >
          {count > 1 && (
            <button
              type="button"
              aria-label={t("home.reel.prev", { defaultValue: "Предыдущий кадр" })}
              aria-disabled={canPrev ? undefined : true}
              onClick={() => canPrev && go(-1)}
              className={vx(ARROW, "left-4 sm:left-6")}
            >
              <FiChevronLeft aria-hidden className="text-xl" />
            </button>
          )}

          <div
            ref={stage}
            className={vx(
              "vs-stage grid touch-pan-y touch-pinch-zoom select-none place-items-center py-6",
              count > 1 && (dragging ? "cursor-grabbing" : "cursor-grab"),
            )}
            style={fog}
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={endGesture}
            onPointerCancel={endGesture}
            onClickCapture={onClickCapture}
          >
            {count === 0
              ? loading &&
                SKELETON.map((d) => {
                  const look = slotLook(d);
                  return (
                    <div
                      key={d}
                      aria-hidden
                      className={vx(SLOT, "vs-film", width === null && SLOT_WIDTH, d !== 0 && "opacity-60")}
                      style={{ width: width ?? undefined, transform: look.transform, zIndex: look.zIndex }}
                    />
                  );
                })
              : slotsAround(track.pos, shift, count).map(({ v, index: i, d }) => {
                  const item = items[i];
                  const name = names[i] ?? "";
                  return (
                    <Slot
                      key={`${v}:${item.id}`}
                      item={item}
                      name={name}
                      d={d}
                      active={v === track.pos}
                      playing={v === playingPos}
                      width={width}
                      eased={!dragging}
                      label={frame(i)}
                      pickLabel={
                        name ? t("home.reel.show", { defaultValue: "Показать: {{title}}", title: name }) : frame(i)
                      }
                      late={moved}
                      onUse={onUse}
                      onPick={go}
                    />
                  );
                })}
          </div>

          {count > 1 && (
            <button
              type="button"
              aria-label={t("home.reel.next", { defaultValue: "Следующий кадр" })}
              aria-disabled={canNext ? undefined : true}
              onClick={() => canNext && go(1)}
              className={vx(ARROW, "right-4 sm:right-6")}
            >
              <FiChevronRight aria-hidden className="text-xl" />
            </button>
          )}
        </div>

        {/* Ряд заходит на нижнее поле сцены (там только тень кадра): название стоит под самым кадром.
            relative — чтобы на этой полосе нажатие доставалось ему, а не сцене под ним. */}
        <div
          className={FOOT}
          onFocus={studio ? () => setRailFocus(true) : undefined}
          onBlur={
            studio
              ? (e) => {
                  if (!e.currentTarget.contains(e.relatedTarget)) setRailFocus(false);
                }
              : undefined
          }
        >
          {count > 1 &&
            (studio ? (
              <ScenarioRail
                names={names}
                active={index}
                progressMs={running ? REEL_INTERVAL_MS : null}
                paused={paused}
                onProgressEnd={autoNext}
                onSelect={select}
              />
            ) : (
              <Segments
                count={count}
                active={index}
                progressMs={running ? REEL_INTERVAL_MS : null}
                paused={paused}
                onProgressEnd={autoNext}
                onSelect={select}
                label={frame}
                className="h-full px-4"
              />
            ))}
        </div>

        {/* Пока карусель листается сама, скринридер молчит; когда её листает человек — называет кадр.
            Из ряда названий кадр называет чип, на который переходит фокус, — второй раз то же не читаем.
            Сегменты мультстудии фокус за кадром не ведут, там называть кадр по-прежнему нам. */}
        {current && (
          <p className="sr-only" aria-live={(running && !paused) || (studio && railFocus) ? "off" : "polite"} aria-atomic>
            {names[index] ? `${frame(index)}: ${names[index]}` : frame(index)}
          </p>
        )}
      </div>
    </div>
  );
}

export default memo(ReelStage);
