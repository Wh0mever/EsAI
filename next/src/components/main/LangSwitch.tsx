"use client";

import clsx from "clsx";
import Cookies from "js-cookie";
import { useTranslation } from "react-i18next";
import { setLanguagePreference } from "@/lib/locale";

/**
 * LangSwitch — компактный переключатель языка (флажки в ряд). Вынесен из тяжёлого
 * мобильного меню в шапку, чтобы не нагружать навигацию (запрос клиента).
 */
const LANGS = [
  { code: "ru", icon: "/images/local/ru.webp", label: "Русский" },
  { code: "en", icon: "/images/local/en.webp", label: "English" },
  { code: "kg", icon: "/images/local/kg.webp", label: "Кыргызча" },
] as const;

export default function LangSwitch({ className }: { className?: string }) {
  const { i18n } = useTranslation();
  const current = i18n.language || Cookies.get("NEXT_LOCALE") || "kg";

  return (
    <div className={clsx("flex items-center gap-1.5", className)}>
      {LANGS.map(({ code, icon, label }) => (
        <button
          key={code}
          type="button"
          onClick={() => setLanguagePreference(code)}
          aria-label={label}
          title={label}
          className={clsx(
            "h-8 w-8 rounded-lg overflow-hidden border transition-all active:scale-95 cursor-pointer",
            current === code
              ? "border-accent ring-1 ring-accent"
              : "border-neutral-700 opacity-60 hover:opacity-100"
          )}
        >
          <img src={icon} alt={label} className="h-full w-full object-cover" />
        </button>
      ))}
    </div>
  );
}
