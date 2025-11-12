"use client";

export type UILang = "ru" | "en" | "kg";

export function domainForLanguage(code: UILang): string {
  if (code === "ru") return "vokalo.ru";
  if (code === "kg") return "vokalo.kg";
  if (code === "en") return "vokalo.online";
  return "vokalo.ru";
}

export function redirectToLanguageDomain(code: UILang) {
  // New approach: stay on current domain and just change locale cookies
  try {
    document.cookie = `NEXT_LOCALE=${code}; path=/; max-age=${60 * 60 * 24 * 365}`;
    document.cookie = `NEXT_LOCALE_MANUAL=1; path=/; max-age=${60 * 60 * 24 * 365}`;
  } catch {}
  // Reload current page to apply translations and currency middleware
  window.location.reload();
}
