"use client";

import i18n from "@/i18n/i18n";

export type UILang = "ru" | "en" | "kg";

/**
 * Switch the UI language instantly (no full-page reload).
 * - persists NEXT_LOCALE + NEXT_LOCALE_MANUAL cookies
 * - calls i18n.changeLanguage so react-i18next re-renders in place
 */
export function setLanguagePreference(code: UILang) {
  try {
    document.cookie = `NEXT_LOCALE=${code}; path=/; max-age=${60 * 60 * 24 * 365}`;
    document.cookie = `NEXT_LOCALE_MANUAL=1; path=/; max-age=${60 * 60 * 24 * 365}`;
  } catch {}
  // Update <html lang> for accessibility / SEO without a reload.
  try {
    if (typeof document !== "undefined") document.documentElement.lang = code === "kg" ? "ky" : code;
  } catch {}
  // Instant, in-place language change.
  void i18n.changeLanguage(code);
}
