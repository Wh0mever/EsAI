import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';
import { languages } from '@/i18n/settings';

export function middleware(request: NextRequest) {
	const locale = request.cookies.get('NEXT_LOCALE')?.value;

	if (!locale || !languages.includes(locale as any)) {
		const fallback = 'ru';
		const response = NextResponse.next();
		response.cookies.set('NEXT_LOCALE', fallback);
		return response;
	}

	return NextResponse.next();
}

export const config = {
	matcher: ['/((?!api|_next/static|_next/image|favicon.ico).*)'],
};
