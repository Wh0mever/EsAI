"use client";

import { useCallback, useEffect, useRef } from "react";
import { callDockOrFocus } from "./dock";

/**
 * Показать слоты кадров панели запроса — кадром позже, а не сразу. Нажатие
 * могло только что сменить модель, и слоты появятся, когда панель запроса
 * перерисуется с новой. У модели без кадров панель сама ставит курсор в поле
 * запроса.
 *
 * Новое нажатие заменяет прежний вызов; закрытый первый экран его отменяет.
 */
export function useFramesFocus(): () => void {
  const frame = useRef(0);
  useEffect(() => () => cancelAnimationFrame(frame.current), []);
  return useCallback(() => {
    cancelAnimationFrame(frame.current);
    frame.current = requestAnimationFrame(() => callDockOrFocus("focusFrames"));
  }, []);
}
