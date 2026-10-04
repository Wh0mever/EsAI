"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Скопировать текст в буфер. Запасной путь через невидимый textarea обязателен:
 * в webview Telegram и Instagram navigator.clipboard часто недоступен
 * (та же логика, что в components/ui/CopyField.tsx).
 */
export async function copyText(value: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(value);
    return true;
  } catch {
    // ниже — запасной путь
  }
  try {
    const area = document.createElement("textarea");
    area.value = value;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    const done = document.execCommand("copy");
    document.body.removeChild(area);
    return done;
  } catch {
    return false;
  }
}

/**
 * Копирование с отметкой «Скопировано» на две секунды. copied — ключ кнопки,
 * которая сработала последней: на экране несколько кнопок, отметка у одной.
 */
export function useCopy(): { copied: string | null; copy: (key: string, value: string) => Promise<void> } {
  const [copied, setCopied] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );

  const copy = useCallback(async (key: string, value: string) => {
    if (!value) return;
    const done = await copyText(value);
    if (!done) return;
    setCopied(key);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setCopied(null), 2000);
  }, []);

  return { copied, copy };
}
