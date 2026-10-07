"use client";

import { useLayoutEffect } from "react";

/**
 * «Тёмный остров» студии на уровне <html>.
 *
 * Обёртка в app/video-studio/layout.tsx красит саму страницу, но шторки, окна
 * и всплывающие меню рисуются порталом в <body> — мимо обёртки. Поэтому, пока
 * студия открыта, <html> получает data-theme="dark" и класс vs-root, а при
 * уходе со страницы возвращается то, что стояло.
 *
 * Сайт может сменить тему и при открытой студии (системная тема ночью,
 * useTheme в соседнем компоненте): такую смену запоминаем как «тему сайта» и
 * сразу возвращаем тёмную — иначе меню поверх видео стало бы белым.
 */

type Saved = { theme: string | null; hadRoot: boolean; observer: MutationObserver | null };

// Счётчик на случай двух экземпляров сразу: тему сайта запоминает первый,
// возвращает последний — иначе второй запомнил бы уже «нашу» тёмную.
let mounted = 0;
let saved: Saved | null = null;

function forceDark(root: HTMLElement, observer: MutationObserver | null) {
  if (root.getAttribute("data-theme") !== "dark") root.setAttribute("data-theme", "dark");
  root.classList.add("dark", "vs-root");
  // Собственные правки наблюдателю не нужны: по ним он принял бы тёмную тему за выбор сайта.
  observer?.takeRecords();
}

/**
 * Вернуть тему сайта без «проявления». У body переход фона и цвета текста на
 * четверть секунды (globals.css): страница, на которую ушли из студии, иначе
 * выцветала бы из тёмной в светлую, со светлым текстом на светлых карточках.
 * Переход возвращаем через два кадра: первый requestAnimationFrame срабатывает
 * ещё до того, как браузер применил новые цвета, — вернуть в нём значило бы
 * всё-таки запустить переход.
 */
function withoutBodyFade(apply: () => void) {
  const body = document.body;
  body.style.transition = "none";
  apply();
  requestAnimationFrame(() => requestAnimationFrame(() => body.style.removeProperty("transition")));
}

export default function VsThemeScope() {
  // Layout-эффект: тему сайта надо вернуть внутри того же обновления, которое
  // ставит следующую страницу, — до первого её кадра, а не после него.
  useLayoutEffect(() => {
    const root = document.documentElement;
    mounted += 1;
    if (mounted === 1) {
      const state: Saved = {
        theme: root.getAttribute("data-theme"),
        hadRoot: root.classList.contains("vs-root"),
        observer: null,
      };
      if (typeof MutationObserver !== "undefined") {
        state.observer = new MutationObserver(() => {
          state.theme = root.getAttribute("data-theme");
          forceDark(root, state.observer);
        });
        state.observer.observe(root, { attributes: true, attributeFilter: ["data-theme"] });
      }
      saved = state;
      forceDark(root, state.observer);
    }
    return () => {
      mounted -= 1;
      if (mounted > 0 || !saved) return;
      const { theme, hadRoot, observer } = saved;
      saved = null;
      observer?.disconnect();
      withoutBodyFade(() => {
        if (!hadRoot) root.classList.remove("vs-root");
        if (theme === null) root.removeAttribute("data-theme");
        else root.setAttribute("data-theme", theme);
        // Класс dark сайт держит в паре с data-theme (lib/theme.ts applyTheme).
        root.classList.toggle("dark", theme !== "light");
      });
    };
  }, []);

  return null;
}
