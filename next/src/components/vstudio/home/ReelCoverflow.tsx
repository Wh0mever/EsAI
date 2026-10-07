"use client";

import { memo } from "react";
import { useVsBreakpoint } from "../VStudioShell";
import ReelStage from "./reel/ReelStage";
import ReelStrip from "./reel/ReelStrip";
import type { ReelItem } from "./useShowreel";

export type ReelCoverflowProps = {
  /** Кадры карусели: работы видеостудии, затем выбор редакции мультстудии (до 12). */
  items: ReelItem[];
  /** Витрина ещё в пути — заглушки той же формы. */
  loading: boolean;
  /**
   * Нажата кнопка активного кадра. Что это значит («Снять похожее», «Выбрать
   * эту модель», переход в мультстудию), решает StudioHome; для сцены
   * мультстудии сам переход делает ссылка на item.href.
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
 * Края секции обрезают только по горизонтали: дальние кадры сцены уходят за
 * колонку, а тени под кадрами должны остаться целыми. Свой слой (isolate) —
 * чтобы порядок кадров и стрелок сцены не спорил с затуханием над панелью запроса.
 */
function ReelCoverflow({ items, loading, onUse }: ReelCoverflowProps) {
  const wide = useVsBreakpoint() !== "mobile";
  if (!loading && items.length === 0) return null;

  // Заглушки — только пока кадров нет совсем: при обновлении витрины прежние остаются на месте.
  const waiting = loading && items.length === 0;
  return (
    <section className="isolate mt-4 w-full overflow-x-clip sm:mt-6" aria-busy={waiting || undefined}>
      {wide ? (
        <ReelStage items={items} loading={waiting} onUse={onUse} />
      ) : (
        <ReelStrip items={items} loading={waiting} onUse={onUse} />
      )}
    </section>
  );
}

export default memo(ReelCoverflow);
