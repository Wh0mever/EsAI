import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';
import { localeFromAcceptLanguage } from '@/lib/localeDetect';
import { SEO_MODELS } from '@/lib/seo/models';
import { SEO_FUNCTIONS } from '@/lib/seo/functions';
import { SITE_URL } from '@/lib/seo/site';
import { safeReturnPath } from '@/tools/returnPath';

// Множества валидных SEO-слагов (чистые данные, edge-safe). Любой другой слаг
// под /model/<x> или /ai/<x> (напр. удалённый /model/mistral) обязан отдавать
// НАСТОЯЩИЙ 404, а не 200. В Next 16 notFound() на этих маршрутах отдаёт 200,
// т.к. корневой layout читает cookies()/headers() → маршрут динамический и
// стримится (статус 200 уходит до notFound()). Поэтому режем в middleware (edge,
// ДО рендера) — гарантированный hard-404 для краулеров, без «мусорных» страниц.
const MODEL_SLUGS = new Set(SEO_MODELS.map((m) => m.slug));
const FUNCTION_SLUGS = new Set(SEO_FUNCTIONS.map((f) => f.slug));

function seoNotFound(): NextResponse {
  const html = `<!doctype html><html lang="ru"><head><meta charset="utf-8"/>` +
    `<meta name="viewport" content="width=device-width,initial-scale=1"/>` +
    `<meta name="robots" content="noindex"/><title>404 — EsAI</title>` +
    `<style>html,body{margin:0;height:100%}body{background:#141414;color:#fff;` +
    `font-family:system-ui,Segoe UI,Roboto,sans-serif;display:flex;align-items:center;` +
    `justify-content:center}main{text-align:center;padding:40px}h1{font-size:72px;margin:0;` +
    `letter-spacing:-2px}p{color:#bdbdbd;margin:12px 0 28px}a{display:inline-block;` +
    `background:#F5C518;color:#141414;font-weight:700;text-decoration:none;padding:12px 26px;` +
    `border-radius:999px}.b{color:#F5C518;font-weight:700}</style></head><body><main>` +
    `<div class="b" style="font-size:22px;letter-spacing:1px;margin-bottom:8px">EsAI</div>` +
    `<h1>404</h1><p>Такой страницы нет. Возможно, она удалена или адрес введён с ошибкой.</p>` +
    `<a href="/">На главную</a></main></body></html>`;
  return new NextResponse(html, {
    status: 404,
    headers: { 'content-type': 'text/html; charset=utf-8' },
  });
}

// --- Продление входа на сервере -------------------------------------------
// access-JWT и его cookie живут 12 ч, refresh — 15 дней. Все проверки «вошёл
// ли человек» смотрят только cookie access, а обновление по refresh случалось
// лишь после 401 — которого не бывает, раз без cookie запрос не уходит. Итог:
// назавтра платящий пользователь видел гостевой режим. Поэтому, если access
// нет/истёк, а refresh есть, обновляем пару здесь, до рендера страницы, и
// кладём cookie с теми же атрибутами, что ставит клиент (js-cookie на
// /auth/signin и в fetchData.refreshAuth): path=/, sameSite=lax, secure на
// https, НЕ httpOnly (их читает клиентский код), срок как у expires 0.5 / 15.
const ACCESS_COOKIE_MAX_AGE = 60 * 60 * 12;
const REFRESH_COOKIE_MAX_AGE = 60 * 60 * 24 * 15;
// Запрос refresh нельзя обрывать рано: сервер ротирует refresh и кладёт
// старый в blacklist — оборванный ответ = потерянная сессия.
const REFRESH_TIMEOUT_MS = 8000;

function jwtExp(token: string | undefined): number | null {
  if (!token) return null;
  const parts = token.split('.');
  if (parts.length !== 3) return null;
  try {
    let b64 = parts[1].replace(/-/g, '+').replace(/_/g, '/');
    while (b64.length % 4) b64 += '=';
    const payload = JSON.parse(atob(b64));
    return typeof payload?.exp === 'number' ? payload.exp : null;
  } catch {
    return null;
  }
}

function jwtAlive(token: string | undefined, skewSeconds = 30): boolean {
  const exp = jwtExp(token);
  return exp != null && exp > Math.floor(Date.now() / 1000) + skewSeconds;
}

/** Origin для запроса к Django из middleware. */
function apiOrigin(request: NextRequest, hostname: string): string {
  // Внутри docker-сети — напрямую в core, мимо Cloudflare. Снаружи все эти
  // запросы пришли бы с одного IP сервера и делили бы на всех анонимный
  // лимит DRF (30 в минуту); напрямую core видит X-Forwarded-For человека.
  const internal = (process.env.INTERNAL_API_ORIGIN || '').replace(/\/$/, '');
  if (internal) return internal;
  const env = (process.env.NEXT_PUBLIC_SITE_URL || '').replace(/\/$/, '');
  if (env) return env;
  // За nginx request.nextUrl может быть http://… — POST на http получит 301 на
  // https и превратится в GET. Для боевого домена идём сразу на https.
  if (hostname.endsWith('esai.kg')) return SITE_URL;
  return request.nextUrl.origin;
}

