"use client";

import Cookies from "js-cookie";
import { safeReturnPath } from "./returnPath";

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

/**
 * Только свой относительный путь. Проверка общая с middleware
 * (tools/returnPath): одних строковых правил мало — «/\t/evil.com» браузер
 * превращает в «//evil.com», то есть в чужой адрес.
 */
export function isSafeReturnPath(value: unknown): value is string {
  return safeReturnPath(value) !== null;
}

export function rememberReturnPath(path: string): void {
  const safe = safeReturnPath(path);
  if (!safe) return;
  try {
    Cookies.set(COOKIE, safe, {
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
  // Отдаём нормализованный путь — ровно тот, что проверен.
  let chosen = safeReturnPath(fromQuery) || "";
  if (!chosen) chosen = safeReturnPath(Cookies.get(COOKIE)) || "";
  try {
    Cookies.remove(COOKIE);
  } catch {}
  return chosen || fallback;
}
