"use client";

import { memo, useCallback, useEffect, useRef, useState } from "react";
import type { KeyboardEvent, MouseEvent } from "react";
import { useTranslation } from "react-i18next";
import { FiChevronLeft, FiChevronRight } from "react-icons/fi";
import { SegmentFill } from "../../ui/Segments";
import { VS_FOCUS, vx } from "../../ui/skin";
import { prefersReducedMotion, useReducedMotion } from "../../ui/useAutoplayAllowed";
import { EDGE_FADE, useEdgeFade } from "../strip/useEdgeFade";
import { railArrows, railScroll } from "./reelMath";

/**
 * Ряд названий под каруселью роликов студии: у каждого ролика — свой чип
 * («Киносцена», «Реклама товара»…). Стоит на месте безымянных сегментов и
 * делает их работу: показывает, какой ролик сейчас, и по нажатию ведёт к
 * любому. Под активным чипом — та же золотая полоска, что заполняла сегмент
 * (SegmentFill): часы у карусели по-прежнему одни, и листает она по ним.
 *
 * Ряд один. Названий бывает до 48, и уже двенадцать на большинстве экранов не
 * помещаются — тогда он прокручивается вбок, а активный чип сам встаёт
 * посередине. Двигаем только сам ряд (scrollTo): scrollIntoView потянул бы за
 * собой и ленту студии. Вверх-вниз ряд не прокручивается, и страница под
 * пальцем идёт как обычно.
 *
 * Пальцем и тачпадом ряд листают вбок, а колесо обычной мыши ведёт страницу.
 * Поэтому у длинного ряда (reelMath.railArrows) на экранах от 768 px по краям
 * стоят стрелки: они листают только ряд, активный ролик остаётся на месте.
 * Стрелки — для мыши: в обход по Tab и в разметку вкладок они не входят
 * (с клавиатуры ряд листают клавиши), потому и роль tablist — у прокручиваемого
 * блока, а не у корня, где они лежат. В корне же они остаются под его паузой:
 * пока курсор на стрелке, карусель не листается и ряд назад не уводит.
 *
 * Активный чип отличается цветом и полоской, но не жирностью: иначе соседние
 * названия вздрагивали бы при каждой смене ролика.
 *
 * С клавиатуры ряд — одна остановка Tab, на активном чипе, как у вкладок
 * (tablist): стрелки листает сама карусель (её обработчик стоит выше), фокус
 * идёт за активным чипом, Home и End ведут к первому и последнему ролику.
 *
 * Пока курсор или палец на ряду, карусель не листается: иначе название уехало
 * бы из-под курсора за миг до нажатия.
 */
export type ScenarioRailProps = {
  /** Имена роликов в порядке карусели (reelMath.reelNames); пустое — чип подписан номером. */
  names: readonly string[];
  /** Номер активного ролика, с нуля. */
  active: number;
  /** За сколько миллисекунд карусель перелистнётся сама; null — сама не листается. */
  progressMs: number | null;
  /** Часы стоят: курсор над каруселью, фокус внутри, её не видно. */
  paused: boolean;
  /** Полоска активного чипа дошла до конца. */
  onProgressEnd: () => void;
  onSelect: (index: number) => void;
};

// Чип во всю высоту ряда: 44 px на телефоне, 36 px с 768 px (высоту задаёт место под каруселью).
// Кольцо фокуса — внутрь: ряд обрезает всё, что выходит за него.
const CHIP = `group/chip flex h-full shrink-0 cursor-pointer items-center rounded-lg px-2.5 focus-visible:ring-inset sm:px-3 ${VS_FOCUS}`;
// Названия сценариев короткие; длинным бывает своё название работы без сценария — его обрезаем.
const NAME = "max-w-56 truncate text-[13px] font-medium leading-5 transition-colors motion-reduce:transition-none";
const TRACK = "relative block h-0.5 w-full overflow-hidden rounded-full transition-colors motion-reduce:transition-none";
/**
 * Сколько после клавиши ждём смены активного ролика, чтобы повести за ним фокус.
 * На сцене он меняется сразу, на телефоне — когда лента доедет до кадра.
 */
const FOLLOW_MS = 1500;
/**
 * Стрелка у края ряда. Заливка непрозрачная: под стрелкой гаснет край ряда
 * (EDGE_FADE), и бледные названия не должны просвечивать сквозь неё.
 */
const ARROW =
  "absolute top-1/2 hidden size-7 -translate-y-1/2 cursor-pointer place-items-center rounded-full border border-vs-ink/12 bg-surface text-muted shadow-sm transition-colors hover:border-vs-ink/25 hover:text-foreground motion-reduce:transition-none md:grid dark:bg-surface-3";
/**
 * Нажатие на стрелку фокус не забирает. Иначе он ушёл бы на кнопку, которой
 * для скринридера нет, а сцена решила бы, что человек в ряду названий, и
 * перестала бы называть кадры сама (ReelStage, railFocus).
 */
const keepFocus = (e: MouseEvent) => e.preventDefault();

