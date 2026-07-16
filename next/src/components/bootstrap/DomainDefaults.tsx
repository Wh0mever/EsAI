"use client";

import { useEffect } from "react";

function mapByHost(host: string) {
  const h = (host || "").toLowerCase();
  // EsAI — единственный домен esai.kg (одна валюта — сом).
  if (h.endsWith("esai.kg")) return { locale: "kg", currency: "KGS" } as const;
  return { locale: "kg", currency: "KGS" } as const; // kg by default (ТЗ)
}

export default function DomainDefaults() {
  useEffect(() => {
    try {
      const host = window.location.hostname;
      const desired = mapByHost(host);

      const cookies = document.cookie;
      const has = (name: string) => new RegExp("(?:^|; )" + name + "=").test(cookies);
      const get = (name: string) => {
        const m = cookies.match(new RegExp("(?:^|; )" + name + "=([^;]+)"));
        return m ? decodeURIComponent(m[1]) : null;
      };

      let changed = false;

      // Язык интерфейса больше НЕ привязан к домену — он определяется по языку
      // браузера (middleware + layout) и залипает после ручного выбора. Здесь
      // оставлена только синхронизация ВАЛЮТЫ по домену.
      const manualCurr = get("APP_CURRENCY_MANUAL") === "1";
      const currVal = get("APP_CURRENCY");
      if (!manualCurr && currVal !== desired.currency) {
        document.cookie = `APP_CURRENCY=${desired.currency}; path=/; max-age=${60 * 60 * 24 * 365}`;
        try {
          localStorage.setItem("APP_CURRENCY", desired.currency);
          localStorage.setItem("APP_CURRENCY_SOURCE", "domain");
        } catch {}
        changed = true;
      }

      // Avoid infinite reloads
      const guardKey = "DOMAIN_DEFAULTS_APPLIED";
      const already = sessionStorage.getItem(guardKey);
      if (changed && !already) {
        sessionStorage.setItem(guardKey, "1");
        window.location.reload();
      }
    } catch {}
  }, []);
  return null;
}
