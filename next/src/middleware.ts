import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';
import { localeFromAcceptLanguage } from '@/lib/localeDetect';
import { SEO_MODELS } from '@/lib/seo/models';
import { SEO_FUNCTIONS } from '@/lib/seo/functions';

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

export function middleware(request: NextRequest) {
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
  const protectedRoutes = ['/dashboard', '/profile', '/orders'];
  const authRoutes = ['/auth/signin', '/auth/signup', '/auth/signup'];

  const accessToken = request.cookies.get('access');

  const isProtected = protectedRoutes.some((route) => pathname.startsWith(route));
  const isAuthRoute = authRoutes.some((route) => pathname.startsWith(route));

  // Валюта — по домену (esai.kg→KGS и т.д.). Язык — по языку браузера.
  const desired = defaultsByHost(hostname);
  const browserLocale = localeFromAcceptLanguage(request.headers.get('accept-language'));
  const haveLocale = request.cookies.get('NEXT_LOCALE')?.value;
  const haveCurrency = request.cookies.get('APP_CURRENCY')?.value;
  const manualLocale = request.cookies.get('NEXT_LOCALE_MANUAL')?.value === '1';

  let res: NextResponse;
  if (isProtected && !accessToken) {
    const nextUrl = encodeURIComponent(pathname + (request.nextUrl.search || ''));
    res = NextResponse.redirect(new URL(`/auth/signin?next=${nextUrl}`, request.url));
  } else if (isAuthRoute && accessToken) {
    res = NextResponse.redirect(new URL('/dashboard/text-chat', request.url));
  } else {
    res = NextResponse.next();
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
