"use client";

import { memo, useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { FiChevronDown } from "react-icons/fi";
import { VS_BTN_GHOST, VS_SECTION, VS_SECTION_GAP, vx } from "../ui/skin";
import { useCanHover } from "../ui/useAutoplayAllowed";
import { useReveal } from "../ui/useReveal";
import type { ReelItem } from "./showreelData";
import { HOME_CELLS, HOME_CELL_IN, staggerStyle } from "./tools/cardSkin";
import SectionHead from "./tools/SectionHead";
import TrendCard from "./trends/TrendCard";
import { trendAction, trendSeconds, trendText, trendsLimit } from "./trends/trendsLogic";

export type TrendsProps = {
  /** Ролики, которые владелец поставил в «Тренды» (showreelData.trendItems), в его порядке. */
  items: ReelItem[];
  /** Нажата карточка; что это значит («Снять похожее»), решает StudioHome — как для кадра карусели. */
  onUse: (item: ReelItem) => void;
};

/**
 * «Тренды»: сетка роликов, которые владелец отобрал в админке, — на месте
 * прежней галереи «Сделано в EsAI», под инструментами режиссёра. Сетка
 * показывает порциями: восемь карточек, остальные — по «Показать ещё».
 *
 * Пока витрина в пути, секции нет вовсе, без заглушек: роликов в «Трендах»
 * может и не оказаться, а заглушка, которая потом исчезает, сдвинула бы всё
 * под собой. Секция лежит ниже первого экрана — к тому времени, как до неё
 * долистают, ответ уже здесь.
 */
function Trends({ items, onUse }: TrendsProps) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const reveal = useReveal<HTMLElement>();
  const canHover = useCanHover();
  const headId = useId();
  const [extra, setExtra] = useState(0);
  const gridRef = useRef<HTMLUListElement>(null);
  // С какой карточки начинается порция, открытая «Показать ещё»: туда уйдёт фокус.
  const focusFrom = useRef<number | null>(null);

  useEffect(() => {
    const from = focusFrom.current;
    if (from === null) return;
    focusFrom.current = null;
    // Новые карточки стоят в разметке перед кнопкой: без этого Tab с неё пролетел бы мимо них.
    // Страницу не двигаем — первая из новых появляется там, где была кнопка.
    gridRef.current?.querySelectorAll<HTMLElement>("[data-vs-card]")[from]?.focus({ preventScroll: true });
  }, [extra]);

  if (items.length === 0) return null;

  const shown = items.slice(0, trendsLimit(extra));
  const more = items.length > shown.length;

  const actions = {
    like: t("home.reel.like", { defaultValue: "Снять похожее" }),
    model: t("home.reel.model", { defaultValue: "Выбрать эту модель" }),
  };
  const untitled = t("home.trends.untitled", { defaultValue: "Ролик из видеостудии" });

  const showMore = () => {
    focusFrom.current = shown.length;
    setExtra((n) => n + 1);
  };

  return (
    <section ref={reveal} aria-labelledby={headId} className={vx(VS_SECTION, VS_SECTION_GAP, "vs-reveal", HOME_CELLS)}>
      <SectionHead
        id={headId}
        title={t("home.trends.title", { defaultValue: "Тренды" })}
        // Что делает нажатие, говорит сама карточка: без открытого запроса она
        // только выбирает модель, и «снять похожее» здесь обещало бы лишнее.
        sub={t("home.trends.sub", { defaultValue: "Ролики, снятые в видеостудии EsAI" })}
      />
      <ul ref={gridRef} className="mt-5 grid grid-cols-2 gap-x-3 gap-y-6 sm:mt-6 sm:gap-x-4 lg:grid-cols-4">
        {shown.map((item, index) => {
          const text = trendText(item);
          const seconds = trendSeconds(item);
          return (
            <li key={item.id} className={vx("min-w-0", HOME_CELL_IN)} style={staggerStyle(index)}>
              <TrendCard
                item={item}
                title={text.title || untitled}
                subtitle={text.subtitle}
                seconds={seconds > 0 ? t("home.reel.seconds", { defaultValue: "{{n}} с", n: seconds }) : ""}
                action={actions[trendAction(item)]}
                hover={canHover}
                onUse={onUse}
              />
            </li>
          );
        })}
      </ul>

      {more && (
        <div className="mt-8 flex flex-col items-center gap-2.5">
          <button type="button" onClick={showMore} className={VS_BTN_GHOST}>
            {t("home.trends.more", { defaultValue: "Показать ещё" })}
            <FiChevronDown aria-hidden className="text-base" />
          </button>
          <p aria-live="polite" className="text-[11px] tabular-nums text-muted">
            {t("home.trends.shown", {
              defaultValue: "Показано {{shown}} из {{total}}",
              shown: shown.length,
              total: items.length,
            })}
          </p>
        </div>
      )}
    </section>
  );
}

export default memo(Trends);
