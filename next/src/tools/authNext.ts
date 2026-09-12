"use client";

import Cookies from "js-cookie";

/**
 * Куда вернуть человека после входа.
 *
 * Раньше после входа всех без исключения уводило в чат: страница входа
 * параметр ?next= не читала, а соц-вход (Google, Telegram) его и не мог
 * донести — бэкенд возвращает на /auth/callback только с токенами. Студия и
 * тарифы честно отправляли гостя на вход «с возвратом», а он оказывался в чате
 * и терял свой мультфильм.
 *
 * Поэтому путь запоминается в cookie на этом же сайте: он переживает и вход
 * по коду из почты, и уход к Google/Telegram с возвратом обратно.
 */

const COOKIE = "esai_next";

/** Только свой относительный путь: «//evil.com» браузер считает чужим адресом. */
export function isSafeReturnPath(value: unknown): value is string {
  if (typeof value !== "string") return false;
  const path = value.trim();
  return (
    path.startsWith("/") &&
    !path.startsWith("//") &&
    !path.includes("\\") &&
    path.length <= 300 &&
    // Возврат на сам вход — петля.
    !path.startsWith("/auth/")
  );
}

export function rememberReturnPath(path: string): void {
  if (!isSafeReturnPath(path)) return;
  try {
    Cookies.set(COOKIE, path, {
      // Полчаса: хватает на вход по коду из почты, но не всплывёт через неделю.
      expires: 1 / 48,
      sameSite: "lax",
      secure: typeof window !== "undefined" && window.location.protocol === "https:",
    });
  } catch {}
}

/**
 * Забрать путь возврата: из адреса страницы, иначе из cookie. Cookie стирается —
 * следующий вход без явного «куда» снова ведёт по умолчанию.
 * fromQuery ожидается уже раскодированным (URLSearchParams.get так и отдаёт).
 */
export function takeReturnPath(fallback: string, fromQuery?: string | null): string {
  let chosen = "";
  if (isSafeReturnPath(fromQuery)) chosen = fromQuery.trim();
  if (!chosen) {
    const saved = Cookies.get(COOKIE);
    if (isSafeReturnPath(saved)) chosen = saved.trim();
  }
  try {
    Cookies.remove(COOKIE);
  } catch {}
  return chosen || fallback;
}
