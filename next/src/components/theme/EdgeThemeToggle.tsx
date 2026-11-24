"use client";

import { useEffect, useState, useSyncExternalStore } from "react";
import { usePathname } from "next/navigation";
import { useTranslation } from "react-i18next";
import { FiMoon, FiSun } from "react-icons/fi";
import { useTheme } from "@/hooks/useTheme";
import { getSystemTheme } from "@/lib/theme";

/**
 * Переключатель темы, который всегда под рукой: маленький полупрозрачный язычок
 * у правого края экрана на всех страницах (просьба клиента 24.11: «еле нашёл»
 * — до этого тема менялась только в меню чата и в колонках студий).
 *
 * Где стоит: чуть выше середины. Ниже — поле ввода чата и док склейки, а на
 * телефоне с открытой клавиатурой середина экрана — это как раз поле ввода.
 * Пока на телефоне печатают, язычок прячется. Под окнами и шторками (z 900+) —
 * они его накрывают. В Mini App (/tg) не показываем: там тема — от Telegram.
 *
 * Логика темы — как у ThemeToggle студий: тему читаем с <html> (переключателей
 * на экране бывает несколько), а совпавшую с системной не закрепляем — сайт
 * возвращается к «как в системе».
 */

type Theme = "light" | "dark";

function subscribeTheme(onChange: () => void): () => void {
  if (typeof MutationObserver === "undefined") return () => {};
  const observer = new MutationObserver(onChange);
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  return () => observer.disconnect();
}
const readTheme = (): Theme => (document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark");
const serverTheme = (): Theme => "dark";

function isTextField(el: EventTarget | null): boolean {
  if (!(el instanceof HTMLElement)) return false;
  if (el.isContentEditable || el.tagName === "TEXTAREA" || el.tagName === "SELECT") return true;
  if (el.tagName !== "INPUT") return false;
  const type = (el as HTMLInputElement).type;
  return !["button", "checkbox", "radio", "range", "submit", "reset", "file", "color", "image"].includes(type);
}

/** Телефон печатает (фокус в поле при сенсорном экране) — язычок прячем, чтобы не лёг на поле. */
function useTyping(): boolean {
  const [typing, setTyping] = useState(false);
  useEffect(() => {
    const coarse = window.matchMedia?.("(pointer: coarse)");
    const onIn = (e: FocusEvent) => setTyping(Boolean(coarse?.matches) && isTextField(e.target));
    const onOut = () => setTyping(false);
    document.addEventListener("focusin", onIn);
    document.addEventListener("focusout", onOut);
    return () => {
      document.removeEventListener("focusin", onIn);
      document.removeEventListener("focusout", onOut);
    };
  }, []);
  return typing;
}

export default function EdgeThemeToggle() {
  const { t } = useTranslation("common");
  const pathname = usePathname() || "";
  const { mounted, setPreference } = useTheme();
  const theme = useSyncExternalStore(subscribeTheme, readTheme, serverTheme);
  const typing = useTyping();

  // Сервер темы не знает (её ставит скрипт в <head>) — до гидратации ничего не рисуем.
  if (!mounted || pathname.startsWith("/tg")) return null;

  const dark = theme === "dark";
  // Подпись и значок — о том, что сделает нажатие: в тёмной теме — солнце.
  const label = dark
    ? t("theme.to_light", { defaultValue: "Включить светлую тему" })
    : t("theme.to_dark", { defaultValue: "Включить тёмную тему" });
  const Icon = dark ? FiSun : FiMoon;

  const flip = () => {
    const next: Theme = dark ? "light" : "dark";
    setPreference(next === getSystemTheme() ? "system" : next);
  };

  return (
    <button
      type="button"
      onClick={flip}
      aria-label={label}
      title={label}
      data-edge-theme=""
      className={[
        "fixed top-[38%] z-[880] -translate-y-1/2 cursor-pointer print:hidden",
        "right-[env(safe-area-inset-right,0px)]",
        "grid h-11 w-7 place-items-center rounded-l-xl border border-r-0 border-border",
        "bg-surface-2/75 text-muted shadow-md backdrop-blur",
        "opacity-70 transition-[opacity,width,color,background-color] duration-200 motion-reduce:transition-none",
        "hover:w-9 hover:bg-surface-3 hover:text-foreground hover:opacity-100",
        "focus-visible:w-9 focus-visible:text-foreground focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-yellow-400/70",
        typing ? "pointer-events-none !opacity-0" : "",
      ].join(" ")}
      style={{ WebkitTapHighlightColor: "transparent" }}
    >
      <Icon className="size-4" aria-hidden="true" />
    </button>
  );
}
