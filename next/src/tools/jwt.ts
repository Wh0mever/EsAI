// Tiny JWT utils for client-only checks (no crypto verification)
export function parseJwtPayload<T = any>(token: string | undefined | null): T | null {
  if (!token) return null;
  const parts = token.split('.');
  if (parts.length !== 3) return null;
  try {
    const json = atob(parts[1].replace(/-/g, '+').replace(/_/g, '/'));
    return JSON.parse(decodeURIComponent(escape(json)));
  } catch {
    try {
      // Fallback without unicode decode
      return JSON.parse(atob(parts[1].replace(/-/g, '+').replace(/_/g, '/')));
    } catch {
      return null;
    }
  }
}

export function isJwtExpired(token: string | undefined | null, skewSeconds = 30): boolean {
  const payload = parseJwtPayload<{ exp?: number }>(token);
  const exp = payload?.exp;
  if (!exp || typeof exp !== 'number') return true;
  const now = Math.floor(Date.now() / 1000);
  return exp <= (now + skewSeconds);
}

export function isJwtValid(token: string | undefined | null): boolean {
  return !!token && !isJwtExpired(token);
}

