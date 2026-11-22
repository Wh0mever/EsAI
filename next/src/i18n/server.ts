// Только для серверного кода (корневой layout). В браузер этот модуль не попадает:
// клиентские компоненты его не импортируют — словари приходят пропсами I18nProvider.
import type { Resource, ResourceLanguage } from "i18next";
import { NAMESPACES, type Language, type Namespace } from "./settings";

type Dict = { [k: string]: unknown };

async function loadDict(lng: Language, ns: Namespace): Promise<Dict> {
	if (!(NAMESPACES as readonly string[]).includes(ns)) throw new Error(`i18n: unknown namespace ${ns}`);
	const mod = await import(`../locales/${lng}/${ns}.json`);
	return (mod.default ?? mod) as Dict;
}

/** Ключи из base, которых нет в target: русский запасной вариант для en (≈40 ключей в common); для kg — пусто. */
function missing(base: Dict, target: Dict | undefined): Dict | null {
	const out: Dict = {};
	let any = false;
	for (const [k, v] of Object.entries(base)) {
		const tv = target?.[k];
		if (v && typeof v === "object" && !Array.isArray(v)) {
			const sub = missing(v as Dict, tv && typeof tv === "object" ? (tv as Dict) : undefined);
			if (sub) {
				out[k] = sub;
				any = true;
			}
		} else if (tv === undefined) {
			out[k] = v;
			any = true;
		}
	}
	return any ? out : null;
}

export type I18nPayload = { resources: Resource; ns: Namespace[] };

// Словари одинаковы для всех посетителей: 3 языка × несколько наборов пространств имён.
// Из кэша только читают — createServerI18n/initI18nSync копируют верхние уровни.
const cache = new Map<string, Promise<I18nPayload>>();

/**
 * Словари для серверной отрисовки страницы: язык посетителя целиком и русский —
 * только недостающее (для kg — пустые наборы). Пустой русский набор обязателен:
 * без него i18next пошёл бы за ru через загрузчик, и инициализация стала бы
 * асинхронной (на сервере — текст ключами, в браузере — расхождение при гидрации).
 */
export function loadI18nResources(lang: Language, ns: Namespace[]): Promise<I18nPayload> {
	const list = Array.from(new Set(ns));
	const key = `${lang}:${list.join(",")}`;
	let hit = cache.get(key);
	if (!hit) {
		hit = (async () => {
			const own = await Promise.all(list.map((n) => loadDict(lang, n)));
			const resources: Resource = { [lang]: Object.fromEntries(list.map((n, i) => [n, own[i]])) as ResourceLanguage };
			if (lang !== "ru") {
				const ru = await Promise.all(list.map((n) => loadDict("ru", n)));
				resources.ru = Object.fromEntries(list.map((n, i) => [n, missing(ru[i], own[i]) ?? {}])) as ResourceLanguage;
			}
			return { resources, ns: list };
		})();
		// Сбой чтения не кэшируем навсегда — следующий запрос попробует снова.
		hit.catch(() => cache.delete(key));
		cache.set(key, hit);
	}
	return hit;
}