function ScenarioRail({ names, active, progressMs, paused, onProgressEnd, onSelect }: ScenarioRailProps) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const reduced = useReducedMotion();
  const { attach, fade, page } = useEdgeFade<HTMLDivElement>();
  const root = useRef<HTMLDivElement>(null);
  const row = useRef<HTMLDivElement | null>(null);
  const settled = useRef(false);
  /** До какого момента фокус идёт за активным чипом — недолго после клавиши на самом ряду. */
  const followUntil = useRef(0);
  const [hover, setHover] = useState(false);
  const [touching, setTouching] = useState(false);

  const total = names.length;
  const current = Math.min(Math.max(0, Math.floor(active)), total - 1);
  const ms = typeof progressMs === "number" && progressMs > 0 && !reduced ? progressMs : null;

  // Прокручиваемый блок нужен и здесь (вести активный чип), и useEdgeFade (гасить края).
  const mount = useCallback(
    (node: HTMLDivElement | null) => {
      row.current = node;
      const detach = attach(node);
      return () => {
        row.current = null;
        if (typeof detach === "function") detach();
      };
    },
    [attach],
  );

  useEffect(() => {
    const box = row.current;
    const chip = box?.querySelector<HTMLElement>(`[data-rail-chip="${current}"]`);
    if (!box || !chip) return;
    // В первый раз ряд встаёт на место сразу: ехать ему ещё неоткуда.
    const jump = !settled.current || prefersReducedMotion();
    settled.current = true;
    const left = chip.getBoundingClientRect().left - box.getBoundingClientRect().left + box.scrollLeft;
    box.scrollTo({
      left: railScroll(left, chip.offsetWidth, box.clientWidth, box.scrollWidth),
      behavior: jump ? "auto" : "smooth",
    });
    // Листали клавишей с самого ряда — фокус идёт за активным чипом: прежний из обхода по Tab
    // уже вышел. Когда карусель листается сама или чип нажали мышью, фокус не трогаем.
    // preventScroll — ряд мы только что повели сами.
    const byKey = performance.now() <= followUntil.current;
    followUntil.current = 0;
    const focused = document.activeElement;
    if (byKey && focused instanceof HTMLElement && focused !== chip && box.contains(focused)) {
      chip.focus({ preventScroll: true });
    }
  }, [current, names]);

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.defaultPrevented || e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return;
    const arrow = e.key === "ArrowLeft" || e.key === "ArrowRight";
    if (!arrow && e.key !== "Home" && e.key !== "End") return;
    followUntil.current = performance.now() + FOLLOW_MS;
    // Стрелки листает сама карусель — её обработчик выше по дереву получит это же нажатие.
    if (arrow) return;
    e.preventDefault();
    onSelect(e.key === "Home" ? 0 : total - 1);
  };

  if (total <= 1) return null;

  const arrows = railArrows(total, fade);

  return (
    <div
      ref={root}
      className="relative h-full w-full"
      onPointerEnter={() => setHover(true)}
      onPointerLeave={() => setHover(false)}
      onTouchStart={() => setTouching(true)}
      onTouchEnd={() => setTouching(false)}
      onTouchCancel={() => setTouching(false)}
      onKeyDown={onKeyDown}
    >
      <div
        ref={mount}
        role="tablist"
        aria-label={t("home.reel.rail", { defaultValue: "Сценарии роликов" })}
        className={vx("vs-noscroll h-full overflow-x-auto overflow-y-hidden overscroll-x-contain", EDGE_FADE[fade])}
      >
        {/* Помещается целиком — стоит по центру; не помещается — начинается от левого края. */}
        <div className="mx-auto flex h-full w-max px-1.5 sm:px-3">
          {names.map((name, i) => {
            const on = i === current;
            return (
              <button
                key={i}
                type="button"
                role="tab"
                data-rail-chip={i}
                tabIndex={on ? 0 : -1}
                aria-selected={on}
                onClick={() => onSelect(i)}
                className={CHIP}
              >
                {/* Полоска — по ширине названия, а не чипа. */}
                <span className="flex flex-col gap-1">
                  {/* Соседние названия на сцене стоят на тени активного кадра. В светлой теме «бумага» под
                      ними темнее, и приглушённому тексту не хватало контраста — там тон плотнее, как у чипов. */}
                  <span
                    className={vx(
                      NAME,
                      on ? "text-foreground" : "text-foreground/75 dark:text-muted group-hover/chip:text-foreground",
                    )}
                  >
                    {name || t("home.reel.clip", { defaultValue: "Ролик {{n}}", n: i + 1 })}
                  </span>
                  {/* Дорожка активного чипа — тоже золотая, бледнее заливки: пока часы стоят в самом
                      начале (курсор на ряду), заливки ещё нет, а чип должен читаться как выбранный. */}
                  <span
                    aria-hidden
                    className={vx(TRACK, on ? "bg-vs-accent/30" : "bg-vs-ink/10 group-hover/chip:bg-vs-ink/25")}
                  >
                    {on &&
                      (ms !== null ? (
                        // Чип может уехать за край ряда, пока тот листают рукой, — часы от этого не встают:
                        // видимость считаем по всему ряду.
                        <SegmentFill ms={ms} paused={paused || hover || touching} onEnd={onProgressEnd} anchor={root} />
                      ) : (
                        <span className="absolute inset-0 rounded-full bg-vs-accent" />
                      ))}
                  </span>
                </span>
              </button>
            );
          })}
        </div>
      </div>
      {arrows.prev && (
        <button
          type="button"
          aria-hidden
          tabIndex={-1}
          onMouseDown={keepFocus}
          onClick={() => page(-1)}
          className={vx(ARROW, "left-1")}
        >
          <FiChevronLeft />
        </button>
      )}
      {arrows.next && (
        <button
          type="button"
          aria-hidden
          tabIndex={-1}
          onMouseDown={keepFocus}
          onClick={() => page(1)}
          className={vx(ARROW, "right-1")}
        >
          <FiChevronRight />
        </button>
      )}
    </div>
  );
}

export default memo(ScenarioRail);
