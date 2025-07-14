// middleware.ts
import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  const protectedRoutes = ['/in'];
  // const protectedRoutes = ['/dashboard', '/profile', '/orders', '/admin'];

  const isProtected = protectedRoutes.some((route) => pathname.startsWith(route));

  if (isProtected) {
    return NextResponse.redirect(new URL('/auth', request.url));
  }

  return NextResponse.next();
}
