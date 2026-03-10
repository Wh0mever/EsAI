"use client";

export type UILang = "ru" | "en" | "kg";

export function setLanguagePreference(code: UILang) {
  try {
    document.cookie = `NEXT_LOCALE=${code}; path=/; max-age=${60 * 60 * 24 * 365}`;
    document.cookie = `NEXT_LOCALE_MANUAL=1; path=/; max-age=${60 * 60 * 24 * 365}`;
  } catch {}
  window.location.reload();
}