/**
 * Можно ли на этом запросе обновлять токены. Только настоящая навигация по
 * странице (документ или RSC-переход), без префетчей: их много и параллельно,
 * а каждый лишний refresh — ротация и шанс гонки. Mini App (/tg) живёт в
 * iframe Telegram со своими cookie SameSite=None — туда не лезем.
 */
function canRefreshOn(request: NextRequest, pathname: string): boolean {
  if (request.method !== 'GET') return false;
  if (/\.[a-z0-9]+$/i.test(pathname)) return false; // файлы из public/
  if (pathname.startsWith('/tg') || pathname.startsWith('/auth/callback')) return false;
  const h = request.headers;
  if (h.get('next-router-prefetch') || h.get('purpose') === 'prefetch' || (h.get('sec-purpose') || '').includes('prefetch')) {
    return false;
  }
  const dest = h.get('sec-fetch-dest');
  if (dest === 'iframe' || dest === 'frame') return false;
  try {
    const ref = h.get('referer');
    if (ref && new URL(ref).pathname.startsWith('/tg')) return false;
  } catch {}
  return dest === 'document' || h.get('rsc') === '1' || (!dest && (h.get('accept') || '').includes('text/html'));
}

type RefreshResult = { access: string; refresh?: string } | 'invalid' | null;

async function refreshTokens(request: NextRequest, hostname: string, refresh: string): Promise<RefreshResult> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REFRESH_TIMEOUT_MS);
  try {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      Accept: 'application/json',
      // Прямой вызов core по http внутри docker-сети: без этого заголовка
      // включённый DJANGO_SECURE_SSL_REDIRECT ответил бы 301 на https.
      'X-Forwarded-Proto': 'https',
    };
    // Анонимный троттлинг DRF считает по X-Forwarded-For: без него все
    // обновления из Next шли бы с одного IP сервера и упирались в общий лимит.
    const xff = request.headers.get('x-forwarded-for');
    if (xff) headers['X-Forwarded-For'] = xff;
    const r = await fetch(`${apiOrigin(request, hostname)}/api/users/token/refresh/`, {
      method: 'POST',
      headers,
      body: JSON.stringify({ refresh }),
      cache: 'no-store',
      redirect: 'manual',
      signal: controller.signal,
    });
    if (r.status === 401 || r.status === 400) return 'invalid';
    if (!r.ok) return null;
    const data = await r.json().catch(() => null);
    if (!data || typeof data.access !== 'string' || !data.access) return null;
    return { access: data.access, refresh: typeof data.refresh === 'string' && data.refresh ? data.refresh : undefined };
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

function normalizeHost(input: string) {
  // take first value if proxy adds a list, trim, lowercase, strip port
  const first = (input || '').split(',')[0].trim().toLowerCase();
  return first.split(':')[0];
}

function defaultsByHost(hostname: string) {
  const h = normalizeHost(hostname);
  // EsAI — единственный домен esai.kg (одна валюта — сом).
  if (h.endsWith('esai.kg')) return { locale: 'kg', currency: 'KGS' } as const;
  return { locale: 'kg', currency: 'KGS' } as const; // fallback — kg by default (ТЗ)
}

