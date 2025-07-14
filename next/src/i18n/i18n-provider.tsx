'use client';

import { ReactNode, useEffect, useState } from "react";
import { I18nextProvider } from "react-i18next";
import i18n, { initI18n } from "./i18n";

export function I18nProvider({ children, lang }: { children: ReactNode; lang: string }) {
	const [ready, setReady] = useState(false);

	useEffect(() => {
		initI18n(lang).then(() => setReady(true));
	}, [lang]);

	if (!ready) return null;

	return <I18nextProvider i18n={i18n}>{children}</I18nextProvider>;
}
