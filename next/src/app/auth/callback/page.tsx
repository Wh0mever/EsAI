"use client";

import { useEffect, useState } from "react";
import Cookies from "js-cookie";
import { useTranslation } from "react-i18next";
import { trackRegistration } from "@/tools/analytics";
import { takeReturnPath } from "@/tools/authNext";

/**
 * AuthCallback — принимает JWT из соц-входа (query `?access&refresh&user`),
 * кладёт их в cookie и уводит в приложение.
 *
 * Устойчивость к мобильным in-app браузерам (Telegram/Instagram), где раньше
 * висело «Processing authentication…»:
 *  - токены читаем НАПРЯМУЮ из window.location (query И fragment), без
 *    useSearchParams (он требует Suspense и капризничает в WebView);
 *  - cookie secure только на https; sameSite=lax (переживает OAuth-возврат);
 *  - pageshow(persisted) — если вкладку вернули из bfcache, форсируем уход;
 *  - жёсткий таймаут-фолбэк + ручная кнопка «Продолжить», чтобы НИКОГДА не
 *    зависнуть.
 */
export default function AuthCallback() {
  const { t } = useTranslation("common");
  const [stuck, setStuck] = useState(false);

  useEffect(() => {
    let navigated = false;
    const go = (url: string) => {
      if (navigated) return;
      navigated = true;
      try { window.location.replace(url); } catch { window.location.href = url; }
    };

    try {
      const qs = new URLSearchParams(window.location.search || "");
      const hs = new URLSearchParams((window.location.hash || "").replace(/^#/, ""));
      // Бэкенд теперь кладёт токены во фрагмент (#): его браузер никуда не
      // отправляет, а query с JWT оседал в логах nginx/Cloudflare. Query —
      // запасной путь для старых ссылок (и ?error=… от соц-входа).
      const get = (k: string) => hs.get(k) || qs.get(k);

      const access = get("access");
      const refresh = get("refresh");
      const user = get("user");

      // Сразу убираем токены из адресной строки и истории браузера.
      try {
        const rest = new URLSearchParams(qs);
        ["access", "refresh", "user", "welcome"].forEach((k) => rest.delete(k));
        const search = rest.toString();
        window.history.replaceState(window.history.state, "", window.location.pathname + (search ? `?${search}` : ""));
      } catch {}

      let nextUrl = "/dashboard/text-chat";

      const secure = window.location.protocol === "https:";

      if (access && refresh) {
        // Бэкенд соц-входа возвращает сюда только токены, без «куда». Путь
        // сохранила страница входа — иначе человек из студии попадал в чат.
        nextUrl = takeReturnPath(nextUrl, get("next"));
        Cookies.remove("access");
        Cookies.remove("refresh");
        Cookies.remove("user");
        Cookies.remove("sessionid");
        Cookies.set("access", access, { expires: 0.5, secure, sameSite: "lax" });
        Cookies.set("refresh", refresh, { expires: 15, secure, sameSite: "lax" });
        if (user) Cookies.set("user", user, { secure, sameSite: "lax" });
        // Новый соц-пользователь (бэк прислал welcome=1) → приветственное окно
        // + конверсия «Регистрация» в Google Ads и цель «registration» в
        // Яндекс.Метрике (только для нового аккаунта).
        let waitingForGoal = false;
        try {
          if (get("welcome")) {
            localStorage.setItem("esai-show-welcome", "1");
            // Событие уходит через sendBeacon и переживёт последующий переход.
            try { (window as any).gtag_report_conversion?.(); } catch {}
            // А вот Метрику ждём: отсюда уходим мгновенно, и цель, поставленная
            // в очередь до загрузки tag.js, пропала бы вместе со страницей.
            // Колбэк сработает и по таймауту, так что зависнуть нельзя.
            waitingForGoal = true;
            trackRegistration(() => go(nextUrl));
          }
        } catch {}
        if (!waitingForGoal) go(nextUrl);
      } else {
        // Нет токенов (например, устаревшая вкладка после выхода) → на вход.
        go("/auth/signin");
      }
    } catch {
      go("/");
    }

    // Вкладка вернулась из bfcache (частый кейс in-app браузеров) → уводим.
    const onShow = (e: PageTransitionEvent) => {
      if (e.persisted) {
        try { window.location.replace("/"); } catch {}
      }
    };
    window.addEventListener("pageshow", onShow);

    // Страховки от зависания: показать кнопку через 2.5с, форс-уход через 6с.
    const t1 = window.setTimeout(() => setStuck(true), 2500);
    const t2 = window.setTimeout(() => { try { window.location.replace("/"); } catch {} }, 6000);

    return () => {
      window.removeEventListener("pageshow", onShow);
      clearTimeout(t1);
      clearTimeout(t2);
    };
  }, []);

  return (
    <div className="w-full min-h-[60vh] flex flex-col items-center justify-center gap-4 p-6 text-center">
      <span className="text-muted">{t("common.processing", { defaultValue: "Обработка..." })}</span>
      {stuck && (
        <a href="/" className="text-accent-strong underline underline-offset-2">
          {t("common.continue", { defaultValue: "Продолжить" })}
        </a>
      )}
    </div>
  );
}
