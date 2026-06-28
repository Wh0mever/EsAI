export type Currency = "USD" | "RUB" | "KGS";

function readCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.match(new RegExp("(?:^|; )" + name.replace(/([.$?*|{}()\[\]\\\/\+^])/g, "\\$1") + "=([^;]*)"));
  return match ? decodeURIComponent(match[1]) : null;
}

function currencyFromHost(hostname: string | undefined | null): Currency {
  const h = (hostname || "").toLowerCase();
  // EsAI hosts
  if (h.endsWith("esai.kg")) return "KGS";
  if (h.endsWith("esai.ru")) return "RUB";
  if (h.endsWith("esai.online") || h.endsWith("esai.com")) return "USD";
  // Legacy Vokalo hosts (kept for backward compatibility)
  if (h.endsWith("vokalo.ru")) return "RUB";
  if (h.endsWith("vokalo.kg")) return "KGS";
  if (h.endsWith("vokalo.online")) return "USD";
  return "KGS"; // kg by default (ТЗ)
}

export function getInitialCurrency(): Currency {
  if (typeof window === "undefined") return "USD";
  const manualCookie = readCookie("APP_CURRENCY_MANUAL");
  const ls = (() => { try { return window.localStorage.getItem("APP_CURRENCY"); } catch { return null; } })();
  const ck = readCookie("APP_CURRENCY");

  const isManual = manualCookie === "1";
  if (isManual && (ls === "USD" || ls === "RUB" || ls === "KGS")) return ls as Currency;

  if (ck === "USD" || ck === "RUB" || ck === "KGS") return ck as Currency;

  return currencyFromHost(window.location.hostname);
}

export function persistCurrency(code: Currency, markManual = true) {
  if (typeof window !== "undefined") {
    try { window.localStorage.setItem("APP_CURRENCY", code); } catch {}
    try { if (markManual) window.localStorage.setItem("APP_CURRENCY_SOURCE", "manual"); } catch {}
    try { document.cookie = `APP_CURRENCY=${code}; path=/; max-age=${60 * 60 * 24 * 365}`; } catch {}
    try { if (markManual) document.cookie = `APP_CURRENCY_MANUAL=1; path=/; max-age=${60 * 60 * 24 * 365}`; } catch {}
  }
}
