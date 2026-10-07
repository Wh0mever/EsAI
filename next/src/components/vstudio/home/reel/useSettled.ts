"use client";

import { useEffect, useState } from "react";

/**
 * Значение, которое «устоялось»: отдаёт новое, только когда оно не менялось ms.
 *
 * Сцена по нему решает, какому кадру играть ролик. Пока карусель листают, ролик
 * остаётся у прежнего кадра: он не обрывается на постер в первый же миг, пока
 * кадр ещё в центре, а быстрый проход по нескольким кадрам не начинает и не
 * бросает загрузку ролика у каждого из них. Ролик при этом по-прежнему один.
 */
export function useSettled<T>(value: T, ms: number): T {
  const [settled, setSettled] = useState(value);

  useEffect(() => {
    if (Object.is(value, settled)) return;
    const timer = setTimeout(() => setSettled(value), ms);
    return () => clearTimeout(timer);
  }, [value, settled, ms]);

  return settled;
}
