/**
 * Код языка для API.
 *
 * Часть текста витрины лежит в базе и переводится там же (пакеты кредитов,
 * библиотека студии), поэтому запросы за таким содержимым несут `?lang=`.
 *
 * i18n у нас работает с «kg», но в браузер и в <html lang> уходит корректный
 * «ky» — и именно он иногда возвращается обратно из i18n.language. Приводим
 * оба к тому, что понимает бэкенд.
 */
export type ApiLang = "ru" | "en" | "kg";

export function apiLang(language?: string | null): ApiLang {
	const code = (language || "ru").toLowerCase().slice(0, 2);
	if (code === "ky" || code === "kg") return "kg";
	return code === "en" ? "en" : "ru";
}
