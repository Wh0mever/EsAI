// lib/theme.ts
// Light/dark theme management for EsAI.
// - System preference is the default.
// - Manual choice is persisted in localStorage ("esai-theme") and applied
//   to <html data-theme="...">.
// - An inline bootstrap script (see THEME_BOOTSTRAP) runs before paint to
//   avoid a flash of the wrong theme.

export type ThemePreference = "light" | "dark" | "system";
export type ResolvedTheme = "light" | "dark";

export const THEME_STORAGE_KEY = "esai-theme";

export function getSystemTheme(): ResolvedTheme {
  if (typeof window === "undefined") return "dark";
  return window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches
    ? "light"
    : "dark";
}

export function getStoredPreference(): ThemePreference {
  if (typeof window === "undefined") return "system";
  try {
    const v = window.localStorage.getItem(THEME_STORAGE_KEY);
    if (v === "light" || v === "dark" || v === "system") return v;
  } catch {}
  return "system";
}

export function resolveTheme(pref: ThemePreference): ResolvedTheme {
  return pref === "system" ? getSystemTheme() : pref;
}

export function applyTheme(resolved: ResolvedTheme) {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  root.setAttribute("data-theme", resolved);
  // keep Tailwind's `dark:` variant in sync
  root.classList.toggle("dark", resolved === "dark");
}

export function setThemePreference(pref: ThemePreference) {
  try {
    if (pref === "system") window.localStorage.removeItem(THEME_STORAGE_KEY);
    else window.localStorage.setItem(THEME_STORAGE_KEY, pref);
  } catch {}
  applyTheme(resolveTheme(pref));
}

// Inline, dependency-free script string injected in <head> to set the theme
// before first paint (no flash). Mirrors the logic above.
export const THEME_BOOTSTRAP = `(function(){try{var k='${THEME_STORAGE_KEY}';var p=localStorage.getItem(k);var sys=window.matchMedia&&window.matchMedia('(prefers-color-scheme: light)').matches?'light':'dark';var t=(p==='light'||p==='dark')?p:sys;var e=document.documentElement;e.setAttribute('data-theme',t);e.classList.toggle('dark',t==='dark');}catch(_){document.documentElement.setAttribute('data-theme','dark');document.documentElement.classList.add('dark');}})();`;
