import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';
import { languages } from '@/i18n/settings';

export function middleware(request: NextRequest) {
  const cookies = request.cookies;
  const host = request.nextUrl.hostname || '';

  const byHost = (h: string) => {
    const name = h.toLowerCase();
    if (name.endsWith('vokalo.ru')) return { locale: 'ru', currency: 'RUB' } as const;
    if (name.endsWith('vokalo.kg')) return { locale: 'kg', currency: 'KGS' } as const;
    if (name.endsWith('vokalo.online')) return { locale: 'en', currency: 'USD' } as const;
    return { locale: 'ru', currency: 'USD' } as const; // fallback
  };

  const desired = byHost(host);

  const haveLocale = cookies.get('NEXT_LOCALE')?.value;
  const haveCurrency = cookies.get('APP_CURRENCY')?.value;

  const response = NextResponse.next();

  if (!haveLocale || !languages.includes(haveLocale as any)) {
    response.cookies.set('NEXT_LOCALE', desired.locale, { path: '/', maxAge: 60 * 60 * 24 * 365 });
  }
  if (!haveCurrency || !['USD', 'RUB', 'KGS'].includes(haveCurrency)) {
    response.cookies.set('APP_CURRENCY', desired.currency, { path: '/', maxAge: 60 * 60 * 24 * 365 });
  }

  return response;
}

export const config = {
	matcher: ['/((?!api|_next/static|_next/image|favicon.ico).*)'],
};
