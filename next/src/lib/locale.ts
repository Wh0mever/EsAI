"use client";

export type UILang = "ru" | "en" | "kg";

export function domainForLanguage(code: UILang): string {
  if (code === "ru") return "vokalo.ru";
  if (code === "kg") return "vokalo.kg";
  if (code === "en") return "vokalo.online";
  return "vokalo.ru";
}

export function redirectToLanguageDomain(code: UILang) {
  try {
    // Mark manual choice on current domain (helps if we stay on same domain)
    document.cookie = `NEXT_LOCALE=${code}; path=/; max-age=${60 * 60 * 24 * 365}`;
    document.cookie = `NEXT_LOCALE_MANUAL=1; path=/; max-age=${60 * 60 * 24 * 365}`;
  } catch {}

  const targetDomain = domainForLanguage(code);
  const { protocol, hostname, pathname, search, hash } = window.location;
  const same = hostname.toLowerCase().endsWith(targetDomain);
  const knownDomains = ["vokalo.ru", "vokalo.kg", "vokalo.online"];
  const onKnownDomain = knownDomains.some(d => hostname.toLowerCase().endsWith(d));

  const path = `${pathname}${search}${hash}`;
  // Helper to read cookie value without deps
  const readCookie = (name: string) => {
    try {
      const m = document.cookie.match(new RegExp('(?:^|; )' + name + '=([^;]+)'));
      return m ? decodeURIComponent(m[1]) : null;
    } catch { return null; }
  };
  const access = readCookie("access");
  const refresh = readCookie("refresh");
  const user = readCookie("user");

  if (same || !onKnownDomain) {
    // Same domain family already, or dev env: just reload to apply cookies
    window.location.reload();
    return;
  }

  // If authenticated, hand off tokens via callback, then return to current path
  if (access && refresh) {
    const nextParam = encodeURIComponent(path || "/");
    const qp = new URLSearchParams();
    qp.set("access", access);
    qp.set("refresh", refresh);
    if (user) qp.set("user", user);
    qp.set("next", nextParam);
    window.location.href = `${protocol}//${targetDomain}/auth/callback?${qp.toString()}`;
  } else {
    // Not authenticated: just go to same path on target domain
    window.location.href = `${protocol}//${targetDomain}${path}`;
  }
}
