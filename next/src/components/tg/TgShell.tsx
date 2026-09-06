"use client";

import Script from "next/script";
import { useEffect, useState, type ReactNode } from "react";
import Cookies from "js-cookie";
import { setSessionTokens } from "@/tools/fetchData";

/**
 * Обёртка страниц Mini App: сайт внутри Telegram с автологином.
 *
 * Telegram передаёт подписанные данные пользователя в initData; сервер
 * проверяет подпись токеном бота и отдаёт токены того же аккаунта, что
 * и в боте. Дальше страница работает как обычный сайт: те же компоненты,
 * тот же API. Шапки и подвала здесь нет — у Telegram свои.
 */
type Status = "loading" | "ready" | "guest" | "error";

declare global {
  interface Window {
    Telegram?: {
      WebApp?: {
        initData?: string;
        ready: () => void;
        expand: () => void;
        colorScheme?: string;
        setHeaderColor?: (c: string) => void;
        setBackgroundColor?: (c: string) => void;
      };
    };
  }
}

export default function TgShell({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Status>("loading");
  const [scriptReady, setScriptReady] = useState(false);

  useEffect(() => {
    if (!scriptReady) return;
    const app = window.Telegram?.WebApp;
    if (!app) {
      // Открыли не из Telegram — ведём себя как обычный сайт.
      setStatus(Cookies.get("access") ? "ready" : "guest");
      return;
    }
    try {
      app.ready();
      app.expand();
      app.setHeaderColor?.("#ffffff");
      app.setBackgroundColor?.("#ffffff");
    } catch {}

    const initData = app.initData || "";
    if (!initData) {
      setStatus(Cookies.get("access") ? "ready" : "guest");
      return;
    }
    // Уже входили в этой сессии — initData одноразовый, повторно не шлём.
    if (Cookies.get("access") || sessionStorage.getItem("tg_access")) {
      setStatus("ready");
      return;
    }
    (async () => {
      try {
        const res = await fetch("/api/users/auth/telegram/webapp/", {
          method: "POST",
          headers: { "Content-Type": "application/json", Accept: "application/json" },
          body: JSON.stringify({ init_data: initData }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok || !data?.access) {
          setStatus("error");
          return;
        }
        setSessionTokens(data.access, data.refresh || "");
        setStatus("ready");
      } catch {
        setStatus("error");
      }
    })();
  }, [scriptReady]);

  return (
    <>
      <Script
        src="https://telegram.org/js/telegram-web-app.js"
        strategy="afterInteractive"
        onLoad={() => setScriptReady(true)}
        onError={() => setScriptReady(true)}
      />
      {status === "ready" && children}
      {status === "loading" && (
        <div style={{ padding: 32, textAlign: "center", color: "#666" }}>Входим в EsAI…</div>
      )}
      {status === "guest" && (
        <div style={{ padding: 32, textAlign: "center" }}>
          Откройте эту страницу из бота EsAI в Telegram — вход произойдёт сам.
        </div>
      )}
      {status === "error" && (
        <div style={{ padding: 32, textAlign: "center" }}>
          Не удалось войти. Закройте окно и откройте студию из бота ещё раз.
        </div>
      )}
    </>
  );
}
