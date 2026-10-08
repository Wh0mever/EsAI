"use client";

import { memo, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useVsBreakpoint } from "../VStudioShell";
import { reelNames } from "./reel/reelMath";
import ReelStage from "./reel/ReelStage";
import ReelStrip from "./reel/ReelStrip";
import { scenarioDefault, scenarioLabel } from "./scenarios";
import type { ReelItem } from "./useShowreel";

export type ReelCoverflowProps = {
  /**
   * Кадры карусели (до 12), одного источника: либо ролики видеостудии — по
   * одному на сценарий, либо, пока их мало, сцены мультстудии (showreelData).
   */
  items: ReelItem[];
  /** Витрина ещё в пути — заглушки той же формы. */
  loading: boolean;
  /**
   * Пример выбран: нажата кнопка активного кадра, сам кадр или Enter на
   * карусели. Что это значит («Снять похожее», «Выбрать эту модель», переход в
   * мультстудию), решает StudioHome; для сцены мультстудии сам переход делает
   * ссылка на item.href. Зовётся один раз на действие.
   */
  onUse: (item: ReelItem) => void;
};

/**
 * Карусель настоящих роликов под заголовком первого экрана (§2.2).
 *
 * От 768 px — сцена с перспективой (reel/ReelStage), на телефоне — лента с
 * прилипанием (reel/ReelStrip). Обе играют ролик только в активном кадре и
 * листаются сами раз в 7 секунд, пока человек видит карусель и не трогает её.
 * Пока витрина в пути — заглушки той же формы; если показать нечего, секции нет.
 *
 * У каждого ролика студии есть короткое имя — его сценарий («Киносцена»,
 * «Реклама товара»): оно стоит на кадре и на чипе под каруселью. Имена
 * считаются здесь, один раз на обе раскладки.
 *
 * Края секции обрезают только по горизонтали: дальние кадры сцены уходят за
 * колонку, а тени под кадрами должны остаться целыми. Свой слой (isolate) —
 * чтобы порядок кадров и стрелок сцены не спорил с затуханием над панелью запроса.
 */
function ReelCoverflow({ items, loading, onUse }: ReelCoverflowProps) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const wide = useVsBreakpoint() !== "mobile";
  const names = useMemo(() => reelNames(items, (key) => scenarioLabel(t, key), scenarioDefault), [items, t]);
  if (!loading && items.length === 0) return null;

  // Заглушки — только пока кадров нет совсем: при обновлении витрины прежние остаются на месте.
  const waiting = loading && items.length === 0;
  return (
    <section className="isolate mt-4 w-full overflow-x-clip sm:mt-6" aria-busy={waiting || undefined}>
      {wide ? (
        <ReelStage items={items} names={names} loading={waiting} onUse={onUse} />
      ) : (
        <ReelStrip items={items} names={names} loading={waiting} onUse={onUse} />
      )}
    </section>
  );
}

export default memo(ReelCoverflow);
