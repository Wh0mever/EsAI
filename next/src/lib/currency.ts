export type Currency = "USD" | "RUB" | "KGS";

function readCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.match(new RegExp("(?:^|; )" + name.replace(/([.$?*|{}()\[\]\\\/\+^])/g, "\\$1") + "=([^;]*)"));
  return match ? decodeURIComponent(match[1]) : null;
}

function currencyFromHost(hostname: string | undefined | null): Currency {
  const h = (hostname || "").toLowerCase();
  if (h.endsWith("vokalo.ru")) return "RUB";
  if (h.endsWith("vokalo.kg")) return "KGS";
  if (h.endsWith("vokalo.online")) return "USD";
  return "USD";
}

export function getInitialCurrency(): Currency {
  if (typeof window === "undefined") return "USD";
  const ls = window.localStorage.getItem("APP_CURRENCY");
  if (ls === "USD" || ls === "RUB" || ls === "KGS") return ls;

  const ck = readCookie("APP_CURRENCY");
  if (ck === "USD" || ck === "RUB" || ck === "KGS") return ck;

  return currencyFromHost(window.location.hostname);
}

export function persistCurrency(code: Currency) {
  if (typeof window !== "undefined") {
    try { window.localStorage.setItem("APP_CURRENCY", code); } catch {}
    try { document.cookie = `APP_CURRENCY=${code}; path=/; max-age=${60 * 60 * 24 * 365}`; } catch {}
  }
}

