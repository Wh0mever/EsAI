"use client";

import { useEffect, useRef } from "react";
import type { Dispatch } from "react";
import { activeTakes } from "@/lib/vstudio/api";
import type { ActiveTake, VsAction } from "@/lib/vstudio/types";

/**
 * «Восстановили N генераций» (§9.4).
 *
 * Человек может закрыть вкладку посреди съёмки: деньги в резерве, дубль
 * снимается на сервере. При следующем открытии студии один раз спрашиваем
 * GET takes/active/ — открытые дубли по всем проектам — и кладём их в стор:
 * их подхватит опрос ленты (useTakePolling) и покажет «готово», когда
 * дойдут. Если что-то нашлось, контейнер показывает всплывающее сообщение.
 *
 * Запрос уходит один раз за жизнь страницы (и в StrictMode тоже), а ответ
 * применяется даже после размонтирования: dispatch тогда просто ничего не
 * делает, а потерять найденные дубли хуже, чем лишний вызов.
 */
export function useRestoreActive({
  enabled,
  dispatch,
  onRestored,
}: {
  /** Вошёл, студия доступна (mode/available) — только тогда есть что восстанавливать. */
  enabled: boolean;
  dispatch: Dispatch<VsAction>;
  /** Нашлись открытые дубли (по всем проектам). */
  onRestored?: (items: ActiveTake[]) => void;
}): void {
  const started = useRef(false);
  const onRestoredRef = useRef(onRestored);
  useEffect(() => {
    onRestoredRef.current = onRestored;
  }, [onRestored]);

  useEffect(() => {
    if (!enabled || started.current) return;
    started.current = true;
    void (async () => {
      const res = await activeTakes();
      if (!res.ok) {
        // Сеть мигнула — попробуем при следующем включении (например, после входа).
        started.current = false;
        return;
      }
      const items = Array.isArray(res.data.items) ? res.data.items : [];
      if (!items.length) return;
      dispatch({ type: "takes/upsert", takes: items });
      onRestoredRef.current?.(items);
    })();
  }, [enabled, dispatch]);
}
