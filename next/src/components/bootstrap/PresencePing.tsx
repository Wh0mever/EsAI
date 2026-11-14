"use client";

import { useEffect, useRef } from "react";
import { usePathname } from "next/navigation";
import { ensureAccess, fetchData } from "@/tools/fetchData";

/**
 * Отметка «вкладка открыта» для счётчика онлайна в админке (users.presence).
 *
 * Пока вкладка на виду — раз в 45 секунд, плюс сразу при смене раздела и
 * возвращении во вкладку. Скрытая вкладка молчит: в онлайне только те, кто
 * сейчас реально смотрит на сайт. Id посетителя случайный и живёт в
 * localStorage — три вкладки одного человека считаются одним онлайном.
 */

const PING_MS = 45_000;
const VID_KEY = "esai-vid";

function visitorId(): string | null {
  try {
    let id = localStorage.getItem(VID_KEY);
    if (!id || !/^[A-Za-z0-9-]{16,64}$/.test(id)) {
      id =
        typeof crypto !== "undefined" && "randomUUID" in crypto
          ? crypto.randomUUID()
          : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 14)}`;
      localStorage.setItem(VID_KEY, id);
    }
    return id;
  } catch {
    return null; // хранилище закрыто — не считаем, чем каждый раз выдумывать нового посетителя
  }
}

function sectionOf(pathname: string | null): string {
  const p = pathname || "/";
  if (p === "/" || p.startsWith("/dashboard") || p.startsWith("/chat")) return "chat";
  if (p.startsWith("/video-studio")) return "video_studio";
  if (p === "/studio" || p.startsWith("/studio/") || p.startsWith("/tg/studio")) return "studio";
  if (p === "/merge" || p.startsWith("/merge/")) return "merge";
  if (p.startsWith("/pricing")) return "pricing";
  return "other";
}

export default function PresencePing() {
  const pathname = usePathname();
  const section = useRef(sectionOf(pathname));
  const last = useRef(0);

  useEffect(() => {
    // Админку в онлайн не считаем: это мы сами.
    if (pathname?.startsWith("/admin-new")) return;
    section.current = sectionOf(pathname);

    const ping = async () => {
      if (document.visibilityState !== "visible") return;
      const vid = visitorId();
      if (!vid) return;
      last.current = Date.now();
      try {
        const authed = await ensureAccess();
        await fetchData("users/presence/", "POST", { vid, section: section.current }, authed);
      } catch {
        /* счётчик — не повод шуметь в консоли */
      }
    };

    void ping();
    const timer = window.setInterval(() => void ping(), PING_MS);
    const onVisible = () => {
      if (document.visibilityState === "visible" && Date.now() - last.current > 10_000) void ping();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [pathname]);

  return null;
}
