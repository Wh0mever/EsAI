import i18n, { createInstance, type i18n as I18n, type Resource } from "i18next";
import { initReactI18next } from "react-i18next";
import resourcesToBackend from "i18next-resources-to-backend";
import { languages } from "./settings";

i18n
	.use(initReactI18next)
	.use(
		resourcesToBackend((language: string, namespace: string) =>
			import(`../locales/${language}/${namespace}.json`)
		)
	);

export const initI18n = async (lang: string) => {
  if (!i18n.isInitialized) {
    await i18n.init({
      lng: lang,
      // Russian is the only complete locale: with ["kg","ru"] a key missing in
      // English was shown in Kyrgyz.
      fallbackLng: "ru",
      supportedLngs: languages,
      defaultNS: "common",
      // Only namespaces that have files in src/locales (header/terms never existed).
      // privacy/offer грузятся лениво на своих страницах — не тянуть их на каждую.
      ns: ["common", "home"],
      interpolation: { escapeValue: false },
    });
  } else if (i18n.language !== lang) {
    await i18n.changeLanguage(lang);
  }
};

// ---------- Серверная отрисовка с переводами (i18n/settings.ts, SSR_ROUTES) ----------

const BASE = {
	fallbackLng: "ru",
	supportedLngs: languages,
	defaultNS: "common",
	interpolation: { escapeValue: false },
} as const;

/**
 * Копия двух верхних уровней (язык → пространство имён): i18next дописывает в
 * переданный объект новые наборы, а серверный кэш словарей общий для всех запросов.
 * Сами словари не копируются — в них никто не пишет.
 */
const copyTop = (r: Resource): Resource =>
	Object.fromEntries(Object.entries(r).map(([l, nss]) => [l, { ...nss }])) as Resource;

/**
 * Сервер: отдельный экземпляр на каждый запрос (общий синглтон нёс бы язык чужого
 * запроса). Без загрузчика и с готовыми словарями init синхронный; useSuspense
 * выключен — сервер никогда не «подвисает».
 */
export function createServerI18n(lang: string, resources: Resource, ns: string[]): I18n {
	const inst = createInstance();
	void inst.init({
		...BASE,
		lng: lang,
		ns: [...ns],
		resources: copyTop(resources),
		initAsync: false,
		react: { useSuspense: false },
	});
	return inst;
}

/**
 * Браузер: общий синглтон (его переключает lib/locale.ts), но инициализированный
 * СИНХРОННО теми же словарями, что пришли с сервера, — первый рендер в браузере
 * совпадает с HTML (июльский инцидент «мёртвой гидрации»). Остальные пространства
 * имён и языки по-прежнему догружаются лениво через resourcesToBackend
 * (partialBundledLanguages).
 * useSuspense выключен на всю гидрацию, включая границы Suspense, которые React
 * гидратирует отдельным, более поздним проходом (страница под loading.tsx). Включает
 * его I18nProvider только при первой клиентской навигации — дальше недостающее
 * пространство имён снова показывает loading.tsx, как раньше. Пока он выключен,
 * компонент с незагруженным пространством имён рисует ключи (как и сервер) и
 * перерисовывается, когда словарь догрузится, — расхождения нет, но первый экран
 * будет с ключами: поэтому SSR_ROUTES обязан перечислять все такие пространства имён.
 */
export function initI18nSync(lang: string, resources: Resource, ns: string[]): I18n {
	if (!i18n.isInitialized) {
		void i18n.init({
			...BASE,
			lng: lang,
			ns: [...ns],
			resources: copyTop(resources),
			partialBundledLanguages: true,
			initAsync: false,
			react: { useSuspense: false },
		});
	} else {
		// Повторный вызов (StrictMode в разработке): только докладываем словари.
		// changeLanguage здесь нельзя — это setState в других компонентах во время рендера.
		addBundles(i18n, resources);
	}
	return i18n;
}

/** С первой клиентской навигации (I18nProvider): недостающее пространство имён снова «подвешивает» (Suspense → loading.tsx), как в старом пути. */
export function enableSuspense(inst: I18n) {
	inst.options.react = { ...inst.options.react, useSuspense: true };
}

/** Доложить наборы, которых ещё нет в хранилище (существующие не трогаем). */
export function addBundles(inst: I18n, resources: Resource) {
	for (const [lng, nss] of Object.entries(resources)) {
		for (const [ns, data] of Object.entries(nss ?? {})) {
			if (!inst.hasResourceBundle(lng, ns)) inst.addResourceBundle(lng, ns, data, true, false);
		}
	}
}

export default i18n;
