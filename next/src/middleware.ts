import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  const protectedRoutes = ['/dashboard', '/profile', '/orders', '/admin'];
  const isProtected = protectedRoutes.some((route) => pathname.startsWith(route));

  const accessToken = request.cookies.get('access');

  if (isProtected && !accessToken) {
    return NextResponse.redirect(new URL('/auth/signin', request.url));
  }

  return NextResponse.next();
}