export async function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // Hard-404 для неизвестных SEO-слагов /model/<x> и /ai/<x> (см. коммент выше).
  const seoMatch = pathname.match(/^\/(model|ai)\/([^/]+)\/?$/);
  if (seoMatch) {
    const kind = seoMatch[1];
    const slug = decodeURIComponent(seoMatch[2]);
    const known = kind === 'model' ? MODEL_SLUGS.has(slug) : FUNCTION_SLUGS.has(slug);
    if (!known) return seoNotFound();
  }

  // Prefer forwarded host/host header, fallback to URL hostname
  const rawHost = request.headers.get('x-forwarded-host') || request.headers.get('host') || request.nextUrl.hostname;
  const hostname = normalizeHost(rawHost);

  // '/admin' убран: /admin (Django) обслуживает nginx мимо Next, а у /admin-new
  // собственный гейт с формой входа по паролю (layout admin-new).
  // '/creators/dashboard' — кабинет креатора: с '/dashboard' он не начинается,
  // поэтому указан отдельно. Публичная /creators остаётся открытой.
  const protectedRoutes = ['/dashboard', '/profile', '/orders', '/creators/dashboard'];
  const authRoutes = ['/auth/signin', '/auth/signup', '/auth/signup'];

  const accessCookie = request.cookies.get('access')?.value;
  const refreshCookie = request.cookies.get('refresh')?.value;

  const isProtected = protectedRoutes.some((route) => pathname.startsWith(route));
  const isAuthRoute = authRoutes.some((route) => pathname.startsWith(route));

  // Живой access — вошёл. Нет/истёк, но есть живой refresh — обновляем здесь.
  let hasAccess = jwtAlive(accessCookie);
  const refreshAlive = jwtAlive(refreshCookie, 0);
  let refreshed: { access: string; refresh?: string } | null = null;
  if (!hasAccess && refreshAlive && refreshCookie && canRefreshOn(request, pathname)) {
    const result = await refreshTokens(request, hostname, refreshCookie);
    if (result && result !== 'invalid') {
      refreshed = result;
      hasAccess = true;
    }
    // 'invalid'/сбой: cookie не трогаем — клиент (fetchData/ensureAccess) сам
    // разберётся; тут это могла быть гонка с параллельной вкладкой.
  }
  // Для гейта /dashboard сессия — это живой access ИЛИ живой refresh: если
  // обновить здесь не вышло (сеть, префетч), страница обновит токен сама.
  const hasSession = hasAccess || refreshAlive;

  // Валюта — по домену (esai.kg→KGS и т.д.). Язык — по языку браузера.
  const desired = defaultsByHost(hostname);
  const browserLocale = localeFromAcceptLanguage(request.headers.get('accept-language'));
  const haveLocale = request.cookies.get('NEXT_LOCALE')?.value;
  const haveCurrency = request.cookies.get('APP_CURRENCY')?.value;
  const manualLocale = request.cookies.get('NEXT_LOCALE_MANUAL')?.value === '1';

  let res: NextResponse;
  if (isProtected && !hasSession) {
    const nextUrl = encodeURIComponent(pathname + (request.nextUrl.search || ''));
    res = NextResponse.redirect(new URL(`/auth/signin?next=${nextUrl}`, request.url));
  } else if (isAuthRoute && hasAccess) {
    // Уже вошёл — уводим со входа туда, куда его и собирались вернуть (?next=),
    // а не всегда в чат. Только живой access: иначе мёртвый refresh давал бы
    // петлю signin → dashboard → signin.
    // Проверка общая с клиентом (tools/returnPath): «/%09/evil.example» без неё
    // уводил вошедшего человека на чужой сайт. Сверяем с origin самого запроса —
    // за nginx он внутренний, но и цель разбирается от него же.
    const target = safeReturnPath(request.nextUrl.searchParams.get('next'), request.url) || '/dashboard/text-chat';
    res = NextResponse.redirect(new URL(target, request.url));
  } else {
    // Путь — в заголовок запроса для корневого layout: главная отдаёт в HTML
    // скрытый H1 до загрузки переводов (components/home/HomeSeoFallback).
    const forwarded = new Headers(request.headers);
    forwarded.set('x-esai-path', pathname);
    forwarded.set('x-esai-search', request.nextUrl.search);
    res = NextResponse.next({ request: { headers: forwarded } });
  }

  if (refreshed) {
    const proto = (request.headers.get('x-forwarded-proto') || request.nextUrl.protocol.replace(':', ''))
      .split(',')[0]
      .trim()
      .toLowerCase();
    const cookieOpts = { path: '/', sameSite: 'lax' as const, secure: proto === 'https', httpOnly: false };
    res.cookies.set('access', refreshed.access, { ...cookieOpts, maxAge: ACCESS_COOKIE_MAX_AGE });
    if (refreshed.refresh) {
      res.cookies.set('refresh', refreshed.refresh, { ...cookieOpts, maxAge: REFRESH_COOKIE_MAX_AGE });
    }
  }

  // Язык интерфейса: пока пользователь НЕ выбрал вручную — держим по языку
  // браузера (ky→kg, ru→ru, en→en, иначе ru). После ручного выбора
  // (NEXT_LOCALE_MANUAL=1) — не трогаем, язык залипает (ТЗ клиента).
  if (!manualLocale && (!haveLocale || !['ru', 'en', 'kg'].includes(haveLocale) || haveLocale !== browserLocale)) {
    res.cookies.set('NEXT_LOCALE', browserLocale, { path: '/', maxAge: 60 * 60 * 24 * 365 });
  }
  // Валюта: cookie отсутствует/битая -> дефолт KGS (первый визит, до того как
  // клиентский геодетект (useCurrency(), GET /api/plans/currency-rate/) успеет
  // отработать). ВАЖНО: домен больше НЕ перетирает cookie при каждой навигации
  // (defaultsByHost всегда возвращает "KGS" — домен один, esai.kg, ветвления
  // никогда не было) — раньше это стирало non-manual RUB, определённый по
  // геолокации IP из России, обратно на KGS на следующей же странице. И ручной,
  // и авто (гео) выбор валюты теперь одинаково залипают до явной смены
  // пользователем — только по-настоящему пустая/невалидная cookie заменяется.
  if (!haveCurrency || !['USD', 'RUB', 'KGS'].includes(haveCurrency)) {
    res.cookies.set('APP_CURRENCY', desired.currency, { path: '/', maxAge: 60 * 60 * 24 * 365 });
  }

  return res;
}

export const config = {
  matcher: ['/((?!api|_next/static|_next/image|favicon.ico).*)'],
};
