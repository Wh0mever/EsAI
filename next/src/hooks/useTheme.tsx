"use client";

import { useCallback, useEffect, useState } from "react";
import {
  applyTheme,
  getStoredPreference,
  getSystemTheme,
  resolveTheme,
  setThemePreference as persistPreference,
  type ResolvedTheme,
  type ThemePreference,
} from "@/lib/theme";

/**
 * useTheme — read/control the EsAI light/dark theme.
 * Default is the system preference; manual choice persists in localStorage.
 */
export function useTheme() {
  const [preference, setPreferenceState] = useState<ThemePreference>("system");
  const [resolved, setResolved] = useState<ResolvedTheme>("dark");
  const [mounted, setMounted] = useState(false);

  // Hydrate from storage on mount.
  useEffect(() => {
    const pref = getStoredPreference();
    setPreferenceState(pref);
    setResolved(resolveTheme(pref));
    setMounted(true);
  }, []);

  // React to OS theme changes while in "system" mode.
  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const mq = window.matchMedia("(prefers-color-scheme: light)");
    const onChange = () => {
      if (getStoredPreference() === "system") {
        const sys = getSystemTheme();
        setResolved(sys);
        applyTheme(sys);
      }
    };
    mq.addEventListener?.("change", onChange);
    return () => mq.removeEventListener?.("change", onChange);
  }, []);

  const setPreference = useCallback((pref: ThemePreference) => {
    setPreferenceState(pref);
    setResolved(resolveTheme(pref));
    persistPreference(pref);
  }, []);

  // Simple toggle between light and dark (collapses "system" to its resolved value first).
  const toggle = useCallback(() => {
    setPreference(resolved === "dark" ? "light" : "dark");
  }, [resolved, setPreference]);

  return { preference, theme: resolved, mounted, setPreference, toggle };
}
