"use client";

import { useEffect, useState, useCallback } from "react";
import { usePathname } from "next/navigation";
import { useTranslation } from "react-i18next";
import Cookies from "js-cookie";
import { autoResubscribe } from "@/tools/webPush";

/** beforeinstallprompt event (not in TS DOM lib). */
type BeforeInstallPromptEvent = Event & {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed"; platform: string }>;
};

const DISMISS_KEY = "esai-pwa-install-dismissed";

function isStandalone(): boolean {
  if (typeof window === "undefined") return false;
  return (
    window.matchMedia?.("(display-mode: standalone)").matches ||
    // iOS Safari
    (window.navigator as Navigator & { standalone?: boolean }).standalone === true
  );
}

function isIos(): boolean {
  if (typeof window === "undefined") return false;
  const ua = window.navigator.userAgent || "";
  const iOS = /iphone|ipad|ipod/i.test(ua);
  // iPadOS 13+ reports as Mac; detect by touch.
  const iPadOS = /Macintosh/i.test(ua) && "ontouchend" in document;
  return iOS || iPadOS;
}

/**
 * Встроенные браузеры мессенджеров/соцсетей (Telegram, Instagram, Facebook,
 * LINE): «На экран Домой» там нет, подсказка про установку только мешает.
 */
function isInAppBrowser(): boolean {
  if (typeof window === "undefined") return false;
  const ua = window.navigator.userAgent || "";
  const w = window as Window & {
    TelegramWebviewProxy?: unknown;
    Telegram?: { WebApp?: { initData?: unknown } };
  };
  return (
    /Telegram|Instagram|FBAN|FBAV|FB_IAB|\bLine\//i.test(ua) ||
    typeof w.TelegramWebviewProxy !== "undefined" ||
    typeof w.Telegram?.WebApp?.initData === "string"
  );
}

/** Страницы с чатом: поле ввода внизу экрана — туда баннер ставить нельзя. */
function isChatPath(pathname: string | null): boolean {
  if (!pathname) return false;
  return pathname === "/" || pathname.startsWith("/dashboard");
}

/**
 * Видеостудия занимает весь экран: внизу баннер закрывал панель запроса с
 * кнопкой «Создать», вверху — заголовок первого экрана. Там его не показываем;
 * человек увидит предложение на любой другой странице.
 */
function isStudioPath(pathname: string | null): boolean {
  return Boolean(pathname && pathname.startsWith("/video-studio"));
}

/**
 * PwaManager — registers the service worker and renders the brand-styled
 * "Install app" banner (beforeinstallprompt on Android/Chrome, manual hint on iOS).
 * Mounted once in the root layout. Renders nothing until something is actionable.
 */
