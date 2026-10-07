"use client";

import { useEffect, useMemo, useState, useSyncExternalStore } from "react";
import type { FocusEvent, RefObject } from "react";
import { PLAY_BLOCKED, playState, subscribePlay } from "../../ui/playBudget";
import { useAutoplayAllowed } from "../../ui/useAutoplayAllowed";

/**
 * Когда карусель не листается сама (§2.2).
 *
 * Пауза — пока человек занят ею или не видит её: курсор или палец на сцене,
 * фокус с клавиатуры внутри, вкладка скрыта, на экране меньше половины
 * карусели. Часы у карусели одни — заполнение активного сегмента (Segments);
 * сюда приходит только ответ «стоять или идти».
 */

/** Доля карусели на экране, ниже которой она не листается. */
const HALF = 0.5;

function subscribeTab(onChange: () => void): () => void {
  document.addEventListener("visibilitychange", onChange);
  return () => document.removeEventListener("visibilitychange", onChange);
}
const tabHidden = () => document.hidden;
const never = () => false;

/** Фокус пришёл с клавиатуры. Фокус от клика остаётся на кнопке и после ухода курсора — такой паузу не держит. */
function fromKeyboard(el: Element): boolean {
  try {
    return el.matches(":focus-visible");
  } catch {
    // старый браузер без :focus-visible — считаем любой фокус клавиатурным
    return true;
  }
}

export function useReelPause(target: RefObject<HTMLElement | null>) {
  const [hover, setHover] = useState(false);
  const [focus, setFocus] = useState(false);
  // Без IntersectionObserver считаем карусель видимой: лучше листать, чем стоять вечно.
  const [visible, setVisible] = useState(() => typeof IntersectionObserver === "undefined");
  const hidden = useSyncExternalStore(subscribeTab, tabHidden, never);

  useEffect(() => {
    const el = target.current;
    if (!el || typeof IntersectionObserver === "undefined") return;
    const io = new IntersectionObserver(
      (entries) => {
        const last = entries[entries.length - 1];
        setVisible(last.isIntersecting && last.intersectionRatio >= HALF);
      },
      { threshold: [0, HALF] },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [target]);

  /** На сцену: курсор над ней или палец на ней. */
  const hoverHandlers = useMemo(
    () => ({
      onPointerEnter: () => setHover(true),
      onPointerLeave: () => setHover(false),
    }),
    [],
  );
  /** На весь блок карусели, вместе с сегментами. */
  const focusHandlers = useMemo(
    () => ({
      onFocus: (e: FocusEvent<HTMLElement>) => {
        if (fromKeyboard(e.target)) setFocus(true);
      },
      onBlur: (e: FocusEvent<HTMLElement>) => {
        if (!e.currentTarget.contains(e.relatedTarget)) setFocus(false);
      },
    }),
    [],
  );

  return { paused: hover || focus || !visible || hidden, hoverHandlers, focusHandlers };
}

const autoplayBlocked = () => (playState("") & PLAY_BLOCKED) !== 0;

/**
 * Листается ли карусель сама. Нет — если человек просил меньше движения,
 * бережёт трафик или браузер запретил автозапуск роликов. Во всех трёх случаях
 * на кадре кнопка «Смотреть», и ролик, запущенный ею, карусель не оборвёт:
 * сама она в этих режимах не листает вовсе.
 */
export function useReelAuto(): boolean {
  const allowed = useAutoplayAllowed();
  const blocked = useSyncExternalStore(subscribePlay, autoplayBlocked, never);
  return allowed && !blocked;
}
