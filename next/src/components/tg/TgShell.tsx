"use client";

import Script from "next/script";
import { useEffect, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
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
        initDataUnsafe?: { start_param?: string };
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
  const { t } = useTranslation("common");
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
    } catch {}

    // Шапка и фон Telegram — в цвет текущей темы сайта. Раньше они всегда
    // были белыми, а страница в тёмной теме — тёмной: белая полоса сверху.
    // Цвет берём из токена --background, чтобы не дублировать палитру.
    const syncColors = () => {
      try {
        const bg = getComputedStyle(document.documentElement).getPropertyValue("--background").trim();
        if (!/^#[0-9a-f]{6}$/i.test(bg)) return;
        app.setHeaderColor?.(bg);
        app.setBackgroundColor?.(bg);
      } catch {}
    };
    syncColors();
    const themeObserver = new MutationObserver(syncColors);
    themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    const stop = () => themeObserver.disconnect();

    const initData = app.initData || "";
    if (!initData) {
      setStatus(Cookies.get("access") ? "ready" : "guest");
      return stop;
    }
    // Уже входили в этой сессии — initData одноразовый, повторно не шлём.
    if (Cookies.get("access") || sessionStorage.getItem("tg_access")) {
      setStatus("ready");
      return stop;
    }
    // Mini App открыли по ссылке t.me/<бот>/<app>?startapp=ref_CODE (или
    // promo_CODE): параметр запуска несёт код креатора или промокод. Сервер
    // применяет их только при создании аккаунта — без этого регистрации из
    // Mini App не закреплялись ни за кем.
    let startParam = "";
    try {
      startParam =
        app.initDataUnsafe?.start_param ||
        new URLSearchParams(window.location.search).get("tgWebAppStartParam") ||
        "";
    } catch {}
    const ref = /^ref_([A-Za-z0-9]{4,32})$/.exec(startParam)?.[1];
    const promo = /^promo_([A-Za-z0-9_-]{2,48})$/.exec(startParam)?.[1];

    (async () => {
      try {
        const res = await fetch("/api/users/auth/telegram/webapp/", {
          method: "POST",
          headers: { "Content-Type": "application/json", Accept: "application/json" },
          body: JSON.stringify({ init_data: initData, ...(ref ? { ref } : {}), ...(promo ? { promo } : {}) }),
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
    return stop;
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
        <div className="min-h-[100dvh] bg-background p-8 text-center text-muted">
          {t("auth.tg_loading", { defaultValue: "Входим в EsAI…" })}
        </div>
      )}
      {status === "guest" && (
        <div className="min-h-[100dvh] bg-background p-8 text-center text-foreground">
          {t("auth.tg_guest", {
            defaultValue: "Откройте эту страницу из бота EsAI в Telegram — вход произойдёт сам.",
          })}
        </div>
      )}
      {status === "error" && (
        <div className="min-h-[100dvh] bg-background p-8 text-center text-foreground">
          {t("auth.tg_error", {
            defaultValue: "Не удалось войти. Закройте окно и откройте студию из бота ещё раз.",
          })}
        </div>
      )}
    </>
  );
}
