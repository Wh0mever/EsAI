"use client";

import { useEffect, useLayoutEffect } from "react";
import { applyTheme, getStoredPreference, getSystemTheme } from "@/lib/theme";

/**
 * Палитра студии на уровне <html>.
 *
 * Обёртка в app/video-studio/layout.tsx красит саму страницу, но шторки, окна
 * и всплывающие меню рисуются порталом в <body> — мимо обёртки. Поэтому, пока
 * студия открыта, <html> получает класс vs-root, а при уходе со страницы
 * класс снимается.
 *
 * Тему (data-theme) студия не выбирает: она живёт в той же теме, что и сайт, —
 * светлые и тёмные значения палитры описаны в app/globals.css, блок
 * «Видеостудия». Единственное, что делаем сами, — идём за системной темой,
 * пока на сайте стоит «как в системе» (см. эффект ниже).
 */

// Счётчик на случай двух экземпляров сразу: класс снимает последний.
let mounted = 0;
let hadRoot = false;

/**
 * Снять палитру без «проявления». У body переход фона и цвета текста на
 * четверть секунды (globals.css): страница, на которую ушли из студии, иначе
 * перетекала бы из цветов студии в цвета сайта. Переход возвращаем через два
 * кадра: первый requestAnimationFrame срабатывает ещё до того, как браузер
 * применил новые цвета, — вернуть в нём значило бы всё-таки запустить переход.
 */
function withoutBodyFade(apply: () => void) {
  const body = document.body;
  body.style.transition = "none";
  apply();
  requestAnimationFrame(() => requestAnimationFrame(() => body.style.removeProperty("transition")));
}

export default function VsThemeScope() {
  // Layout-эффект: палитру надо снять внутри того же обновления, которое
  // ставит следующую страницу, — до первого её кадра, а не после него.
  useLayoutEffect(() => {
    const root = document.documentElement;
    mounted += 1;
    if (mounted === 1) {
      hadRoot = root.classList.contains("vs-root");
      root.classList.add("vs-root");
    }
    return () => {
      mounted -= 1;
      if (mounted > 0) return;
      if (!hadRoot) withoutBodyFade(() => root.classList.remove("vs-root"));
    };
  }, []);

  // Смена системной темы (телефон вечером уходит в тёмную). На сайте за ней
  // следит хук useTheme, а в студии он есть только у кнопки темы: на телефоне
  // она лежит в закрытой шторке, на экранах загрузки и ошибки её нет вовсе —
  // студия оставалась бы в старой теме до перезагрузки. Сверяемся и при входе:
  // со страницы сайта без такого слушателя можно прийти уже с устаревшей темой.
  useEffect(() => {
    const sync = () => {
      if (getStoredPreference() === "system") applyTheme(getSystemTheme());
    };
    sync();
    if (!window.matchMedia) return;
    const mq = window.matchMedia("(prefers-color-scheme: light)");
    mq.addEventListener?.("change", sync);
    return () => mq.removeEventListener?.("change", sync);
  }, []);

  return null;
}
