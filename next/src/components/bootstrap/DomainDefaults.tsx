"use client";

import { useEffect } from "react";

function mapByHost(host: string) {
  const h = (host || "").toLowerCase();
  console.log(h)
  if (h.endsWith("vokalo.ru")) return { locale: "ru", currency: "RUB" } as const;
  if (h.endsWith("vokalo.kg")) return { locale: "kg", currency: "KGS" } as const;
  if (h.endsWith("vokalo.online")) return { locale: "en", currency: "USD" } as const;
  return { locale: "ru", currency: "USD" } as const;
}

export default function DomainDefaults() {
  useEffect(() => {
    try {
      const host = window.location.hostname;
      const desired = mapByHost(host);

      const cookies = document.cookie;
      const has = (name: string) => new RegExp("(?:^|; )" + name + "=").test(cookies);

      let changed = false;

      if (!has("NEXT_LOCALE")) {
        document.cookie = `NEXT_LOCALE=${desired.locale}; path=/; max-age=${60 * 60 * 24 * 365}`;
        changed = true;
      }
      const currMatch = cookies.match(/(?:^|; )APP_CURRENCY=([^;]+)/);
      const currVal = currMatch ? decodeURIComponent(currMatch[1]) : null;
      if (!currVal || !["USD", "RUB", "KGS"].includes(currVal)) {
        document.cookie = `APP_CURRENCY=${desired.currency}; path=/; max-age=${60 * 60 * 24 * 365}`;
        try { localStorage.setItem("APP_CURRENCY", desired.currency); } catch {}
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

