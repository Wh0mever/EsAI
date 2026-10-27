/**
 * Шторка «Скачать» (SaveSheet.tsx): решения без React — их проверяет
 * saveSheetLogic.test.mjs обычным Node.
 */

/**
 * Код ответа из ошибки загрузки файла: tools/saveMedia на ответ не 2xx бросает
 * HttpError с текстом «HTTP 404». Другая ошибка (сеть, вместо файла страница) — null.
 */
export function httpStatusOf(e: unknown): number | null {
  const err = e as { name?: unknown; message?: unknown } | null;
  if (!err || err.name !== "HttpError" || typeof err.message !== "string") return null;
  const match = /^HTTP (\d{3})$/.exec(err.message);
  return match ? Number(match[1]) : null;
}

/**
 * Файла на сервере больше нет (404, 410): удалили или истёк срок хранения.
 * «Повторить» упадёт так же, а «Скачать файл» откроет страницу ошибки — их не показываем.
 */
export const fileGone = (http: number | null | undefined): boolean => http === 404 || http === 410;
