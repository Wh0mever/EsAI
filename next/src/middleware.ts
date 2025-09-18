import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

function defaultsByHost(hostname: string) {
  const h = (hostname || '').toLowerCase();
  if (h.endsWith('vokalo.ru')) return { locale: 'ru', currency: 'RUB' } as const;
  if (h.endsWith('vokalo.kg')) return { locale: 'kg', currency: 'KGS' } as const;
  if (h.endsWith('vokalo.online')) return { locale: 'en', currency: 'USD' } as const;
  return { locale: 'ru', currency: 'USD' } as const; // fallback
}

export function middleware(request: NextRequest) {
  const { pathname, hostname } = request.nextUrl;

  const protectedRoutes = ['/dashboard', '/profile', '/orders', '/admin'];
  const authRoutes = ['/auth/signin', '/auth/signup', '/auth/signup'];

  const accessToken = request.cookies.get('access');

  const isProtected = protectedRoutes.some((route) => pathname.startsWith(route));
  const isAuthRoute = authRoutes.some((route) => pathname.startsWith(route));

  // Pick desired defaults from host
  const desired = defaultsByHost(hostname);
  const haveLocale = request.cookies.get('NEXT_LOCALE')?.value;
  const haveCurrency = request.cookies.get('APP_CURRENCY')?.value;

  let res: NextResponse;
  if (isProtected && !accessToken) {
    res = NextResponse.redirect(new URL('/auth/signin', request.url));
  } else if (isAuthRoute && accessToken) {
    res = NextResponse.redirect(new URL('/dashboard/text-chat', request.url));
  } else {
    res = NextResponse.next();
  }

  if (!haveLocale || !['ru', 'en', 'kg'].includes(haveLocale)) {
    res.cookies.set('NEXT_LOCALE', desired.locale, { path: '/', maxAge: 60 * 60 * 24 * 365 });
  }
  if (!haveCurrency || !['USD', 'RUB', 'KGS'].includes(haveCurrency)) {
    res.cookies.set('APP_CURRENCY', desired.currency, { path: '/', maxAge: 60 * 60 * 24 * 365 });
  }

  return res;
}

export const config = {
  matcher: ['/((?!api|_next/static|_next/image|favicon.ico).*)'],
};
