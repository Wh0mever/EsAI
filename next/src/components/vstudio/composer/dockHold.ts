"use client";

/**
 * Видеостудия, панель запроса: «сейчас поле сворачивать нельзя».
 *
 * Окошки панели (чипы параметров, меню материала, раскладка цены, выбор «@»)
 * рисуются порталом и открыты каждое у себя: общего флага «что-то открыто»
 * в сторе нет. Пока любое из них на экране или открыт выбор файла, поле запроса
 * не должно сворачиваться — панель под окошком поехала бы. Поэтому каждое
 * окошко берёт здесь «удержание» на время, пока открыто, а композер
 * (usePromptFold) спрашивает, держит ли кто-нибудь.
 *
 * Модуль без React-состояния, как composerBus: одна панель на вкладку.
 */
import { useEffect } from "react";

let holds = 0;
const listeners = new Set<() => void>();

function notify() {
  for (const l of [...listeners]) l();
}

/** Взять удержание; возвращает функцию, которая его снимает (повторный вызов ничего не делает). */
export function holdDock(): () => void {
  let held = true;
  holds += 1;
  notify();
  return () => {
    if (!held) return;
    held = false;
    holds = Math.max(0, holds - 1);
    notify();
  };
}

export function dockHeld(): boolean {
  return holds > 0;
}

/** Сообщать об изменениях: удержание сняли — можно снова проверить, не пора ли свернуть. */
export function subscribeDockHold(cb: () => void): () => void {
  listeners.add(cb);
  return () => listeners.delete(cb);
}

/** Удержание на время, пока окошко открыто. */
export function useDockHold(open: boolean): void {
  useEffect(() => {
    if (!open) return;
    return holdDock();
  }, [open]);
}

/**
 * Перед input.click(): системное окно выбора файла открыто, а события об этом
 * у браузера нет. Закрытие узнаём по возврату фокуса окну; если окно фокус не
 * теряло (выбор файла на части телефонов — лист поверх страницы) — по первому
 * нажатию на странице: раз до неё достали, лист уже закрыт.
 */
export function holdDockForFileDialog(): void {
  if (typeof window === "undefined") return;
  const release = holdDock();
  const done = () => {
    window.removeEventListener("focus", done);
    window.removeEventListener("pointerdown", done, true);
    release();
  };
  window.addEventListener("focus", done);
  window.addEventListener("pointerdown", done, true);
}