export default function PwaManager() {
  const { t } = useTranslation("common");
  const pathname = usePathname();
  const [deferred, setDeferred] = useState<BeforeInstallPromptEvent | null>(null);
  const [showBanner, setShowBanner] = useState(false);
  const [showIosHint, setShowIosHint] = useState(false);

  /* ---------- register service worker ---------- */
  useEffect(() => {
    if (typeof window === "undefined") return;
    if (!("serviceWorker" in navigator)) return;
    if (process.env.NODE_ENV !== "production") {
      // Avoid SW caching interfering with `next dev`.
      return;
    }
    const onLoad = () => {
      navigator.serviceWorker
        .register("/sw.js")
        .then(() => {
          // Only for users who already opted in (cookie access) AND already
          // granted notifications — silently refresh their push subscription
          // (endpoint can rotate). NEVER request permission here: iOS requires
          // a user gesture, so the actual opt-in lives on a button in the UI.
          try {
            if (
              Cookies.get("access") &&
              "Notification" in window &&
              Notification.permission === "granted"
            ) {
              autoResubscribe();
            }
          } catch {
            /* non-fatal */
          }
        })
        .catch((err) => {
          // Non-fatal: app works without SW.
          console.warn("[PWA] SW registration failed", err);
        });
    };
    if (document.readyState === "complete") onLoad();
    else window.addEventListener("load", onLoad, { once: true });
    return () => window.removeEventListener("load", onLoad);
  }, []);

  /* ---------- install prompt wiring ---------- */
  useEffect(() => {
    if (typeof window === "undefined") return;
    if (isStandalone()) return; // already installed
    // Во встроенном браузере Telegram/Instagram установить PWA нельзя.
    if (isInAppBrowser()) return;

    let dismissed = false;
    try {
      dismissed = localStorage.getItem(DISMISS_KEY) === "1";
    } catch {}
    if (dismissed) return;

    const onBeforeInstall = (e: Event) => {
      e.preventDefault();
      setDeferred(e as BeforeInstallPromptEvent);
      setShowBanner(true);
    };
    const onInstalled = () => {
      setShowBanner(false);
      setShowIosHint(false);
      setDeferred(null);
      try {
        localStorage.setItem(DISMISS_KEY, "1");
      } catch {}
    };

    window.addEventListener("beforeinstallprompt", onBeforeInstall);
    window.addEventListener("appinstalled", onInstalled);

    // iOS never fires beforeinstallprompt — show a manual hint after a short delay.
    let iosTimer: number | undefined;
    if (isIos()) {
      iosTimer = window.setTimeout(() => setShowIosHint(true), 3500);
    }

    return () => {
      window.removeEventListener("beforeinstallprompt", onBeforeInstall);
      window.removeEventListener("appinstalled", onInstalled);
      if (iosTimer) window.clearTimeout(iosTimer);
    };
  }, []);

  const dismiss = useCallback(() => {
    setShowBanner(false);
    setShowIosHint(false);
    try {
      localStorage.setItem(DISMISS_KEY, "1");
    } catch {}
  }, []);

  const install = useCallback(async () => {
    if (!deferred) return;
    try {
      await deferred.prompt();
      const choice = await deferred.userChoice;
      if (choice.outcome === "accepted") {
        try {
          localStorage.setItem(DISMISS_KEY, "1");
        } catch {}
      }
    } catch {
      /* ignore */
    } finally {
      setDeferred(null);
      setShowBanner(false);
    }
  }, [deferred]);

  if ((!showBanner && !showIosHint) || isStudioPath(pathname)) return null;

  // На страницах чата баннер внизу закрывал поле ввода (особенно iOS-подсказка,
  // которая всплывает сама через 3.5 с) — там показываем его сверху, под шапкой.
  const onChat = isChatPath(pathname);

  return (
    <div
      className={
        "fixed inset-x-0 z-[1100] px-3 pointer-events-none " +
        (onChat
          ? "top-[calc(3.5rem_+_env(safe-area-inset-top,0px)_+_0.5rem)]"
          : "bottom-0 pb-[max(0.75rem,env(safe-area-inset-bottom))]")
      }
    >
      <div className="pointer-events-auto mx-auto max-w-md rounded-2xl border border-border bg-surface shadow-lg p-3.5 flex items-start gap-3">
        {/* ring: тёмный квадрат метки не сливается с bg-surface в тёмной теме */}
        <img src="/esai-mark.svg" alt="EsAI" className="w-10 h-10 rounded-xl ring-1 ring-border shrink-0" />
        <div className="min-w-0 flex-1">
          <p className="text-foreground font-semibold text-sm">
            {t("pwa.install_title", { defaultValue: "Установить приложение EsAI" })}
          </p>
          {showIosHint ? (
            <p className="text-muted text-xs mt-1 leading-relaxed">
              {t("pwa.ios_hint", {
                defaultValue: "Нажмите «Поделиться», затем «На экран „Домой“».",
              })}
            </p>
          ) : (
            <p className="text-muted text-xs mt-1 leading-relaxed">
              {t("pwa.install_desc", {
                defaultValue: "Быстрый доступ к чату с экрана телефона, как обычное приложение.",
              })}
            </p>
          )}
          <div className="mt-2.5 flex items-center gap-2">
            {!showIosHint && (
              <button
                type="button"
                onClick={install}
                className="rounded-full bg-accent text-on-accent text-sm font-semibold px-4 py-1.5 hover:bg-accent-strong transition-colors cursor-pointer"
              >
                {t("pwa.install_cta", { defaultValue: "Установить" })}
              </button>
            )}
            <button
              type="button"
              onClick={dismiss}
              className="rounded-full border border-border text-muted text-sm px-4 py-1.5 hover:text-foreground hover:bg-surface-2 transition-colors cursor-pointer"
            >
              {t("pwa.dismiss", { defaultValue: "Не сейчас" })}
            </button>
          </div>
        </div>
        <button
          type="button"
          onClick={dismiss}
          aria-label={t("pwa.dismiss", { defaultValue: "Закрыть" })}
          className="text-muted-2 hover:text-foreground text-lg leading-none cursor-pointer -mt-1 -mr-1"
        >
          ×
        </button>
      </div>
    </div>
  );
}
