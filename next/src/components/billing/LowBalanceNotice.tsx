"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";
import { FiAlertTriangle, FiX, FiZap } from "react-icons/fi";
import { ensureAccess, fetchData } from "@/tools/fetchData";
import { requestTopUp } from "@/lib/topupRequest";

/**
 * Напоминание «кредиты заканчиваются» (ТЗ клиента 09.11.2026).
 *
 * Когда показывать, решает сервер (/api/plans/balance/ → low_balance): остаток
 * 20 % и 10 % от последнего купленного пакета, каждый порог один раз за цикл,
 * новая покупка начинает цикл заново. Здесь только показ: отметили на сервере
 * «показано» — на другом устройстве второй раз не всплывёт.
 *
 * Плашка сверху справа, под шапкой: внизу у студий панели с кнопкой «Создать»,
 * в чате — поле ввода. Ничего не блокирует и генерацию не трогает. Окно
 * нехватки кредитов при запуске генерации — отдельное и остаётся как было.
 */

type Notice = { level: number; cycle: number; base: number };

const POLL_MS = 120_000;
/** 20 % — мягкое: само уходит через 20 с. 10 % — висит, пока не закроют. */
const SOFT_HIDE_MS = 20_000;

function hiddenOn(pathname: string | null): boolean {
  if (!pathname) return true;
  return (
    pathname.startsWith("/pricing") ||
    pathname.startsWith("/admin-new") ||
    pathname.startsWith("/auth") ||
    pathname === "/save"
  );
}

function isStudio(pathname: string | null): boolean {
  return !!pathname && (pathname === "/studio" || pathname.startsWith("/studio/") || pathname.startsWith("/tg/studio"));
}

function seenKey(n: Notice) {
  return `esai-lowbal:${n.cycle}:${n.level}`;
}

export default function LowBalanceNotice() {
  const { t } = useTranslation("common");
  const pathname = usePathname();
  const router = useRouter();
  const [notice, setNotice] = useState<Notice | null>(null);
  const showing = useRef(false);
  const hovered = useRef(false);
  const path = useRef(pathname);
  useEffect(() => {
    path.current = pathname;
  }, [pathname]);

  const check = useCallback(async () => {
    if (showing.current || typeof document === "undefined" || document.visibilityState !== "visible") return;
    // На тарифах и в админке не показываем — и «показано» там не отмечаем.
    if (hiddenOn(path.current)) return;
    if (!(await ensureAccess())) return;
    try {
      const res = await fetchData<{ low_balance?: Notice | null }>("plans/balance/", "GET", null, true);
      const n = res?.ok ? res.data?.low_balance : null;
      if (!n || showing.current || hiddenOn(path.current)) return;
      try {
        if (localStorage.getItem(seenKey(n)) === "1") return;
        localStorage.setItem(seenKey(n), "1");
      } catch {
        /* приватный режим — опираемся на сервер */
      }
      showing.current = true;
      setNotice(n);
      void fetchData("plans/balance/low-seen/", "POST", { level: n.level, cycle: n.cycle }, true).catch(() => {});
    } catch {
      /* сеть — проверим в следующий раз */
    }
  }, []);

  // Смена страницы, «balance:refresh» после генерации/оплаты, возврат во вкладку и редкий опрос.
  useEffect(() => {
    if (hiddenOn(pathname)) return;
    void check();
  }, [pathname, check]);

  useEffect(() => {
    const onRefresh = () => void check();
    const onVisible = () => document.visibilityState === "visible" && void check();
    window.addEventListener("balance:refresh", onRefresh);
    document.addEventListener("visibilitychange", onVisible);
    const timer = window.setInterval(() => void check(), POLL_MS);
    return () => {
      window.removeEventListener("balance:refresh", onRefresh);
      document.removeEventListener("visibilitychange", onVisible);
      window.clearInterval(timer);
    };
  }, [check]);

  const close = useCallback(() => {
    showing.current = false;
    setNotice(null);
  }, []);

  useEffect(() => {
    if (!notice || notice.level !== 20) return;
    const timer = window.setTimeout(function hide() {
      if (hovered.current) {
        // Человек навёл курсор — не прячем из-под руки.
        window.setTimeout(hide, 3000);
        return;
      }
      close();
    }, SOFT_HIDE_MS);
    return () => window.clearTimeout(timer);
  }, [notice, close]);

  if (!notice || hiddenOn(pathname)) return null;

  const urgent = notice.level <= 10;
  const onCta = () => {
    close();
    if (requestTopUp()) return;
    router.push(isStudio(pathname) ? "/pricing/studio" : "/pricing");
  };

  return (
    <div className="pointer-events-none fixed inset-x-0 top-[calc(3.5rem_+_env(safe-area-inset-top,0px)_+_0.5rem)] z-[1150] flex justify-center px-3 sm:justify-end sm:px-4">
      <div
        role={urgent ? "alert" : "status"}
        aria-live={urgent ? "assertive" : "polite"}
        onMouseEnter={() => (hovered.current = true)}
        onMouseLeave={() => (hovered.current = false)}
        className={`pointer-events-auto flex w-full max-w-sm items-start gap-3 rounded-2xl bg-surface p-3.5 shadow-lg ${
          urgent ? "border-2 border-accent shadow-accent/20" : "border border-border"
        }`}
      >
        <span
          aria-hidden
          className={`grid h-9 w-9 shrink-0 place-items-center rounded-xl ${
            urgent ? "bg-accent text-on-accent" : "bg-accent/15 text-accent-strong"
          }`}
        >
          {urgent ? <FiAlertTriangle /> : <FiZap />}
        </span>
        <div className="min-w-0 flex-1">
          <p className={`text-sm leading-snug text-foreground ${urgent ? "font-semibold" : ""}`}>
            {urgent
              ? t("low_balance.urgent_text", {
                  defaultValue: "У вас осталось совсем немного кредитов! Пополните баланс и продолжайте создавать контент с EsAI.",
                })
              : t("low_balance.soft_text", {
                  defaultValue:
                    "Ваш баланс постепенно заканчивается. Пополните счёт, чтобы продолжить создавать видео, мультфильмы и изображения без перерыва.",
                })}
          </p>
          <button
            type="button"
            onClick={onCta}
            className={`mt-2.5 inline-flex cursor-pointer items-center gap-1.5 rounded-full px-4 py-1.5 text-sm font-semibold transition-colors ${
              urgent
                ? "bg-accent text-on-accent hover:bg-accent-strong"
                : "border border-accent/60 text-accent-strong hover:bg-accent/10"
            }`}
          >
            {urgent
              ? t("low_balance.urgent_cta", { defaultValue: "Выбрать тариф" })
              : t("low_balance.soft_cta", { defaultValue: "Пополнить баланс" })}
          </button>
        </div>
        <button
          type="button"
          onClick={close}
          aria-label={t("low_balance.close", { defaultValue: "Закрыть" })}
          className="-mr-1 -mt-1 cursor-pointer p-1 text-lg leading-none text-muted-2 hover:text-foreground"
        >
          <FiX />
        </button>
      </div>
    </div>
  );
}
