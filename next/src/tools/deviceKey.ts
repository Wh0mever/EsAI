"use client";

import Cookies from "js-cookie";

/**
 * Постоянный идентификатор устройства (UUID).
 *
 * Живёт в localStorage и дублируется в cookie. localStorage удобнее для
 * запросов из браузера, но при входе через Google/Telegram браузер уходит на
 * сторону провайдера и возвращается обычным редиректом — заголовок туда не
 * поставить, а cookie доедет сама. Поэтому оба хранилища, значение одно.
 *
 * Нужен, чтобы отличать «второй аккаунт того же человека» от нового
 * пользователя: почту и IP меняют легко, ключ устройства — заметно сложнее.
 * Раньше он заводился внутри useExitDiscount; вынесен сюда, потому что теперь
 * им пользуются ещё и вход, и блокировки.
 */

export const DEVICE_KEY_STORAGE = "esai_device_key";
const COOKIE_DAYS = 365;

export function getOrCreateDeviceKey(): string {
  if (typeof window === "undefined") return "";
  let key = "";
  try {
    key = window.localStorage.getItem(DEVICE_KEY_STORAGE) || "";
  } catch {
    // Приватный режим — localStorage недоступен, пробуем cookie.
  }
  if (!key) key = Cookies.get(DEVICE_KEY_STORAGE) || "";
  if (!key) {
    try {
      key = crypto.randomUUID();
    } catch {
      key = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
    }
  }
  try {
    window.localStorage.setItem(DEVICE_KEY_STORAGE, key);
  } catch {}
  try {
    // sameSite lax — переживает возврат с OAuth-провайдера.
    Cookies.set(DEVICE_KEY_STORAGE, key, {
      expires: COOKIE_DAYS,
      secure: window.location.protocol === "https:",
      sameSite: "lax",
    });
  } catch {}
  return key;
}

/** Заголовок для fetchData: {} если ключа нет (SSR). */
export function deviceKeyHeader(): Record<string, string> {
  const key = getOrCreateDeviceKey();
  return key ? { "X-Device-Key": key } : {};
}
