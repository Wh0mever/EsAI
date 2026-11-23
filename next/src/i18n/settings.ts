export const languages = ["ru", "en", "kg"] as const;
export type Language = (typeof languages)[number];

/** Все пространства имён, у которых есть файлы в src/locales/<язык>/. */
export const NAMESPACES = ["common", "home", "creative", "vstudio", "creators", "academy", "qrpay", "privacy", "offer"] as const;
export type Namespace = (typeof NAMESPACES)[number];

/**
 * Нужны на любой странице с серверной отрисовкой: common — общие виджеты корневого
 * layout (кнопка «наверх», баннер установки, напоминание о балансе), home — шапка,
 * меню и подвал. Без common глобальный виджет мог бы «подвиснуть» (suspend) вне
 * границы Suspense после гидрации, поэтому common присылается всегда.
 */
export const BASE_NS: readonly Namespace[] = ["common", "home"];

type Match = "exact" | "prefix";

/**
 * Страницы, которые сервер рисует целиком, с переводами (мобильная скорость:
 * текст и картинка первого экрана — прямо в HTML, без ожидания JS и словарей).
 *
 * Только проверенные на гидрацию: при отрисовке нет чтения cookie/localStorage/
 * window, Date/Math.random — всё это в эффектах или в обработчиках
 * (vstudio2-notes/creative-studio/research/mobile_speed.md §4.2). Вход
 * (шапка, хаб) рисуется по подсказке сервера — components/bootstrap/AuthHint.
 * Остальные страницы — по-старому: дети рисуются в браузере после загрузки переводов.
 *
 * Добавлять страницу сюда — только после такой же проверки всех её клиентских
 * компонентов. Третье поле — пространства имён сверх BASE_NS. Правило: КАЖДОЕ
 * пространство имён, с которым любой компонент страницы (включая вложенные и те,
 * что под своим Suspense) вызывает useTranslation(), должно быть в этом списке —
 * либо такой компонент передаёт { useSuspense: false } и терпит ключи на первом
 * кадре. Иначе сервер отрисует ключи (у серверного экземпляра нет загрузчика), а
 * браузер — переводы после догрузки: расхождение при гидрации. Пример: вынести на
 * хаб виджет vstudio/creators или добавить /studio — не перечислив его
 * пространства имён — сломает страницу.
 */
const SSR_ROUTES: ReadonlyArray<readonly [path: string, match: Match, ns: readonly Namespace[]]> = [
	["/", "exact", ["creative"]], // хаб (HomeHub)
	["/creative", "prefix", ["creative"]], // каталог, /creative/<id> и /creative/works (формы и «Мои работы» — только creative + BASE_NS)
	["/model", "prefix", []], // SEO-страницы моделей (SeoShell — без переводов)
	["/ai", "prefix", []], // SEO-страницы функций
	["/blog", "prefix", []], // блог и статьи
	["/models", "exact", []], // каталог моделей
	["/academy", "exact", ["academy"]],
];

/** Нужна ли странице серверная отрисовка с переводами и какие пространства имён ей прислать. */
export function routeI18n(path: string | null | undefined): { ssr: boolean; ns: Namespace[] } {
	if (path) {
		// "/creative/" и "/creative" — одна страница; "/" не трогаем.
		const p = path.length > 1 && path.endsWith("/") ? path.slice(0, -1) : path;
		for (const [route, match, ns] of SSR_ROUTES) {
			// "/models" не должен совпасть с префиксом "/model", "/creative" — с "/creatives".
			const hit = match === "exact" ? p === route : p === route || p.startsWith(route + "/");
			if (hit) return { ssr: true, ns: Array.from(new Set([...BASE_NS, ...ns])) };
		}
	}
	return { ssr: false, ns: [] };
}

/**
 * Выключатель серверной отрисовки (переменная окружения I18N_SSR, читается на
 * сервере при каждом запросе — пересборка не нужна). По умолчанию включено;
 * "off" (или "0"/"false") возвращает старое поведение на всех страницах.
 */
export function i18nSsrEnabled(): boolean {
	const v = (process.env.I18N_SSR || "").trim().toLowerCase();
	return !(v === "off" || v === "0" || v === "false");
}
