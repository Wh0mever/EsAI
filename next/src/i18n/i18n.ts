import i18n from "i18next";
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
      fallbackLng: "ru",
      supportedLngs: languages,
      defaultNS: "common",
      ns: ["common", "header", "home"],
      interpolation: { escapeValue: false },
    });
  } else if (i18n.language !== lang) {
    await i18n.changeLanguage(lang);
  }
};

export default i18n;
