"use client";

import { useCallback, useMemo, useState } from "react";
import type { ReelItem } from "../showreelData";
import { activeIndex, jumpTrack, moveTrack, syncTrack, type Track } from "./reelMath";

/**
 * Какой кадр карусели сейчас в центре.
 *
 * Всё, что видно на сцене, считается из одного числа — позиции. Поэтому
 * быстрые нажатия не могут «разойтись» с картинкой: каждое просто двигает
 * число, а кадры едут к новым местам с того, где их застали.
 *
 * Список кадров может смениться, пока карусель на экране (витрина обновилась).
 * Позицию под новый список считаем прямо при отрисовке, а запоминаем при
 * следующем нажатии — так не нужен эффект, который догонял бы пропсы.
 */
export function useReelTrack(items: readonly ReelItem[]) {
  const ids = useMemo(() => items.map((item) => item.id), [items]);
  const [stored, setStored] = useState<Track>(() => ({ ids, pos: 0 }));
  const track = useMemo(() => syncTrack(stored, ids), [stored, ids]);

  /** Сдвинуться на steps мест; auto — карусель листает сама. */
  const move = useCallback(
    (steps: number, auto = false) => setStored((cur) => moveTrack(syncTrack(cur, ids), steps, auto)),
    [ids],
  );
  /** Перейти к кадру по номеру в списке. */
  const jump = useCallback((index: number) => setStored((cur) => jumpTrack(syncTrack(cur, ids), index)), [ids]);

  return { track, index: activeIndex(track), move, jump };
}
