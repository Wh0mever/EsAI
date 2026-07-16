// Чистое определение языка интерфейса по заголовку Accept-Language.
// Runtime-agnostic: используется и в middleware (edge), и в корневом layout
// (server) — без браузерных/клиентских зависимостей.
//
// Логика (ТЗ клиента): ky/kg → kg, ru → ru, en → en, иначе → ru (русский).

export type UILocale = "ru" | "en" | "kg";

export function localeFromAcceptLanguage(header?: string | null): UILocale {
  const h = (header || "").toLowerCase();
  // Берём языковые теги по порядку приоритета (q-веса игнорируем — порядок
  // браузеры и так выставляют по убыванию приоритета).
  for (const part of h.split(",")) {
    const tag = part.split(";")[0].trim();
    if (!tag) continue;
    if (tag.startsWith("ky") || tag.startsWith("kg")) return "kg";
    if (tag.startsWith("ru")) return "ru";
    if (tag.startsWith("en")) return "en";
  }
  return "ru"; // язык не определён — по умолчанию русский
}
