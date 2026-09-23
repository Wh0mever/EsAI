/**
 * Проверка пути возврата после входа (?next=, cookie esai_next).
 *
 * Общая для middleware (edge) и клиента (tools/authNext), поэтому без
 * "use client" и без зависимостей.
 *
 * Строковых проверок мало: парсер URL молча выкидывает \t, \r, \n из любого
 * места, и «/\t/evil.example» после new URL() превращается в «//evil.example» —
 * редирект на чужой сайт. Поэтому управляющие символы отбрасываем, а итог
 * дополнительно разбираем как URL и сверяем origin.
 */

// Для пути от корня («/…», но не «//…») результат разбора от хоста не зависит,
// важно лишь, чтобы схема была «особой» (https), как у настоящего сайта: тогда
// парсер ведёт себя как браузер (например, «\» считает за «/»).
const PROBE_BASE = "https://esai.kg";

// C0 и C1 управляющие символы + DEL.
const CONTROL_CHARS = /[\u0000-\u001F\u007F-\u009F]/;

/**
 * Свой относительный путь или null. Возвращает уже нормализованный вид
 * (pathname + search + hash) — ровно то, куда уйдёт браузер.
 */
export function safeReturnPath(value: unknown, base: string = PROBE_BASE): string | null {
  if (typeof value !== "string") return null;
  const path = value.trim();
  if (
    !path.startsWith("/") ||
    // «//evil.com» браузер считает чужим адресом.
    path.startsWith("//") ||
    path.includes("\\") ||
    path.length > 300 ||
    CONTROL_CHARS.test(path)
  ) {
    return null;
  }
  let url: URL;
  let origin: string;
  try {
    url = new URL(path, base);
    origin = new URL(base).origin;
  } catch {
    return null;
  }
  if (url.origin !== origin) return null;
  // Возврат на сам вход — петля. Смотрим уже разобранный путь: «/./auth/signin» — тоже вход.
  if (url.pathname.startsWith("/auth/")) return null;
  return url.pathname + url.search + url.hash;
}
