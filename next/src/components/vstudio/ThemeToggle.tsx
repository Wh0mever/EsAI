"use client";

import { useSyncExternalStore } from "react";
import { useTranslation } from "react-i18next";
import { FiMoon, FiSun } from "react-icons/fi";
import { useTheme } from "@/hooks/useTheme";
import { getSystemTheme } from "@/lib/theme";
import { VS_ICON_BTN, vx } from "./ui/skin";

/**
 * Переключатель темы в студии: одно нажатие — светлая ↔ тёмная.
 *
 * Выбор запоминает и применяет хук сайта useTheme (localStorage «esai-theme»,
 * data-theme на <html>). А какая тема стоит сейчас, читаем с <html>, не из
 * состояния хука: переключателей на экране бывает два (колонка значков и та же
 * история, развёрнутая шторкой), и у каждого хук свой. Второй не узнал бы, что
 * тему уже сменили: показывал бы старый значок, а его первое нажатие ничего бы
 * не меняло.
 *
 * Положений у кнопки два, а у сайта три — есть ещё «как в системе». Поэтому
 * тему, совпавшую с системной, не закрепляем, а возвращаем сайт к «как в
 * системе»: иначе человек, который заглянул в светлую тему и вернулся, навсегда
 * терял бы смену темы по расписанию телефона — на всём сайте, не только здесь.
 * За сменой системной темы следит VsThemeScope: он на экране всё время, а эта
 * кнопка на телефоне живёт в закрытой шторке.
 */

type Theme = "light" | "dark";

function subscribeTheme(onChange: () => void): () => void {
  if (typeof MutationObserver === "undefined") return () => {};
  const observer = new MutationObserver(onChange);
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  return () => observer.disconnect();
}

function readTheme(): Theme {
  return document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark";
}

// Сервер темы не знает (её ставит скрипт в <head>) — до mounted стоит заглушка.
const serverTheme = (): Theme => "dark";

export type ThemeToggleProps = {
  /** compact — колонка значков 64 px: значок крупнее, как у её соседей. */
  variant?: "full" | "compact";
};

export default function ThemeToggle({ variant = "full" }: ThemeToggleProps) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const { mounted, setPreference } = useTheme();
  const theme = useSyncExternalStore(subscribeTheme, readTheme, serverTheme);

  // Пустой кружок того же размера: соседние кнопки не сдвигаются, а разметка сервера и браузера совпадает.
  if (!mounted) return <span className={vx(VS_ICON_BTN, "pointer-events-none")} aria-hidden="true" />;

  const dark = theme === "dark";
  // Подпись и значок говорят, что сделает нажатие: в тёмной теме — солнце и «Светлая тема».
  const label = dark
    ? t("nav.themeLight", { defaultValue: "Светлая тема" })
    : t("nav.themeDark", { defaultValue: "Тёмная тема" });
  const Icon = dark ? FiSun : FiMoon;

  const flip = () => {
    const next: Theme = dark ? "light" : "dark";
    setPreference(next === getSystemTheme() ? "system" : next);
  };

  return (
    <button
      type="button"
      onClick={flip}
      className={VS_ICON_BTN}
      aria-label={label}
      title={label}
    >
      <Icon className={variant === "compact" ? "text-lg" : undefined} aria-hidden="true" />
    </button>
  );
}
